"""Create a deterministic, unsigned Firefox diagnostic add-on from explicit files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile


FILES = (
    "LICENSE.md", "NOTICE", "background.js", "diagnostics.html", "diagnostics.mjs",
    "icon.svg", "manifest.json", "readback.mjs", "style.css", "ui.mjs",
)
ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = tuple("clients/firefox-addon/" + name for name in FILES) + (
    "LICENSE.md", "NOTICE", "tools/package_firefox_addon.py", "tools/firefox_addon_smoke.py", "tools/firefox_addon_runtime.py",
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


def build_package(source: Path, destination: Path) -> dict:
    source, destination = Path(source), Path(destination)
    entries = read_entries(source, FILES)
    manifest = json.loads(entries["manifest.json"])
    if manifest.get("manifest_version") != 3 or manifest.get("version") != "0.1.0":
        raise ValueError("ADDON_MANIFEST_VERSION")
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
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "are-softwaregpu-diagnostics-0.1.0.xpi"
    receipt = build_package(ROOT / "clients/firefox-addon", output)
    source_entries = read_entries(ROOT, SOURCE_FILES)
    receipt["sourceArchive"] = write_archive(source_entries, args.output_dir / "are-softwaregpu-diagnostics-0.1.0-source.zip")
    receipt["sourceFiles"] = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                              for name, data in source_entries.items()]
    with (args.output_dir / "package-receipt.json").open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
