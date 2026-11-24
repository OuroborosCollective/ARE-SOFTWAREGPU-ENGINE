"""Assign a stable patch number per first-parent main integration, including retries."""
import json
import os
import subprocess
import time

from release_gate import select_run, verify_jobs, verify_desktop_jobs, release_tag_for_lineage


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def api(path):
    return json.loads(output("gh", "api", path))


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["GITHUB_SHA"]
    if output("git", "rev-parse", "HEAD") != sha:
        raise ValueError("Release checkout differs from event SHA")
    lineage = output("git", "rev-list", "--first-parent", sha).splitlines()
    tag = release_tag_for_lineage(lineage, sha)
    base = f"repos/{repo}"
    pending = {"cpu-regressions.yml": 9, "public-package-install.yml": 4,
               "desktop-installers.yml": 2}
    for _ in range(135):
        for name, minimum in list(pending.items()):
            runs = api(f"{base}/actions/workflows/{name}/runs?head_sha={sha}&event=push&per_page=100")
            exact = [r for r in runs["workflow_runs"] if r["head_branch"] == "main" and r["head_sha"] == sha]
            if exact and max(exact, key=lambda r: r["id"])["status"] == "completed":
                run = select_run(runs, sha, repo)
                jobs = api(f"{base}/actions/runs/{run}/jobs?per_page=100")
                verify_jobs(jobs, run, minimum=minimum)
                if name == "desktop-installers.yml":
                    verify_desktop_jobs(jobs, run)
                print("verified", name, run, flush=True)
                del pending[name]
        if not pending:
            break
        time.sleep(20)
    if pending:
        raise TimeoutError(f"Waiting for exact-main CI: {pending}")
    refs = api(f"{base}/git/matching-refs/tags/{tag}")
    if not any(r["ref"] == f"refs/tags/{tag}" for r in refs):
        output("gh", "api", "-X", "POST", f"{base}/git/refs", "-f", f"ref=refs/tags/{tag}", "-f", f"sha={sha}")
    if api(f"{base}/git/ref/tags/{tag}")["object"]["sha"] != sha:
        raise ValueError("Existing tag points to another commit")
    runs = api(f"{base}/actions/workflows/goreleaser.yml/runs?head_sha={sha}&event=workflow_dispatch")
    if any(r["head_branch"] == tag and (r["status"] != "completed" or r["conclusion"] == "success")
           for r in runs["workflow_runs"]):
        return
    output("gh", "workflow", "run", "goreleaser.yml", "--repo", repo, "--ref", tag)
    print("Dispatched verified release", tag, sha)


if __name__ == "__main__":
    main()
