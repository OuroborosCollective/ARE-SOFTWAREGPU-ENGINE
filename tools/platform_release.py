#!/usr/bin/env python3
"""Stage exact-main installer bytes; reuse and read back immutable releases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from release_gate import (DESKTOP_JOBS, ReleaseGateError, select_run, extract_desktop_artifact,
                          select_desktop_artifacts, validate_tag,
                          verify_desktop_jobs, verify_desktop_packages,
                          verify_platform_manifest, verify_sdist, verify_wheel)

REPOSITORY = "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"


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


def download_release_files(repo, tag, names, output):
    for name in names:
        command("gh", "release", "download", tag, "--repo", repo,
                "--pattern", name, "--dir", str(output))


def stage_from_main(repo, sha, tag, output):
    base = f"repos/{repo}"
    runs = api(f"{base}/actions/workflows/desktop-installers.yml/runs?head_sha={sha}&event=push&per_page=100")
    run_id = select_run(runs, sha, repo)
    jobs = api(f"{base}/actions/runs/{run_id}/jobs?per_page=100")
    verify_desktop_jobs(jobs, run_id)
    listing = api(f"{base}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = select_desktop_artifacts(listing, jobs, run_id, sha)
    with tempfile.TemporaryDirectory(prefix="are-release-") as temporary:
        staging = Path(temporary) / "combined"
        staging.mkdir()
        for artifact in artifacts:
            target = Path(temporary) / str(artifact["id"])
            archive = Path(temporary) / (str(artifact["id"]) + ".zip")
            with archive.open("xb") as download:
                subprocess.run(["gh", "api", f"{base}/actions/artifacts/{artifact['id']}/zip"],
                               stdout=download, check=True)
            platform, = [platform for platform in DESKTOP_JOBS if f"-{platform}-" in artifact["name"]]
            extract_desktop_artifact(archive, artifact["digest"], platform, tag, target)
            for source in target.iterdir():
                if source.is_symlink() or not source.is_file() or (staging / source.name).exists():
                    raise ReleaseGateError("Unexpected nested, duplicate or linked installer artifact")
                shutil.copy2(source, staging / source.name)
        files = verify_desktop_packages(staging, tag, sha)
        readback = api(f"{base}/actions/runs/{run_id}/artifacts?per_page=100")
        after = select_desktop_artifacts(readback, jobs, run_id, sha)
        identity = lambda entries: [(a["id"], a["name"], a["digest"]) for a in entries]
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
