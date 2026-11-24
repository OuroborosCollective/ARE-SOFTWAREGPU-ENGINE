#!/usr/bin/env python3
"""Trusted-main admission and immutable asset uploads for release companions."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile

if __package__:
    from . import platform_release as platform
    from .release_gate import (ReleaseGateError, parse_followup_event,
                               release_tag_for_lineage, verify_followup_publisher_jobs)
else:
    import platform_release as platform
    from release_gate import (ReleaseGateError, parse_followup_event,
                              release_tag_for_lineage, verify_followup_publisher_jobs)

REPOSITORY = platform.REPOSITORY


def tag_commit(repo, tag):
    ref = platform.api(f"repos/{repo}/git/ref/tags/{tag}")["object"]
    for _ in range(4):
        if ref.get("type") == "commit" and re.fullmatch(r"[0-9a-f]{40}", ref.get("sha", "")):
            return ref["sha"]
        if ref.get("type") != "tag":
            break
        ref = platform.api(f"repos/{repo}/git/tags/{ref['sha']}")["object"]
    raise ReleaseGateError("Cannot resolve release tag")


def verify_desktop_release(repo, tag, sha, output_dir):
    if repo != REPOSITORY:
        raise ReleaseGateError("Unexpected release repository")
    platform.verify_tag_identity(repo, tag, sha)
    platform.command("git", "merge-base", "--is-ancestor", sha, "refs/remotes/origin/main")
    lineage = platform.command("git", "rev-list", "--first-parent", sha).splitlines()
    if release_tag_for_lineage(lineage, sha) != tag:
        raise ReleaseGateError("Release tag differs from source's first-parent version")
    release = platform.api(f"repos/{repo}/releases/tags/{tag}")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    platform.reuse_published_release(repo, sha, tag, output, release)
    return {"tag": tag, "version": tag[1:], "sha": sha,
            "release_id": release["id"],
            "desktop_manifest_sha256": platform.digest(output / "platform-release.json")}


def resolve_context(event, repo=REPOSITORY, event_name=None):
    candidate = parse_followup_event(event, event_name or os.environ.get("GITHUB_EVENT_NAME"), repo)
    tag = candidate["tag"]
    sha = tag_commit(repo, tag)
    if candidate["sha"] is not None and candidate["sha"] != sha:
        raise ReleaseGateError("Release event SHA differs from immutable tag")
    run_id = candidate["run_id"]
    if run_id is None:
        payload = platform.api(f"repos/{repo}/actions/workflows/goreleaser.yml/runs?head_sha={sha}&per_page=100")
        candidates = [run for run in payload["workflow_runs"]
                      if run.get("head_sha") == sha and run.get("head_branch") == tag
                      and run.get("event") in ("push", "workflow_dispatch")
                      and run.get("head_repository", {}).get("full_name") == repo]
        if not candidates:
            raise ReleaseGateError("No release publisher run exists for retry")
        run = max(candidates, key=lambda item: item["id"])
        parse_followup_event({"repository": {"full_name": repo}, "workflow_run": run}, "workflow_run", repo)
        run_id = run["id"]
    jobs = platform.api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")
    verify_followup_publisher_jobs(jobs, run_id, sha)
    with tempfile.TemporaryDirectory(prefix="are-desktop-admission-") as directory:
        result = verify_desktop_release(repo, tag, sha, directory)
    result["publisher_run_id"] = run_id
    return result


def publish_assets(repo, tag, sha, files):
    """No clobber: existing names must already contain identical full bytes."""
    if repo != REPOSITORY:
        raise ReleaseGateError("Unexpected release repository")
    platform.verify_tag_identity(repo, tag, sha)
    result = []
    paths = [Path(path) for path in files]
    if len({p.name for p in paths}) != len(paths):
        raise ReleaseGateError("Duplicate release asset names")
    for path in paths:
        if (path.is_symlink() or not path.is_file()
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]+", path.name)):
            raise ReleaseGateError("Invalid release asset")
        expected = platform.digest(path)
        release = platform.api(f"repos/{repo}/releases/tags/{tag}")
        if release.get("draft") is not False:
            raise ReleaseGateError("Desktop release is not published")
        matching = [a for a in release["assets"] if a.get("name") == path.name]
        if len(matching) > 1:
            raise ReleaseGateError("Ambiguous published asset")
        if not matching:
            platform.command("gh", "release", "upload", tag, str(path), "--repo", repo)
        with tempfile.TemporaryDirectory(prefix="are-asset-readback-") as directory:
            platform.download_release_files(repo, tag, [path.name], Path(directory))
            downloaded = Path(directory) / path.name
            if downloaded.stat().st_size != path.stat().st_size or platform.digest(downloaded) != expected:
                raise ReleaseGateError("Published asset collision or readback mismatch: " + path.name)
        result.append({"name": path.name, "bytes": path.stat().st_size, "sha256": expected})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--event", type=Path, required=True)
    resolve.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME"))
    resolve.add_argument("--repo", default=REPOSITORY)
    resolve.add_argument("--github-output", type=Path, required=True)
    check = sub.add_parser("desktop-gate")
    check.add_argument("--tag", required=True)
    check.add_argument("--sha", required=True)
    check.add_argument("--repo", default=REPOSITORY)
    check.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "resolve":
        result = resolve_context(json.loads(args.event.read_text(encoding="utf-8")), args.repo, args.event_name)
        # No privileged job receives an unverified source or tag.
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write("".join(f"{name}={result[name]}\n" for name in ("tag", "version", "sha")))
    else:
        result = verify_desktop_release(args.repo, args.tag, args.sha, args.output_dir)
    print(json.dumps({"status": "VERIFIED_DESKTOP_RELEASE", **result}, sort_keys=True))


if __name__ == "__main__":
    main()
