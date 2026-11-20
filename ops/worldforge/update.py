#!/usr/bin/python3
"""Activate one public wheel only after GitHub and PyPI agree on its exact bytes."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PREFIX = Path("/opt/are-media")
PROJECT = "ouroboroscollective-softwaregpu"
REPO = "https://api.github.com/repos/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"


def fetch(url, limit=2_000_000):
    request = Request(url, headers={"User-Agent": "ARE-WorldForge-Release-Updater"})
    with urlopen(request, timeout=30) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Download exceeds limit")
    return content


def semver(value):
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Expected a stable package release")
    return tuple(int(i) for i in value.split("."))


def update():
    current = PREFIX / "learning-current"
    releases = PREFIX / "learning-releases"
    registry = json.loads(fetch(f"https://pypi.org/pypi/{PROJECT}/json"))
    version = registry["info"]["version"]
    if registry["info"]["name"] != PROJECT or semver(version) < (1, 2, 1):
        raise ValueError("World Forge requires a published version >= 1.2.1")
    metadata = current / "release.json"
    if metadata.is_file() and semver(json.loads(metadata.read_text())["version"]) > semver(version):
        raise ValueError("Refusing a downgrade")
    wheel_name = PROJECT.replace("-", "_") + "-" + version + "-py3-none-any.whl"
    entry, = [e for e in registry["urls"] if e["filename"] == wheel_name and not e["yanked"]]
    digest = entry["digests"]["sha256"]
    if not re.fullmatch("[a-f0-9]{64}", digest):
        raise ValueError("Invalid PyPI SHA-256")
    if metadata.is_file() and json.loads(metadata.read_text()).get("wheelSha256") == digest:
        return
    tag = "v" + version
    release = json.loads(fetch(f"{REPO}/releases/tags/{tag}"))
    github_wheel, = [a for a in release["assets"] if a["name"] == wheel_name]
    if (release["tag_name"] != tag or release["draft"] or release["prerelease"]
            or github_wheel.get("digest") != "sha256:" + digest):
        raise ValueError("GitHub release and PyPI wheel differ")
    commit = json.loads(fetch(f"{REPO}/git/ref/tags/{tag}"))["object"]
    if commit["type"] != "commit" or not re.fullmatch("[a-f0-9]{40}", commit["sha"]):
        raise ValueError("Expected the workflow's exact commit tag")
    url = urlsplit(entry["url"])
    if (url.scheme, url.netloc) != ("https", "files.pythonhosted.org"):
        raise ValueError("Unexpected PyPI download origin")
    data = fetch(entry["url"], 32 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Downloaded wheel SHA-256 mismatch")
    releases.mkdir(mode=0o755, exist_ok=True, parents=True)
    # Venv entrypoints embed absolute paths. Build at the permanent path and switch only the symlink.
    target = Path(tempfile.mkdtemp(prefix=f"pypi-{version}-", dir=releases))
    link = releases / ".activate"
    try:
        target.chmod(0o755)
        wheel = target / wheel_name
        wheel.write_bytes(data)
        env = target / "venv"
        subprocess.run(["/usr/local/bin/uv", "venv", "--python", "/usr/bin/python3.11", str(env)], check=True)
        subprocess.run(["/usr/local/bin/uv", "pip", "install", "--python", str(env / "bin/python"),
                        "--default-index", "https://pypi.org/simple", "--only-binary", ":all:",
                        str(wheel), "numpy==1.26.4", "Pillow==12.3.0"], check=True)
        (target / "studio-python").symlink_to(env / "bin/python")
        for cli in ("are-learning", "software-gpu", "are-render-video", "are-worldforge"):
            subprocess.run(["runuser", "-u", "unityarpg", "--", str(env / "bin" / cli), "--help"],
                           cwd="/tmp", stdout=subprocess.DEVNULL, check=True)
        actual = subprocess.check_output(["runuser", "-u", "unityarpg", "--", str(env / "bin/are-worldforge"),
                                          "--version"], cwd="/tmp", text=True).strip()
        if actual != version:
            raise ValueError(f"Installed version differs: {actual!r}")
        record = {"version": version, "tag": tag, "gitSha": commit["sha"], "wheelSha256": digest}
        (target / "release.json").write_text(json.dumps(record) + "\n")
        link.unlink(missing_ok=True)
        link.symlink_to(target)
        os.replace(link, current)
        print(json.dumps(record), flush=True)
    finally:
        if current.resolve() != target:
            shutil.rmtree(target)


if __name__ == "__main__":
    with (PREFIX / ".worldforge-release.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        update()
