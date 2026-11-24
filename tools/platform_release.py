#!/usr/bin/env python3
"""Stage exact-main installer bytes; reuse and read back immutable releases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

if __package__:
    from .release_gate import (DESKTOP_JOBS, MAX_DESKTOP_JSON_BYTES, ReleaseGateError, select_run, extract_desktop_artifact,
                              select_desktop_artifacts, validate_tag,
                              verify_desktop_jobs, verify_desktop_packages,
                              verify_platform_manifest, verify_sdist, verify_wheel)
else:
    from release_gate import (DESKTOP_JOBS, MAX_DESKTOP_JSON_BYTES, ReleaseGateError, select_run, extract_desktop_artifact,
                              select_desktop_artifacts, validate_tag,
                              verify_desktop_jobs, verify_desktop_packages,
                              verify_platform_manifest, verify_sdist, verify_wheel)

REPOSITORY = "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"
# Far above the current native installers, but finite before any remote transfer.
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_DOWNLOAD_TOTAL_BYTES = 1024 * 1024 * 1024


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def api(path, *, allow_missing=False):
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if result.returncode:
        if allow_missing and "(HTTP 404)" in result.stderr:
            return None
        raise ReleaseGateError("GitHub API request failed: " + path)
    return json.loads(result.stdout)


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def copy_immutable(source, destination):
    if destination.exists():
        if destination.is_symlink() or not destination.is_file() or digest(source) != digest(destination):
            raise ReleaseGateError("Refusing to overwrite differing release asset: " + destination.name)
        return
    shutil.copy2(source, destination)


def desktop_names(version):
    names = []
    for platform in DESKTOP_JOBS:
        suffix = platform + ("-setup.exe" if platform == "windows-x64" else ".run")
        names.extend((f"ARE-SoftwareGPU-{version}-{suffix}",
                      f"desktop-{platform}.json", f"desktop-{platform}-smoke.json"))
    return sorted(names)


def verify_tag_identity(repo, tag, sha):
    ref = api(f"repos/{repo}/git/ref/tags/{tag}")["object"]
    for _ in range(4):
        if ref.get("type") == "commit":
            if ref.get("sha") != sha:
                raise ReleaseGateError("Immutable release tag points to another source")
            return
        if ref.get("type") != "tag":
            break
        ref = api(f"repos/{repo}/git/tags/{ref['sha']}")["object"]
    raise ReleaseGateError("Cannot resolve immutable release tag")


def check_download_budget(sizes):
    sizes = list(sizes)
    if (any(type(size) is not int or not 0 < size <= MAX_DOWNLOAD_BYTES for size in sizes)
            or sum(sizes) > MAX_DOWNLOAD_TOTAL_BYTES):
        raise ReleaseGateError("Release download exceeds per-file or total byte budget")


def release_download_plan(release, tag, names):
    """Admit the complete metadata set before transferring even the first byte."""
    if (not isinstance(release, dict) or release.get("tag_name") != tag
            or release.get("draft") is not False or not isinstance(release.get("assets"), list)):
        raise ReleaseGateError("Release download identity or asset listing is invalid")
    names = list(names)
    if (not names or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]+", name)
                         for name in names) or len(names) != len(set(names))):
        raise ReleaseGateError("Release download names must be unique flat filenames")
    selected = []
    for name in names:
        matching = [asset for asset in release["assets"] if isinstance(asset, dict) and asset.get("name") == name]
        if (len(matching) != 1 or type(matching[0].get("id")) is not int or matching[0]["id"] < 1
                or matching[0].get("state") != "uploaded"):
            raise ReleaseGateError("Release download is missing, ambiguous or not uploaded: " + name)
        asset = matching[0]
        check_download_budget([asset.get("size")])
        if name.endswith((".json", ".txt", ".sha256")) and asset["size"] > MAX_DESKTOP_JSON_BYTES:
            raise ReleaseGateError("Release JSON/text exceeds metadata byte budget: " + name)
        selected.append(asset)
    check_download_budget(asset["size"] for asset in selected)
    return selected


def download_to_file(args, destination, expected_size):
    """Bound the actual transport, reject truncation and remove only our partial file."""
    check_download_budget([expected_size])
    destination = Path(destination)
    created = False
    try:
        with destination.open("xb") as output:
            created = True
            count = 0
            # No downloaded body is held in memory. One extra byte detects a lying size.
            with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
                try:
                    while True:
                        chunk = process.stdout.read(min(65536, expected_size + 1 - count))
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > expected_size:
                            raise ReleaseGateError("Downloaded bytes exceed the admitted byte budget")
                        output.write(chunk)
                    if process.wait(timeout=60) != 0:
                        raise ReleaseGateError("Release asset download process failed")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
            if count != expected_size:
                raise ReleaseGateError("Downloaded byte count differs from admitted metadata")
        if destination.stat().st_size != expected_size:
            raise ReleaseGateError("Downloaded file size differs from admitted metadata")
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def download_release_files(repo, tag, names, output):
    release = api(f"repos/{repo}/releases/tags/{tag}")
    selected = release_download_plan(release, tag, names)
    for asset in selected:
        # Address the admitted immutable asset ID, never a glob or mutable filename.
        download_to_file(["gh", "api", f"repos/{repo}/releases/assets/{asset['id']}",
                          "--header", "Accept: application/octet-stream"],
                         Path(output) / asset["name"], asset["size"])


def stage_from_main(repo, sha, tag, output):
    base = f"repos/{repo}"
    runs = api(f"{base}/actions/workflows/desktop-installers.yml/runs?head_sha={sha}&event=push&per_page=100")
    run_id = select_run(runs, sha, repo)
    jobs = api(f"{base}/actions/runs/{run_id}/jobs?per_page=100")
    verify_desktop_jobs(jobs, run_id)
    listing = api(f"{base}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = select_desktop_artifacts(listing, jobs, run_id, sha)
    check_download_budget(artifact["size_in_bytes"] for artifact in artifacts)
    with tempfile.TemporaryDirectory(prefix="are-release-") as temporary:
        staging = Path(temporary) / "combined"
        staging.mkdir()
        for artifact in artifacts:
            target = Path(temporary) / str(artifact["id"])
            archive = Path(temporary) / (str(artifact["id"]) + ".zip")
            download_to_file(["gh", "api", f"{base}/actions/artifacts/{artifact['id']}/zip"],
                             archive, artifact["size_in_bytes"])
            platform, = [platform for platform in DESKTOP_JOBS if f"-{platform}-" in artifact["name"]]
            extract_desktop_artifact(archive, artifact["digest"], platform, tag, target)
            for source in target.iterdir():
                if source.is_symlink() or not source.is_file() or (staging / source.name).exists():
                    raise ReleaseGateError("Unexpected nested, duplicate or linked installer artifact")
                shutil.copy2(source, staging / source.name)
        files = verify_desktop_packages(staging, tag, sha)
        readback = api(f"{base}/actions/runs/{run_id}/artifacts?per_page=100")
        after = select_desktop_artifacts(readback, jobs, run_id, sha)
        identity = lambda entries: [(a["id"], a["name"], a["digest"], a["size_in_bytes"]) for a in entries]
        if identity(artifacts) != identity(after):
            raise ReleaseGateError("Installer artifacts changed while being downloaded")
        for source in staging.iterdir():
            copy_immutable(source, output / source.name)
    manifest = {"schema": "are.platform-release.v1", "version": validate_tag(tag),
                "source_sha": sha, "desktop_run_id": run_id,
                "desktop_artifacts": [{key: a[key] for key in ("id", "name", "digest")}
                                      for a in artifacts], "assets": files,
                "verification": "Exact-main successful native install/render/uninstall jobs; original ZIP SHA256 matches GitHub artifact digest; extracted installer bytes match original build and smoke receipts."}
    (output / "platform-release.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def reuse_published_release(repo, sha, tag, output, release):
    version = validate_tag(tag)
    if release.get("tag_name") != tag or release.get("draft") is not False:
        raise ReleaseGateError("Existing release has unexpected identity or is still a draft")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleaseGateError("Existing release assets are missing")
    names = [a.get("name") for a in assets if isinstance(a, dict)]
    required = desktop_names(version) + ["platform-release.json",
                f"ouroboroscollective_softwaregpu-{version}-py3-none-any.whl",
                f"ouroboroscollective_softwaregpu-{version}.tar.gz"]
    if any(names.count(name) != 1 for name in required):
        raise ReleaseGateError("Existing release is incomplete; no assets will be overwritten")
    with tempfile.TemporaryDirectory(prefix="are-published-") as temporary:
        downloaded = Path(temporary)
        download_release_files(repo, tag, required, downloaded)
        desktop = downloaded / "desktop"
        desktop.mkdir()
        for name in desktop_names(version):
            shutil.copy2(downloaded / name, desktop / name)
        files = verify_desktop_packages(desktop, tag, sha)
        manifest = json.loads((downloaded / "platform-release.json").read_text(encoding="utf-8"))
        verify_platform_manifest(manifest, files, tag, sha)
        wheel = downloaded / f"ouroboroscollective_softwaregpu-{version}-py3-none-any.whl"
        source = downloaded / f"ouroboroscollective_softwaregpu-{version}.tar.gz"
        verify_wheel(wheel, tag)
        verify_sdist(source, tag)
        for name in required:
            copy_immutable(downloaded / name, output / name)


def readback(repo, sha, tag, directory):
    release = api(f"repos/{repo}/releases/tags/{tag}")
    with tempfile.TemporaryDirectory(prefix="are-readback-") as temporary:
        root = Path(temporary)
        reuse_published_release(repo, sha, tag, root, release)
        for remote in root.iterdir():
            local = directory / remote.name
            if not local.is_file() or digest(local) != digest(remote):
                raise ReleaseGateError("Released bytes differ from staged bytes: " + remote.name)
    print("PLATFORM_RELEASE_FULL_BYTE_READBACK_OK", tag, sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "readback"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    if args.repo != REPOSITORY:
        raise ReleaseGateError("Unexpected release repository")
    validate_tag(args.tag)
    if command("git", "rev-parse", "HEAD") != args.sha:
        raise ReleaseGateError("Release checkout differs from immutable tag SHA")
    verify_tag_identity(args.repo, args.tag, args.sha)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.command == "readback":
        readback(args.repo, args.sha, args.tag, args.output_dir)
        return
    existing = api(f"repos/{args.repo}/releases/tags/{args.tag}", allow_missing=True)
    if existing is not None:
        reuse_published_release(args.repo, args.sha, args.tag, args.output_dir, existing)
    else:
        environment = dict(os.environ)
        environment["ARE_BUILD_TAG"] = args.tag
        environment["SOURCE_DATE_EPOCH"] = command("git", "show", "-s", "--format=%ct", args.sha)
        subprocess.run(["python", "-m", "build", "--wheel", "--sdist", "--outdir", str(args.output_dir)],
                       env=environment, check=True)
        stage_from_main(args.repo, args.sha, args.tag, args.output_dir)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as destination:
            destination.write("exists=" + str(existing is not None).lower() + "\n")
    print("PLATFORM_RELEASE_READY", args.tag, args.sha,
          "existing verified bytes reused" if existing is not None else "exact-main artifacts staged")


if __name__ == "__main__":
    main()
