"""Local CPU cost estimates, trained only by completed authoring jobs."""
import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
from time import perf_counter_ns
import warnings


APPLICATION_ID = 0x4152454C
MIN_PAIRS = 4
RECHECK_INTERVAL = 32
MAX_SAMPLES = 4096
MODEL_COLUMNS = "runs,pairs,reference_ns,candidate_ns,log_gain,recent_wins,blocked"


def default_db():
    root = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return root / "are-softwaregpu" / "learning-v1.sqlite3"


@lru_cache(maxsize=128)
def _hash_file(path, size, modified):
    with open(path, "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def implementation_id(*paths):
    digest = hashlib.sha256()
    for path in (Path(__file__), *map(Path, paths)):
        info = path.stat()
        digest.update(bytes.fromhex(_hash_file(path, info.st_size, info.st_mtime_ns)))
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _host_id():
    cpu = platform.processor()
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="ascii", errors="replace") as info:
                cpu = next((line.strip() for line in info if line.startswith("model name")), cpu)
        except OSError:
            pass
    identity = (platform.node(), platform.system(), platform.machine(), platform.python_version(), cpu)
    return hashlib.sha256(repr(identity).encode()).hexdigest()[:20]


def scope_key(**fields):
    # Local machine identity is hashed. Asset names and paths are not features.
    fields["host"] = _host_id()
    try:
        fields["cpu_count"] = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        fields["cpu_count"] = os.cpu_count()
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), allow_nan=False)


def bucket(value):
    """Lower power of two, with a distinct empty bucket."""
    return 1 << (int(value).bit_length() - 1) if value else 0


def smooth(previous, sample):
    return sample if previous is None else previous + .25 * (sample - previous)


@dataclass
class Model:
    runs: int = 0
    pairs: int = 0
    reference_ns: float | None = None
    candidate_ns: float | None = None
    log_gain: float | None = None
    recent_wins: int = 0
    blocked: bool = False

    def update(self, reference_ns, candidate_ns, outcome):
        self.runs += 1
        if reference_ns is not None:
            self.reference_ns = smooth(self.reference_ns, reference_ns)
        if outcome in ("candidate-error", "mismatch"):
            self.blocked = True
            return
        if candidate_ns is not None:
            self.candidate_ns = smooth(self.candidate_ns, candidate_ns)
        if outcome == "matched":
            self.pairs += 1
            gain = math.log(reference_ns / candidate_ns)
            self.log_gain = smooth(self.log_gain, max(-math.log(4), min(math.log(4), gain)))
            self.recent_wins = ((self.recent_wins << 1) | (candidate_ns < reference_ns)) & 15

    def prefers_candidate(self):
        return (not self.blocked and self.pairs >= MIN_PAIRS
                and self.recent_wins.bit_count() >= 3 and self.log_gain > math.log(1.10)
                and self.candidate_ns < self.reference_ns)


