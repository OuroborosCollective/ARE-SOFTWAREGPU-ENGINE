#!/usr/bin/env python3
"""Verify an exact main SHA, green CPU CI and distributable wheel before release.

All inputs are GitHub API JSON or built artifacts, passed by the trusted CI job.
The script performs no network calls and never publishes anything.
"""

import argparse
import json
from pathlib import Path
import re
import sys
from zipfile import BadZipFile, ZipFile
import tarfile
from pathlib import PurePosixPath


class ReleaseGateError(ValueError):
    """Invalid release evidence; safe to report in CI."""


_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?\Z")


def validate_tag(tag):
    match = _TAG.fullmatch(tag) if isinstance(tag, str) else None
    if match is None:
        raise ReleaseGateError("Release tag must be strict vMAJOR.MINOR.PATCH[-rc.N] SemVer")
    return tag[1:]


def wheel_version(tag):
    version = validate_tag(tag)
    return re.sub(r"-(alpha|beta|rc)\.(\d+)$",
                  lambda match: {'alpha': 'a', 'beta': 'b', 'rc': 'rc'}[match[1]] + match[2], version)


def select_run(payload, sha, repo):
    """Select newest exact-main push; never fall back to an older green run."""
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ReleaseGateError("A full lowercase 40-character commit SHA is required")
    if repo != "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE":
        raise ReleaseGateError("Unexpected release repository")
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise ReleaseGateError("Missing CPU CI workflow run list")
    matches = []
    for item in payload["workflow_runs"]:
        if not isinstance(item, dict):
            continue
        head = item.get("head_repository")
        if (item.get("head_sha") == sha and item.get("head_branch") == "main"
                and item.get("event") == "push" and isinstance(head, dict)
                and head.get("full_name") == repo and type(item.get("id")) is int):
            matches.append(item)
    if not matches:
        raise ReleaseGateError("No exact-main push CI evidence for tagged commit")
    selected = max(matches, key=lambda item: item["id"])
    if selected.get("status") != "completed" or selected.get("conclusion") != "success":
        raise ReleaseGateError("Newest exact-main CPU CI run is not successful")
    return selected["id"]


def verify_jobs(payload, run_id, minimum=8):
    """Read back all jobs; incomplete pagination, failures and skips block publishing."""
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ReleaseGateError("Missing CPU CI jobs data")
    entries = payload["jobs"]
    count = payload.get("total_count")
    if (type(minimum) is not int or minimum < 1
            or type(count) is not int or count < minimum or len(entries) != count):
        raise ReleaseGateError("Missing one or more required CI jobs")
    if any(not isinstance(item, dict) or item.get("run_id") != run_id
           or item.get("status") != "completed" or item.get("conclusion") != "success"
           for item in entries):
        raise ReleaseGateError("CPU CI job incomplete, skipped, failed or wrong run")
    return count


def verify_wheel(path, tag):
    """Check artifact version and embedded noncommercial redistribution notices."""
    version = wheel_version(tag)
    path = Path(path)
    if not path.name.startswith("ouroboroscollective_softwaregpu-" + version + "-") or path.suffix != ".whl":
        raise ReleaseGateError("Wheel filename does not match release tag version")
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ReleaseGateError("Wheel must contain exactly one METADATA")
            manifest = archive.read(metadata[0]).decode("utf-8")
            if f"Version: {version}" not in manifest.splitlines():
                raise ReleaseGateError("Wheel metadata version does not match tag")
            if "Name: ouroboroscollective-softwaregpu" not in manifest.splitlines():
                raise ReleaseGateError("Wheel distribution name does not match")
            if "main.py" not in names or "software_gpu/__init__.py" not in names:
                raise ReleaseGateError("Wheel missing real Python API or CLI")
            license_files = [name for name in names if ".dist-info/" in name]
            if not any(name.endswith("/LICENSE.md") for name in license_files):
                raise ReleaseGateError("Wheel missing PolyForm LICENSE.md")
            if not any(name.endswith("/NOTICE") for name in license_files):
                raise ReleaseGateError("Wheel missing Required Notice")
    except (OSError, BadZipFile, UnicodeError):
        raise ReleaseGateError("Wheel is missing, corrupt or unreadable") from None


def verify_sdist(path, tag):
    """Accept only the expected Python source distribution, not the GoReleaser archive."""
    version = wheel_version(tag)
    path = Path(path)
    basename = f"ouroboroscollective_softwaregpu-{version}"
    if path.name != basename + ".tar.gz":
        raise ReleaseGateError("Source distribution filename/version mismatch")
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if not members or len(members) > 20000:
                raise ReleaseGateError("Source distribution member budget invalid")
            included = {}
            for member in members:
                parts = PurePosixPath(member.name).parts
                if (not parts or parts[0] != basename
                        or any(p in ("", ".", "..") for p in parts)
                        or member.issym() or member.islnk()
                        or not (member.isdir() or member.isfile())):
                    raise ReleaseGateError("Unsafe source distribution member")
                if member.isfile():
                    if member.size > 30_000_000 or member.name in included:
                        raise ReleaseGateError("Source distribution file invalid")
                    included[member.name] = member
            for rel in ("setup.py", "main.py", "software_gpu/__init__.py",
                        "LICENSE.md", "NOTICE", "PKG-INFO", "docs/PYPI_PACKAGE.md"):
                if f"{basename}/{rel}" not in included:
                    raise ReleaseGateError("Source distribution missing " + rel)
            metadata = archive.extractfile(included[f"{basename}/PKG-INFO"])
            if metadata is None:
                raise ReleaseGateError("Source distribution missing metadata")
            text = metadata.read(1_000_000).decode("utf-8")
            if (f"Version: {version}" not in text.splitlines()
                    or "Name: ouroboroscollective-softwaregpu" not in text.splitlines()):
                raise ReleaseGateError("Source distribution metadata mismatch")
            notice = archive.extractfile(included[f"{basename}/NOTICE"])
            if notice is None or b"Required Notice:" not in notice.read(100_000):
                raise ReleaseGateError("Source distribution missing Required Notice")
    except (OSError, tarfile.TarError, UnicodeError, EOFError):
        raise ReleaseGateError("Source distribution corrupt or unreadable") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--jobs", type=Path)
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args(argv)
    try:
        validate_tag(args.tag)
        selected = select_run(json.loads(args.runs.read_text(encoding="utf-8")), args.sha, args.repo)
        if args.jobs is None:
            print(selected)
            return 0
        count = verify_jobs(json.loads(args.jobs.read_text(encoding="utf-8")), selected)
        if args.wheel is None:
            raise ReleaseGateError("Verified wheel path is required before publishing")
        verify_wheel(args.wheel, args.tag)
        print(f"RELEASE_GATE_OK sha={args.sha} run={selected} jobs={count} wheel={args.wheel.name}")
        return 0
    except (ReleaseGateError, OSError, UnicodeError, ValueError) as exc:
        print(f"RELEASE_GATE_BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())