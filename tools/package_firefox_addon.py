"""Create a deterministic, unsigned Firefox diagnostic add-on from explicit files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import zipfile


FILES = (
    "LICENSE.md", "NOTICE", "background.js", "diagnostics.html", "diagnostics.mjs",
    "icon.svg", "manifest.json", "readback.mjs", "style.css", "ui.mjs",
)
ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = tuple("clients/firefox-addon/" + name for name in FILES) + (
    "LICENSE.md", "NOTICE", "tools/package_firefox_addon.py", "tools/firefox_addon_smoke.py",
    "tools/firefox-addon-tests/readback.test.mjs", "tools/firefox-addon-tests/device-loss.test.mjs",
    "software_gpu/tests/test_firefox_addon_package.py", "software_gpu/tests/test_firefox_addon_smoke.py",
    "docs/firefox-addon.md", "docs/firefox-addon-privacy.md", "docs/firefox-addon-amo-listing.md",
    ".github/workflows/firefox-addon.yml",
)


def read_entries(source: Path, names: tuple) -> dict:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("ADDON_SOURCE_NOT_DIRECTORY")
    entries = {}
    for name in sorted(names):
        path = source / name
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("ADDON_INPUT_NOT_REGULAR: " + name)
        data = path.read_bytes()
        if not 0 < len(data) <= 256 * 1024:
            raise ValueError("ADDON_INPUT_SIZE: " + name)
        entries[name] = data
    return entries


def write_archive(entries: dict, destination: Path) -> dict:
    # Exclusive creation refuses replacement of an existing build or a symlink.
    with destination.open("xb") as handle:
        with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in entries.items():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data, compresslevel=9)
    return {"name": destination.name, "bytes": destination.stat().st_size,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}


def validate_version(version: str) -> str:
    if (not isinstance(version, str)
            or re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version) is None
            or any(int(part) > 65535 for part in version.split("."))):
        raise ValueError("ADDON_RELEASE_VERSION_INVALID")
    return version


def runtime_entries(source: Path, version: str | None = None) -> dict:
    source = Path(source)
    entries = read_entries(source, FILES)
    manifest = json.loads(entries["manifest.json"])
    if manifest.get("manifest_version") != 3:
        raise ValueError("ADDON_MANIFEST_VERSION")
    validate_version(manifest.get("version"))
    if version is not None:
        manifest["version"] = validate_version(version)
        entries["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    forbidden = ("permissions", "optional_permissions", "host_permissions", "optional_host_permissions",
                 "content_scripts", "externally_connectable", "web_accessible_resources")
    if any(manifest.get(key) for key in forbidden):
        raise ValueError("ADDON_PERMISSION_BOUNDARY")
    csp = manifest.get("content_security_policy", {}).get("extension_pages", "")
    directives = {}
    for part in csp.split(";"):
        tokens = part.split()
        if not tokens:
            continue
        name, sources = tokens[0].lower(), tokens[1:]
        if name in directives:
            raise ValueError("ADDON_DUPLICATE_CSP_DIRECTIVE")
        directives[name] = sources
    if directives.get("connect-src") != ["'none'"] or directives.get("script-src") != ["'self'"]:
        raise ValueError("ADDON_NETWORK_BOUNDARY")
    gecko = manifest.get("browser_specific_settings", {}).get("gecko", {})
    if gecko.get("data_collection_permissions") != {"required": ["none"]}:
        raise ValueError("ADDON_DATA_DECLARATION")
    if gecko.get("id") != "are-softwaregpu-diagnostics@arelogic.space":
        raise ValueError("ADDON_ID")
    return entries


def build_package(source: Path, destination: Path, version: str | None = None) -> dict:
    entries = runtime_entries(Path(source), version)
    manifest = json.loads(entries["manifest.json"])
    gecko = manifest["browser_specific_settings"]["gecko"]
    package = write_archive(entries, destination)
    return {
        "schema": "are.firefox-addon-package.v1", "signed": False,
        "name": manifest["name"], "version": manifest["version"], "extension_id": gecko["id"],
        "package": package,
        "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in entries.items()],
        "scope": "Packaging identity only; this does not assert browser execution, AMO approval or signing.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", help="Stage this release version; keep tracked source untouched")
    parser.add_argument("--source-sha", help="Require this exact clean Git checkout and bind it in the receipt")
    args = parser.parse_args()
    if args.version is not None:
        validate_version(args.version)
    if args.source_sha:
        if (re.fullmatch(r"[0-9a-f]{40}", args.source_sha) is None
                or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != args.source_sha):
            raise ValueError("ADDON_SOURCE_REVISION_MISMATCH")
        if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True).strip():
            raise ValueError("ADDON_RELEASE_REQUIRES_CLEAN_SOURCE")
    entries = runtime_entries(ROOT / "clients/firefox-addon", args.version)
    version = json.loads(entries["manifest.json"])["version"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    label = "-unsigned" if args.version else ""
    output = args.output_dir / f"are-softwaregpu-diagnostics-{version}{label}.xpi"
    receipt = build_package(ROOT / "clients/firefox-addon", output, args.version)
    receipt.update({"source_sha": args.source_sha, "source_clean": args.source_sha is not None})
    source_entries = read_entries(ROOT, SOURCE_FILES)
    source_entries["clients/firefox-addon/manifest.json"] = entries["manifest.json"]
    receipt["sourceArchive"] = write_archive(source_entries, args.output_dir / f"are-softwaregpu-diagnostics-{version}-source.zip")
    receipt["sourceFiles"] = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                              for name, data in source_entries.items()]
    with (args.output_dir / "package-receipt.json").open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
