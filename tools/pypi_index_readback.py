#!/usr/bin/env python3
"""Read back real PyPI file digests after a trusted release (never publishes)."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT = "ouroboroscollective-softwaregpu"


def validate_registry_payload(payload: dict, artifacts, version: str) -> None:
    """Fail closed if PyPI does not serve precisely the uploaded wheel+sdist."""
    if not isinstance(payload, dict) or not isinstance(payload.get("info"), dict):
        raise ValueError("PYPI_METADATA_MISSING")
    info = payload["info"]
    if info.get("name", "").lower().replace("_", "-").replace(".", "-") != PROJECT:
        raise ValueError("PYPI_PROJECT_MISMATCH")
    if info.get("version") != version:
        raise ValueError("PYPI_VERSION_MISMATCH")
    files = [Path(path) for path in artifacts]
    if (len(files) != 2 or len(set(path.name for path in files)) != 2
            or sum(path.name.endswith(".whl") for path in files) != 1
            or sum(path.name.endswith(".tar.gz") for path in files) != 1):
        raise ValueError("LOCAL_ARTIFACT_SET_INVALID")
    expected = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    remote = payload.get("urls")
    if not isinstance(remote, list) or len(remote) != len(files):
        raise ValueError("PYPI_ARTIFACT_SET_MISMATCH")
    filenames = []
    for item in remote:
        if not isinstance(item, dict) or item.get("yanked") is True:
            raise ValueError("PYPI_INVALID_ENTRY")
        name = item.get("filename")
        if name not in expected or name in filenames:
            raise ValueError("PYPI_UNEXPECTED_FILENAME")
        filenames.append(name)
        digest = item.get("digests", {}).get("sha256")
        if not isinstance(digest, str) or not hmac.compare_digest(digest, expected[name]):
            raise ValueError("PYPI_DIGEST_MISMATCH")
    if set(filenames) != set(expected):
        raise ValueError("PYPI_MISSING_ARTIFACT")


def collect_local_distributions(directory: Path) -> list[Path]:
    """Select only wheel/sdist; accept publisher-created attestations, nothing else."""
    if not directory.is_dir():
        raise ValueError("PYPI_LOCAL_DIST_INVALID")
    entries = sorted(directory.iterdir())
    artifacts = [p for p in entries if p.is_file() and (
        p.name.endswith(".whl") or p.name.endswith(".tar.gz"))]
    if (len(artifacts) != 2 or
            sum(p.name.endswith(".whl") for p in artifacts) != 1 or
            sum(p.name.endswith(".tar.gz") for p in artifacts) != 1):
        raise ValueError("PYPI_LOCAL_DIST_INVALID")
    allowed = {p.name for p in artifacts}
    allowed.update(p.name + ".publish.attestation" for p in artifacts)
    if any(not p.is_file() or p.name not in allowed for p in entries):
        raise ValueError("PYPI_UNEXPECTED_LOCAL_FILE")
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args()
    from release_gate import wheel_version
    version = wheel_version("v" + args.version)
    if version != args.version:
        raise SystemExit("PYPI_VERSION_NOT_PEP440")
    try:
        files = collect_local_distributions(args.dist)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    url = f"https://pypi.org/pypi/{PROJECT}/{version}/json"
    error = None
    for attempt in range(6):
        try:
            with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=20) as response:
                if response.status != 200:
                    raise ValueError("PYPI_HTTP_STATUS_INVALID")
                payload = json.loads(response.read(2_000_000))
            validate_registry_payload(payload, files, version)
            print(json.dumps({"status": "PYPI_REGISTRY_SHA256_READBACK_OK",
                              "name": PROJECT, "version": version,
                              "artifacts": [path.name for path in files]}, sort_keys=True))
            return 0
        except (HTTPError, URLError, TimeoutError, ValueError, OSError,
                json.JSONDecodeError) as exc:
            error = type(exc).__name__
            if attempt < 5:
                time.sleep(8)
    print("PYPI_READBACK_BLOCKED: " + str(error), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
