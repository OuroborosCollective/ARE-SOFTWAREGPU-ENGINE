"""Fail-closed CPU ranking reader. Historical receipts remain immutable.

Julia is an independent correctness oracle, NOT a directly comparable full-frame
backend. Only same-scene/same-resolution/same-effect median times are ranked.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WAVE = ROOT / "evidence/spherepop-wave-ranked-cpu-20261020.json"
WINDOW = ROOT / "evidence/single-origin-time-window-20261020.json"
BACKENDS = ("native-cpp", "batch-first", "tiles")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
# Original unchanged archive identity. Its claimed self-digest is noncanonical.
ARCHIVED_GIT_BLOB = "6db5b618934cc0108a93a797c2dbbf4437d8608e"
ARCHIVED_CLAIMED_SHA256 = "3850a06e6f1996ac28dd77af6b927f9b9e78a6cbacc9d937ce244cfa3391ebee"
ARCHIVED_HEAD = "381f3a8d7053293d0b978128a6ad05f551a5ea9e"


def require(condition, code):
    if not condition:
        raise ValueError(code)


def digest(document):
    """Same canonical JSON body convention as the existing wave receipt."""
    raw = json.dumps({k: v for k, v in document.items() if k != "sha256"},
                     sort_keys=True, separators=(",", ":"), allow_nan=False,
                     default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def samples(row, key, count):
    values = row[key]
    require(isinstance(values, list) and len(values) == count,
            "RANKING_SAMPLE_COUNT")
    require(all(type(x) in (float, int) and math.isfinite(x) and x > 0
                for x in values), "RANKING_SAMPLE_INVALID")
    return values


def checked_median(values, claimed):
    median = statistics.median(values)
    require(type(claimed) in (float, int) and math.isfinite(claimed) and
            math.isclose(median, claimed, rel_tol=1e-8, abs_tol=1e-7),
            "RANKING_MEDIAN_DRIFT")
    return median


def verify_wave_integrity(receipt):
    """New receipts need canonical SHA-256. One historical Git blob is pinned.

    The archived receipt's declared self-digest is inconsistent with canonical
    JSON. This exception is permitted only for the exact unchanged repository
    blob and must be reported. No new receipt may use this exception.
    """
    claimed = receipt.get("sha256")
    require(bool(HEX64.fullmatch(str(claimed))), "RANKING_RECEIPT_SHA")
    if claimed == digest(receipt):
        return "canonical-sha256"
    raw = WAVE.read_bytes()
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    git_blob = hashlib.sha1(header + raw).hexdigest()
    require(git_blob == ARCHIVED_GIT_BLOB, "RANKING_ARCHIVE_GIT_BLOB_DRIFT")
    require(receipt == json.loads(raw) and
            claimed == ARCHIVED_CLAIMED_SHA256 and
            receipt.get("head_sha") == ARCHIVED_HEAD,
            "RANKING_RECEIPT_SHA")
    return "legacy-git-blob-pinned-self-digest-mismatch"


def check_current_checkout(receipt, integrity):
    """Current-run receipts must bind to exactly this checkout and source tree."""
    require(integrity == "canonical-sha256", "RANKING_CURRENT_NONCANONICAL")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                  text=True, timeout=10).strip()
    require(receipt["head_sha"] == sha, "RANKING_CURRENT_HEAD_DRIFT")
    actual = {}
    for path in receipt["source_sha256"]:
        source = ROOT / path
        require(source.is_file() and source.resolve().is_relative_to(ROOT),
                "RANKING_CURRENT_SOURCE_UNAVAILABLE")
        actual[path] = hashlib.sha256(source.read_bytes()).hexdigest()
    require(actual == receipt["source_sha256"], "RANKING_CURRENT_SOURCE_DRIFT")


def validate_wave(receipt, *, strict_current=False):
    require(receipt.get("protocol") == "are.spherepop-wave-ranked-benchmark.v1"
            and receipt.get("no_physical_gpu_comparison") is True
            and receipt.get("no_production_speedup_claim") is True,
            "RANKING_WAVE_PROTOCOL")
    integrity = verify_wave_integrity(receipt)
    require(bool(re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("head_sha", ""))))
            and receipt.get("authority") == "measured-single-host-CPU-only"
            and receipt.get("source_sha256"),
            "RANKING_SOURCE_UNBOUND")
    for h in receipt["source_sha256"].values():
        require(bool(HEX64.fullmatch(str(h))), "RANKING_SOURCE_HASH")
    if strict_current:
        check_current_checkout(receipt, integrity)
    rows = receipt.get("rows")
    require(isinstance(rows, list) and rows, "RANKING_WAVE_EMPTY")
    seen = set()
    board = []
    for row in rows:
        key = (row["scene"], row["pixels"])
        require(key not in seen and isinstance(row["pixels"], int) and
                row["pixels"] in (32, 64), "RANKING_SCENE_DUPLICATE")
        seen.add(key)
        n = row["repeats"]
        require(type(n) is int and n >= 15, "RANKING_REPETITIONS")
        require(row["wave_metrics"]["finalized"] == row["pixels"] ** 2 and
                row["wave_metrics"]["refused"] > 0 and
                row["wave_metrics"]["tinted"] > 0,
                "RANKING_WAVE_NOT_EXERCISED")
        refs = row["reference"]
        effect = row["effect"]
        for key_name in ("rgba_sha256", "depth_sha256"):
            require(bool(HEX64.fullmatch(str(refs[key_name]))) and
                    bool(HEX64.fullmatch(str(effect[key_name]))),
                    "RANKING_FRAME_HASH")
        require(refs["depth_sha256"] == effect["depth_sha256"] and
                refs["rgba_sha256"] != effect["rgba_sha256"],
                "RANKING_FRAME_PARITY")
        require(set(row["modes"]) == set(BACKENDS), "RANKING_BACKEND_SET")
        entry = {"scene": row["scene"], "pixels": row["pixels"],
                 "triangles": row["triangles"], "pairs": n, "ranks": []}
        for backend in BACKENDS:
            data = row["modes"][backend]
            off = samples(data["raw_ms"], "off", n)
            on = samples(data["raw_ms"], "on", n)
            checked_median(off, data["raster_only"]["median"])
            median = checked_median(on, data["raster_plus_wave"]["median"])
            checked_median([a/b for a, b in zip(off, on)],
                           data["effect_cost_ratio_paired"]["median"])
            entry["ranks"].append({"backend": backend, "median_ms": median,
                                   "iqr_ms": data["raster_plus_wave"]["iqr"]})
        for backend in BACKENDS:
            on = row["modes"][backend]["raw_ms"]["on"]
            baseline = row["modes"]["tiles"]["raw_ms"]["on"]
            checked_median([a / b for a, b in zip(baseline, on)],
                           row["ranking_with_wave"][backend]["median"])
        entry["ranks"].sort(key=lambda x: (x["median_ms"], x["backend"]))
        board.append(entry)
    return sorted(board, key=lambda x: (x["pixels"], x["scene"]))


def validate_window(receipt):
    require(receipt.get("protocol") == "are.single-origin-time-window.native-ablation.v1",
            "RANKING_WINDOW_PROTOCOL")
    require(bool(re.fullmatch(r"[0-9a-f]{40}",
                              str(receipt.get("source_commit", "")))),
            "RANKING_WINDOW_SOURCE")
    rows = receipt.get("rows")
    require(isinstance(rows, list) and len(rows) == 4,
            "RANKING_WINDOW_ROWS")
    seen = set()
    board = []
    for row in rows:
        px = row["pixels"]
        require(px in (32, 64, 128, 256) and px not in seen
                and row["pairs"] >= 15
                and row["mode"] == "native_cpp_full_draw",
                "RANKING_WINDOW_SCENE")
        seen.add(px)
        require(row["image_parity_static_full"] is True and
                row["static_rgba_fnv64"] == row["full_rgba_fnv64"] and
                row["area_ring"] < row["area_full_window"] and
                row["area_full_window"] == row["area_static"],
                "RANKING_WINDOW_PARITY")
        entry = {"pixels": px, "pairs": row["pairs"], "ranks": []}
        for mode, medkey in (("static", "median_static_ms"),
                             ("full", "median_full_window_ms"),
                             ("ring", "median_ring_ms")):
            measured = samples(row["raw_ms"], mode, row["pairs"])
            med = checked_median(measured, row[medkey])
            entry["ranks"].append({"mode": mode, "median_ms": med})
        checked_median([a/b for a, b in zip(row["raw_ms"]["static"],
                                            row["raw_ms"]["full"])],
                       row["paired_static_over_full_window"])
        entry["ranks"].sort(key=lambda r: (r["median_ms"], r["mode"]))
        board.append(entry)
    return sorted(board, key=lambda row: row["pixels"])


def assemble(wave, window, *, strict_current=False):
    return {"protocol": "are.cpu-wave-leaderboard.v1",
            "scope": "single-CPU receipt, within-scene rankings, no GPU parity",
            "wave_source": {"head_sha": wave["head_sha"],
                            "receipt_sha256": wave["sha256"],
                            "integrity": verify_wave_integrity(wave)},
            "window_source": {"source_commit": window["source_commit"],
                              "date": window.get("date"),
                              "ci_run": window.get("ci_run")},
            "wave": validate_wave(wave, strict_current=strict_current),
            "impact": validate_window(window)}


def render(board):
    lines = [
        "# SoftwareGPU: CPU-Ranglisten (beleggebunden)",
        "",
        "**Datenstand:** SpherePop-Receipt " + board["wave_source"]["head_sha"][:12] +
        "; Single-Origin " + board["window_source"]["source_commit"][:12] + ".",
        "",
        "**Historischer Integrity-Status:** "
        + board["wave_source"]["integrity"]
        + ". Unveränderter Git-Blob statt stillschweigend umgeschriebener"
        " historischer SHA-256. Neue Messungen verlangen einen"
        " kanonischen SHA-256 sowie einen Abgleich aller Quellhashes"
        " mit dem exakten Checkout.",
        "",
        "Nur reale CPU-Rohzeiten mit mindestens 15 Wiederholungen und verifizierter"
        " Bild-/Depth-Parität. Die Rangfolge gilt **nur innerhalb der jeweiligen"
        " Szene und Auflösung**. Keinerlei GPU-, Gameplay-FPS- oder"
        " Julia-Renderer-Parität ist daraus ableitbar.",
        "",
        "## CAG/SpherePop/Doppler: ganzer Draw mit Welle",
        "",
        "| Szene | Native C++ ms | Batch-first ms | Tiles ms | Rang 1 |",
        "|:--|--:|--:|--:|:--|",
    ]
    for case in board["wave"]:
        m = {r["backend"]: r["median_ms"] for r in case["ranks"]}
        name = f'{case["scene"]}, {case["pixels"]} px ({case["triangles"]} Dreiecke)'
        lines.append(f'| {name} | {m["native-cpp"]:.6f} |'
                     f' {m["batch-first"]:.6f} | {m["tiles"]:.6f} |'
                     f' {case["ranks"][0]["backend"]} |')
    lines += ["", "## Single-Origin Impact Waves: drei unterschiedliche Wirkungen",
              "", "| Auflösung | Ring ms | Sofort ms | Vollfenster ms | Rang 1 |",
              "|:--|--:|--:|--:|:--|"]
    for case in board["impact"]:
        m = {r["mode"]: r["median_ms"] for r in case["ranks"]}
        labels = {"static": "Sofort", "full": "Vollfenster", "ring": "Ring"}
        lines.append(f'| {case["pixels"]} px | {m["ring"]:.6f} |'
                     f' {m["static"]:.6f} | {m["full"]:.6f} |'
                     f' {labels[case["ranks"][0]["mode"]]} |')
    lines += ["",
              "**Semantik-Gate:** Ring verändert nur ein schmales Zeitfenster;"
              " daher nicht bildgleich mit Sofort/Vollfenster und **kein**"
              " gleicher-Output-Speedup. Nur Sofort vs. Vollfenster"
              " besitzen RGBA-Parität. Native C++ ist hier nicht mit"
              " Julia-Wellenmodellen als vollständiger Renderer vergleichbar.",
              "",
              "**Nachweise:** [SpherePop-Rohreceipt]"
              "(../evidence/spherepop-wave-ranked-cpu-20261020.json)"
              " · [Impact-Rohreceipt]"
              "(../evidence/single-origin-time-window-20261020.json)"
              " · [Julia/C++-Differentialtest]"
              "(https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/39635587649).",
              "",
              "Aktualisierte, **nicht automatisch nach main geschriebene**"
              " Live-Messungen stehen als Job-Zusammenfassung und"
              " herunterladbares Receipt im [CPU-Wave-Leaderboard-Workflow]"
              "(https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/workflows/cpu-wave-leaderboard.yml)."
              " Messungen von verschiedenen Runnern werden separat gehalten.",
              ""]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--wave", type=Path, default=WAVE)
    p.add_argument("--window", type=Path, default=WINDOW)
    p.add_argument("--markdown", type=Path)
    p.add_argument("--json", type=Path)
    p.add_argument("--check", type=Path, help="fail unless rendered text matches checked-in snapshot")
    p.add_argument("--strict-current", action="store_true",
                   help="require canonical receipt, current git HEAD and every source SHA-256")
    args = p.parse_args(argv)
    board = assemble(json.loads(args.wave.read_text(encoding="utf-8")),
                     json.loads(args.window.read_text(encoding="utf-8")),
                     strict_current=args.strict_current)
    md = render(board)
    if args.check:
        require(args.check.read_text(encoding="utf-8") == md,
                "RANKING_DOCUMENTATION_DRIFT")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(md, encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(board, indent=2, sort_keys=True,
                                        allow_nan=False) + "\n", encoding="utf-8")
    if not args.markdown and not args.json:
        print(md)


if __name__ == "__main__":
    main()
