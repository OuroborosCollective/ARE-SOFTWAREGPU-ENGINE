#!/usr/bin/env python3
"""Verify an exact main SHA, green CPU CI and distributable wheel before release.

All inputs are GitHub API JSON or built artifacts, passed by the trusted CI job.
The script performs no network calls and never publishes anything.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import shutil
import stat
from zipfile import BadZipFile, ZipFile
import tarfile
from pathlib import PurePosixPath


class ReleaseGateError(ValueError):
    """Invalid release evidence; safe to report in CI."""


_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?\Z")
RELEASE_ANCHOR = "22c436385fad7bf79d074d9eaf2cce458a81810e"
DESKTOP_JOBS = {
    "windows-x64": "Windows x64 install / render / uninstall",
    "linux-x86_64": "Linux x86_64 install / render / uninstall",
}
MAX_DESKTOP_JSON_BYTES = 256 * 1024


def release_tag_for_lineage(lineage, sha):
    """Keep the existing immutable first-parent version, independent of reruns."""
    if (not isinstance(sha, str) or not _SHA.fullmatch(sha)
            or not isinstance(lineage, list) or not lineage or lineage[0] != sha
            or any(not isinstance(item, str) or not _SHA.fullmatch(item) for item in lineage)
            or len(set(lineage)) != len(lineage) or RELEASE_ANCHOR not in lineage):
        raise ReleaseGateError("Complete exact first-parent release history is required")
    patch = lineage.index(RELEASE_ANCHOR)
    if patch < 1:
        raise ReleaseGateError("Release must follow the v1.2.0 automation baseline")
    return f"v1.2.{patch}"


def parse_followup_event(event, event_name, repo):
    """A green branch-only snapshot is never a release authorization."""
    expected = "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"
    if (repo != expected or not isinstance(event, dict)
            or not isinstance(event.get("repository"), dict)
            or event.get("repository", {}).get("full_name") != expected):
        raise ReleaseGateError("Untrusted follow-up repository")
    if event_name == "workflow_run":
        run = event.get("workflow_run")
        if (not isinstance(run, dict) or run.get("name") != "Verified GoReleaser release"
                or run.get("path") != ".github/workflows/goreleaser.yml"
                or run.get("event") not in ("push", "workflow_dispatch")
                or run.get("status") != "completed" or run.get("conclusion") != "success"
                or not isinstance(run.get("head_repository"), dict)
                or run.get("head_repository", {}).get("full_name") != expected
                or type(run.get("id")) is not int or run["id"] < 1
                or not isinstance(run.get("head_sha"), str) or not _SHA.fullmatch(run["head_sha"])):
            raise ReleaseGateError("Untrusted or unsuccessful release workflow")
        result = {"tag": run.get("head_branch"), "sha": run["head_sha"], "run_id": run["id"]}
    elif event_name == "workflow_dispatch":
        if not isinstance(event.get("inputs"), dict):
            raise ReleaseGateError("Manual retry requires explicit tag input")
        result = {"tag": event.get("inputs", {}).get("tag"), "sha": None, "run_id": None}
    else:
        raise ReleaseGateError("Follow-up requires a release event or explicit retry")
    version = validate_tag(result["tag"])
    if "-" in version:
        raise ReleaseGateError("Follow-up requires a stable release tag")
    return result


def verify_followup_publisher_jobs(payload, run_id, sha):
    if (not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list)
            or type(payload.get("total_count")) is not int
            or len(payload["jobs"]) != payload["total_count"]):
        raise ReleaseGateError("Incomplete release publisher job listing")
    required = ("Validate configuration, wheel and snapshot without publishing",
                "Publish only exact-main fully green CPU CI tag",
                "Publish PyPI on verified SemVer tag (Trusted Publishing)")
    for name in required:
        matches = [job for job in payload["jobs"] if isinstance(job, dict) and job.get("name") == name]
        if (len(matches) != 1 or matches[0].get("run_id") != run_id
                or matches[0].get("head_sha") != sha or matches[0].get("status") != "completed"
                or matches[0].get("conclusion") != "success"):
            raise ReleaseGateError("Required release publisher job was not successful: " + name)


def android_version(tag):
    """Bounded order-preserving SemVer encoding; never depends on run number/time."""
    version = validate_tag(tag)
    if "-" in version:
        raise ReleaseGateError("Android releases require stable SemVer")
    major, minor, patch = map(int, version.split("."))
    code = major * 10_000_000 + minor * 100_000 + patch
    if major > 209 or minor > 99 or patch > 99999 or not 1 <= code <= 2_100_000_000:
        raise ReleaseGateError("Android version exceeds the documented noncolliding versionCode bounds")
    return {"version": version, "version_code": code}


def verify_android_badging(output, tag):
    expected = android_version(tag)
    package = re.search(r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']+)'", output, re.M)
    if (package is None or package.groups() != ("de.arelorian.softwaregpu", str(expected["version_code"]), expected["version"])
            or "application-debuggable" in output
            or re.findall(r"^sdkVersion:'([^']+)'", output, re.M) != ["26"]
            or re.findall(r"^targetSdkVersion:'([^']+)'", output, re.M) != ["35"]):
        raise ReleaseGateError("Android package/version/SDK/release-variant mismatch")
    return expected


def android_signer_fingerprint(output, scope):
    fingerprints = re.findall(r"^Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$", output, re.M)
    subjects = re.findall(r"^Signer #[0-9]+ certificate DN: (.+)$", output, re.M)
    if (scope not in ("release", "ci-test") or len(fingerprints) != 1 or len(subjects) != 1
            or "Verified using v2 scheme (APK Signature Scheme v2): true" not in output
            or "android debug" in subjects[0].lower()
            or (scope == "release" and "are ci test only" in subjects[0].lower())):
        raise ReleaseGateError("APK requires a single valid non-debug signing certificate")
    return fingerprints[0].lower()


def verify_android_source(path, tag, sha):
    expected = {"schema": "are.android-source.v1", **android_version(tag),
                "source_sha": sha, "runtime": "https-companion"}
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ReleaseGateError("Invalid Android source SHA")
    try:
        with ZipFile(path) as archive:
            names = [info for info in archive.infolist() if info.filename == "assets/are-release.json"]
            if len(names) != 1 or names[0].file_size > 4096:
                raise ReleaseGateError("APK source metadata is missing, duplicate or excessive")
            actual = json.loads(archive.read(names[0]))
    except (BadZipFile, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseGateError("Invalid Android source archive metadata") from error
    if actual != expected:
        raise ReleaseGateError("APK embedded source/version differs from release")
    return expected


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


def verify_desktop_jobs(payload, run_id):
    """Require native Windows and Linux install/render/uninstall, including retries."""
    verify_jobs(payload, run_id, minimum=len(DESKTOP_JOBS))
    selected = {}
    for platform, name in DESKTOP_JOBS.items():
        matches = [job for job in payload["jobs"] if job.get("name") == name]
        if len(matches) != 1:
            raise ReleaseGateError("Missing or ambiguous native installer job: " + platform)
        job = matches[0]
        if type(job.get("run_attempt")) is not int or job["run_attempt"] < 1:
            raise ReleaseGateError("Missing native installer attempt identity")
        selected[platform] = job
    return selected


def select_desktop_artifacts(payload, jobs, run_id, sha):
    selected_jobs = verify_desktop_jobs(jobs, run_id)
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ReleaseGateError("Invalid installer source SHA")
    if (not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list)
            or type(payload.get("total_count")) is not int
            or payload["total_count"] != len(payload["artifacts"])):
        raise ReleaseGateError("Incomplete installer artifact listing")
    selected = []
    for platform, job in selected_jobs.items():
        name = f"desktop-{sha}-{platform}-{job['run_attempt']}"
        matches = [a for a in payload["artifacts"] if isinstance(a, dict) and a.get("name") == name]
        if len(matches) != 1:
            raise ReleaseGateError("Missing or ambiguous installer artifact: " + platform)
        item = matches[0]
        run = item.get("workflow_run")
        digest = item.get("digest")
        if (type(item.get("id")) is not int or item["id"] < 1
                or item.get("expired") is not False
                or type(item.get("size_in_bytes")) is not int or item["size_in_bytes"] < 1
                or not isinstance(run, dict) or run.get("id") != run_id or run.get("head_sha") != sha
                or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
            raise ReleaseGateError("Installer artifact provenance is invalid")
        selected.append(item)
    return selected


def verify_desktop_packages(directory, tag, sha):
    """Admit only both real CI products and receipts bound to their exact bytes."""
    version = validate_tag(tag)
    if "-" in version or not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ReleaseGateError("Desktop releases require stable SemVer and exact SHA")
    directory = Path(directory)
    expected = set()
    for platform in DESKTOP_JOBS:
        suffix = platform + ("-setup.exe" if platform == "windows-x64" else ".run")
        expected.update((f"ARE-SoftwareGPU-{version}-{suffix}",
                         f"desktop-{platform}.json", f"desktop-{platform}-smoke.json"))
    try:
        paths = list(directory.iterdir())
        if ({p.name for p in paths} != expected
                or any(p.is_symlink() or not p.is_file() for p in paths)):
            raise ReleaseGateError("Installer release must contain exactly both products and four receipts")
        if any(path.suffix == ".json" and not 0 < path.stat().st_size <= MAX_DESKTOP_JSON_BYTES
               for path in paths):
            raise ReleaseGateError("Installer JSON exceeds metadata byte budget")
        hashes = {}
        for path in paths:
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            hashes[path.name] = {"name": path.name, "bytes": path.stat().st_size, "sha256": digest}
        for platform in DESKTOP_JOBS:
            build = json.loads((directory / f"desktop-{platform}.json").read_text(encoding="utf-8"))
            smoke = json.loads((directory / f"desktop-{platform}-smoke.json").read_text(encoding="utf-8"))
            for receipt, schema in ((build, "are.desktop-release.v1"), (smoke, "are.desktop-install-smoke.v1")):
                if (not isinstance(receipt, dict) or receipt.get("schema") != schema
                        or receipt.get("version") != version or receipt.get("source_sha") != sha
                        or receipt.get("platform") != platform):
                    raise ReleaseGateError("Installer receipt source, version or platform mismatch")
            suffix = platform + ("-setup.exe" if platform == "windows-x64" else ".run")
            name = f"ARE-SoftwareGPU-{version}-{suffix}"
            artifact = build.get("artifact")
            if (build.get("source_clean") is not True
                    or not isinstance(artifact, dict) or type(artifact.get("bytes")) is not int
                    or any(artifact.get(key) != value for key, value in hashes[name].items())):
                raise ReleaseGateError("Installer bytes differ from tested build receipt")
            checks = smoke.get("checks")
            if (smoke.get("passed") is not True or smoke.get("artifact_sha256") != hashes[name]["sha256"]
                    or not isinstance(checks, dict)
                    or any(checks.get(key) is not True for key in
                           ("install", "help", "info", "source", "version", "render", "uninstall"))):
                raise ReleaseGateError("Installer has no complete successful native smoke")
        return [hashes[name] for name in sorted(expected)]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseGateError("Installer products or receipts are unreadable") from exc


def verify_platform_manifest(payload, files, tag, sha):
    if (not isinstance(payload, dict) or payload.get("schema") != "are.platform-release.v1"
            or payload.get("source_sha") != sha or payload.get("version") != validate_tag(tag)
            or type(payload.get("desktop_run_id")) is not int or payload["desktop_run_id"] < 1
            or payload.get("assets") != files):
        raise ReleaseGateError("Published platform manifest differs from verified installer bytes")


def extract_desktop_artifact(path, expected_digest, platform, tag, destination):
    """Verify the original GitHub artifact ZIP, then extract three allowlisted files."""
    version = validate_tag(tag)
    if platform not in DESKTOP_JOBS:
        raise ReleaseGateError("Unknown installer platform")
    path, destination = Path(path), Path(destination)
    if path.stat().st_size > 1_000_000_000:
        raise ReleaseGateError("Installer archive exceeds download budget")
    with path.open("rb") as source:
        actual = "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected_digest:
        raise ReleaseGateError("Downloaded original artifact ZIP differs from GitHub SHA256")
    suffix = platform + ("-setup.exe" if platform == "windows-x64" else ".run")
    names = {f"ARE-SoftwareGPU-{version}-{suffix}", f"desktop-{platform}.json",
             f"desktop-{platform}-smoke.json"}
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if (len(entries) != 3 or {entry.filename for entry in entries} != names
                    or any(entry.is_dir() or entry.file_size > 512_000_000 or entry.flag_bits & 1
                           or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                           for entry in entries)
                    or sum(entry.file_size for entry in entries) > 1_000_000_000):
                raise ReleaseGateError("Unsafe or incomplete installer artifact ZIP")
            destination.mkdir(parents=True, exist_ok=False)
            for entry in entries:
                with archive.open(entry) as source, (destination / entry.filename).open("xb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
    except (OSError, BadZipFile) as exc:
        raise ReleaseGateError("Installer artifact ZIP is corrupt or unreadable") from exc


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