class LocalLearner:
    """SQLite serializes updates after measurement. No lock is held while rendering."""
    def __init__(self, path, *, create=True):
        self.path = Path(path).expanduser().resolve()
        if not create:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as conn:
                if (conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID or
                        conn.execute("PRAGMA user_version").fetchone()[0] != 1):
                    raise ValueError("Unrecognized ARE learning database")
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            app = conn.execute("PRAGMA application_id").fetchone()[0]
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if (app, version) == (APPLICATION_ID, 1):
                return
            if app or version or conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
                raise ValueError("Unrecognized ARE learning database")
            conn.execute("CREATE TABLE models (scope TEXT PRIMARY KEY, runs INTEGER, pairs INTEGER,"
                         " reference_ns REAL, candidate_ns REAL, log_gain REAL, recent_wins INTEGER, blocked INTEGER)")
            conn.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY, scope TEXT, outcome TEXT,"
                         " served TEXT, reference_ns INTEGER, candidate_ns INTEGER,"
                         " reference_hash TEXT, candidate_hash TEXT)")
            conn.execute("CREATE INDEX samples_scope ON samples(scope)")
            conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            conn.execute("PRAGMA user_version = 1")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=2)

    @staticmethod
    def _model(conn, key):
        row = conn.execute(f"SELECT {MODEL_COLUMNS} FROM models WHERE scope=?", (key,)).fetchone()
        return Model(*row) if row else Model()

    def _record(self, key, outcome, served, times, hashes):
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._model(conn, key)
            current.update(times[False], times[True], outcome)
            conn.execute(f"INSERT OR REPLACE INTO models(scope,{MODEL_COLUMNS}) VALUES(?,?,?,?,?,?,?,?)",
                         (key, *asdict(current).values()))
            row = conn.execute("INSERT INTO samples(scope,outcome,served,reference_ns,candidate_ns,"
                               "reference_hash,candidate_hash) VALUES(?,?,?,?,?,?,?)",
                               (key, outcome, served, *times, *hashes))
            expired = row.lastrowid - MAX_SAMPLES
            if expired > 0:
                old = conn.execute("SELECT scope FROM samples WHERE id=?", (expired,)).fetchone()
                conn.execute("DELETE FROM samples WHERE id<=?", (expired,))
                if old:
                    conn.execute("DELETE FROM models WHERE scope=? AND NOT EXISTS "
                                 "(SELECT 1 FROM samples WHERE scope=?)", (old[0], old[0]))
            return row.lastrowid

    def execute(self, key, run, fingerprint=None, publish=None):
        """run(False) is the reference. Comparison passes start from the same input."""
        try:
            with closing(self._connect()) as conn:
                model = self._model(conn, key)
        except sqlite3.Error as exc:
            result = run(False)
            if publish:
                publish(result)
            return result, {"outcome": "store-unavailable", "served": "reference", "error": str(exc)}

        times = [None, None]
        hashes = [None, None]

        def timed(alternative):
            start = perf_counter_ns()
            result = run(alternative)
            times[alternative] = max(1, perf_counter_ns() - start)
            return result

        probe = (fingerprint is not None and not model.blocked and
                 (model.pairs < MIN_PAIRS or model.runs % RECHECK_INTERVAL == 0))
        use_candidate = fingerprint is not None and model.prefers_candidate() and not probe
        outcome = "single" if fingerprint is not None else "observe"
        reference = None
        has_reference = False
        if probe and model.pairs % 2 == 0:
            reference = timed(False)
            has_reference = True
        if probe or use_candidate:
            try:
                candidate = timed(True)
                if probe:
                    hashes[True] = fingerprint(candidate)
            except Exception as exc:
                # Candidate work is private. A failing reference still propagates to the caller.
                warnings.warn(f"ARE candidate rejected: {type(exc).__name__}", RuntimeWarning)
                outcome = "candidate-error"
                use_candidate = False
        if use_candidate:
            result = candidate
        else:
            result = reference if has_reference else timed(False)
            if probe and outcome != "candidate-error":
                hashes[False] = fingerprint(result)
                outcome = "matched" if hashes[False] == hashes[True] else "mismatch"
        if publish:
            publish(result)
        served = "candidate" if use_candidate else "reference"
        receipt = {"scope": key, "outcome": outcome, "served": served}
        try:
            receipt["sample_id"] = self._record(key, outcome, served, times, hashes)
        except sqlite3.Error as exc:
            receipt["store_error"] = str(exc)
        return result, receipt

    def status(self):
        with closing(self._connect()) as conn:
            return [{"scope": json.loads(row[0]), **asdict(Model(*row[1:])),
                     "preferred": "candidate" if Model(*row[1:]).prefers_candidate() else "reference"}
                    for row in conn.execute(f"SELECT scope,{MODEL_COLUMNS} FROM models ORDER BY scope")]

    def samples(self, limit=MAX_SAMPLES):
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM samples ORDER BY id DESC LIMIT ?",
                                                       (max(0, min(limit, MAX_SAMPLES)),))]


@lru_cache(maxsize=8)
def _learner(path):
    return LocalLearner(path)


def configured_learner():
    setting = os.getenv("ARE_LEARNING_DB")
    if setting == "off":
        return None
    path = Path(setting).expanduser() if setting else default_db()
    try:
        if not setting and not path.is_file():
            return None
        return _learner(str(path.resolve()))
    except (OSError, sqlite3.Error, ValueError) as exc:
        warnings.warn(f"ARE learning disabled: {exc}", RuntimeWarning)
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["enable", "status", "dataset"])
    parser.add_argument("--db", type=Path)
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of recent dataset rows")
    args = parser.parse_args(argv)
    configured = os.getenv("ARE_LEARNING_DB")
    path = args.db or (Path(configured) if configured and configured != "off" else default_db())
    if args.action != "enable" and not path.expanduser().is_file():
        parser.error(f"No learning database: {path}")
    learner = LocalLearner(path, create=args.action == "enable")
    if args.action == "dataset":
        for sample in learner.samples(args.limit):
            print(json.dumps(sample, sort_keys=True))
    else:
        print(json.dumps({"database": str(learner.path), "profiles": learner.status()}, indent=2))


if __name__ == "__main__":
    main()
