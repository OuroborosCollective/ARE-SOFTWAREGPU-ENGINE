#!/usr/bin/env python3
"""Verify and publish version-bound Firefox packages; submit separately to AMO."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if __package__:
    from . import package_firefox_addon as package
    from . import platform_release as platform
    from .release_followup import REPOSITORY, publish_assets, verify_desktop_release
else:
    import package_firefox_addon as package
    import platform_release as platform
    from release_followup import REPOSITORY, publish_assets, verify_desktop_release

ROOT = Path(__file__).resolve().parents[1]
ADDON_ID = "are-softwaregpu-diagnostics@arelogic.space"
AMO_API = "https://addons.mozilla.org/api/v5/"
MAX_ARCHIVE = 8 * 1024 * 1024


def archive_entries(path):
    """Read bounded regular entries, never extract untrusted archive paths."""
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_ARCHIVE:
        raise ValueError("FIREFOX_ARCHIVE_INVALID")
    result = {}
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > 100:
            raise ValueError("FIREFOX_ARCHIVE_ENTRY_LIMIT")
        for info in archive.infolist():
            name = info.filename
            if (name.startswith("/") or "\\" in name or ":" in name
                    or any(part in ("", ".", "..") for part in name.split("/"))
                    or name in result or info.is_dir()
                    or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
                    or not 0 < info.file_size <= 1024 * 1024):
                raise ValueError("FIREFOX_ARCHIVE_UNSAFE_ENTRY")
            result[name] = archive.read(info)
            if sum(map(len, result.values())) > MAX_ARCHIVE:
                raise ValueError("FIREFOX_ARCHIVE_SIZE_LIMIT")
    return result


def file_records(entries):
    return [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in entries.items()]


def unsigned_names(version):
    package.validate_version(version)
    return [f"are-softwaregpu-diagnostics-{version}-unsigned.xpi",
            f"are-softwaregpu-diagnostics-{version}-source.zip",
            f"firefox-addon-{version}-package.json",
            f"firefox-addon-{version}-SHA256SUMS.txt"]


def verify_unsigned_package(directory, version, sha):
    package.validate_version(version)
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("FIREFOX_SOURCE_SHA_INVALID")
    directory = Path(directory)
    receipt_path = directory / "package-receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.stat().st_size > 256 * 1024:
        raise ValueError("FIREFOX_RECEIPT_INVALID")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("schema") != "are.firefox-addon-package.v1" or receipt.get("signed") is not False
            or receipt.get("source_clean") is not True or receipt.get("version") != version
            or receipt.get("source_sha") != sha or receipt.get("extension_id") != ADDON_ID):
        raise ValueError("FIREFOX_PACKAGE_IDENTITY_MISMATCH")
    runtime = package.runtime_entries(ROOT / "clients/firefox-addon", version)
    sources = package.read_entries(ROOT, package.SOURCE_FILES)
    sources["clients/firefox-addon/manifest.json"] = runtime["manifest.json"]
    for key, name, expected, inventory in (
        ("package", unsigned_names(version)[0], runtime, "files"),
        ("sourceArchive", unsigned_names(version)[1], sources, "sourceFiles"),
    ):
        record = receipt.get(key, {})
        path = directory / name
        entries = archive_entries(path)
        if (record != {"name": name, "bytes": path.stat().st_size, "sha256": platform.digest(path)}
                or entries != expected or receipt.get(inventory) != file_records(expected)):
            raise ValueError("FIREFOX_PACKAGE_BYTES_MISMATCH: " + key)
    return receipt


def checksum_text(paths):
    return "".join(f"{platform.digest(path)}  {path.name}\n" for path in paths)


def write_once(path, data):
    with path.open("xb") as output:
        output.write(data)


def stage_runtime(directory, version, sha, stage):
    receipt = verify_unsigned_package(directory, version, sha)
    stage.mkdir(parents=True, exist_ok=False)
    for name, data in archive_entries(directory / receipt["package"]["name"]).items():
        # Admission has already constrained these to the ten flat runtime names.
        write_once(stage / name, data)
    return receipt


def prepare_unsigned(directory, version, sha, stage):
    receipt = stage_runtime(directory, version, sha, stage)
    names = unsigned_names(version)
    write_once(directory / names[2], (directory / "package-receipt.json").read_bytes())
    write_once(directory / names[3], checksum_text([directory / name for name in names[:3]]).encode())
    return receipt


def verify_public_files(directory, version, sha):
    receipt = verify_unsigned_package(directory, version, sha)
    names = unsigned_names(version)
    if (directory / names[2]).read_bytes() != (directory / "package-receipt.json").read_bytes():
        raise ValueError("FIREFOX_PUBLIC_RECEIPT_CHANGED")
    if (directory / names[3]).read_text() != checksum_text([directory / name for name in names[:3]]):
        raise ValueError("FIREFOX_PUBLIC_CHECKSUMS_CHANGED")
    return receipt


def credential_presence(environment):
    """Return booleans only. Never serialize credential values."""
    return {name: bool(environment.get(name, "").strip())
            for name in ("AMO_JWT_ISSUER", "AMO_JWT_SECRET")}


def amo_metadata():
    return {
        "default_locale": "en-US",
        "name": {"en-US": "ARE SoftwareGPU Diagnostics"},
        "summary": {"en-US": "Test local WebGL and WebGPU rendering, verify every returned pixel, and save a private graphics report."},
        "description": {"en-US": "Local WebGL/WebGPU shader, drawing and complete pixel readback checks. Results stay in this browser and can be saved as JSON. No website permissions, analytics or diagnostic network requests. This diagnostic companion does not install a native GPU driver or provide a missing browser graphics API. Source: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"},
        "homepage": {"en-US": "https://arelogic.space/projects/are-softwaregpu-engine/"},
        "support_url": {"en-US": f"https://github.com/{REPOSITORY}/issues"},
        "categories": {"firefox": ["web-development"]},
        "version": {
            "compatibility": ["firefox"],
            "custom_license": {"name": {"en-US": "PolyForm Noncommercial License 1.0.0"},
                               "text": {"en-US": (ROOT / "LICENSE.md").read_text(encoding="utf-8")}},
            "approval_notes": "Readable original source, no generated JavaScript dependencies. The source ZIP reproduces the XPI with Python tools/package_firefox_addon.py --version <manifest version> --output-dir <new directory>. Reviewer instructions: docs/firefox-addon-amo-listing.md. Open the toolbar action, Run graphics checks, then Save results as JSON. An unavailable WebGPU adapter is reported as unavailable. Author: Thomas Markgraf (pseudonym: OuroborosCollective).",
        },
    }


def accepted_amo_file(payload, version):
    file = payload.get("file", {})
    url = urllib.parse.urlsplit(file.get("url", ""))
    if (payload.get("version") != version or payload.get("channel") != "listed"
            or payload.get("is_disabled") is True or file.get("status") != "public"
            or re.fullmatch(r"sha256:[0-9a-f]{64}", file.get("hash", "")) is None
            or url.scheme != "https" or url.hostname not in ("addons.mozilla.org", "addons.cdn.mozilla.net")
            or url.username is not None or url.password is not None or url.port not in (None, 443)):
        raise ValueError("AMO_NOT_PUBLIC_LISTED_EXACT_VERSION")
    return file


def accepted_amo_listing(payload):
    url = urllib.parse.urlsplit(payload.get("url", ""))
    if (payload.get("guid") != ADDON_ID or payload.get("type") != "extension"
            or payload.get("status") != "public" or payload.get("is_disabled") is not False
            or url.scheme != "https" or url.hostname != "addons.mozilla.org"
            or url.username is not None or url.password is not None or url.port not in (None, 443)):
        raise ValueError("AMO_LISTING_NOT_PUBLIC_OR_IDENTITY_MISMATCH")
    return payload["url"]


def verify_signed_payload(unsigned, signed):
    """Container equality only; authenticity additionally needs AMO API/hash readback."""
    original, received = archive_entries(unsigned), archive_entries(signed)
    extras = set(received) - set(original)
    if (any(received.get(name) != data for name, data in original.items())
            or not extras or any(re.fullmatch(r"META-INF/[A-Za-z0-9_.-]+", name) is None for name in extras)
            or not extras.intersection(("META-INF/mozilla.rsa", "META-INF/cose.sig"))):
        raise ValueError("AMO_SIGNED_RUNTIME_CHANGED")


class NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("AMO_AUTH_REDIRECT_REFUSED")


class MozillaDownloadRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or target.hostname not in ("addons.mozilla.org", "addons.cdn.mozilla.net"):
            raise ValueError("AMO_DOWNLOAD_REDIRECT_REFUSED")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def amo_get(path, environment):
    # Wall clock and nonce are confined to the authentication transport, never rendering.
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    now = int(time.time())
    header = encode(b'{"alg":"HS256","typ":"JWT"}')
    payload = encode(json.dumps({"iss": environment["AMO_JWT_ISSUER"], "jti": secrets.token_hex(16),
                                 "iat": now, "exp": now + 60}, separators=(",", ":")).encode())
    body = f"{header}.{payload}"
    token = body + "." + encode(hmac.new(environment["AMO_JWT_SECRET"].encode(), body.encode(), hashlib.sha256).digest())
    url = AMO_API + path
    request = urllib.request.Request(url, headers={"Authorization": "JWT " + token, "Accept": "application/json"})
    try:
        with urllib.request.build_opener(NoAuthRedirect).open(request, timeout=60) as response:
            data = response.read(MAX_ARCHIVE + 1)
            if len(data) > MAX_ARCHIVE:
                raise ValueError("AMO_RESPONSE_SIZE_LIMIT")
            return json.loads(data)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise ValueError(f"AMO_AUTHENTICATED_READ_FAILED_HTTP_{error.code}") from None
    except urllib.error.URLError:
        raise ValueError("AMO_AUTHENTICATED_READ_NETWORK_FAILED") from None


def amo_version(version, environment):
    package.validate_version(version)
    return amo_get("addons/addon/" + urllib.parse.quote(ADDON_ID, safe="") + "/versions/" + version + "/", environment)


def sign_with_amo(directory, stage, version, sha, web_ext):
    presence = credential_presence(os.environ)
    print(json.dumps({"credential_presence": presence}, sort_keys=True))
    if not all(presence.values()):
        raise ValueError("BLOCKED_AMO_CREDENTIALS: configure AMO_JWT_ISSUER and AMO_JWT_SECRET repository secrets")
    receipt = stage_runtime(directory, version, sha, stage)
    payload = amo_version(version, os.environ)
    if payload is None:
        metadata = directory / "amo-metadata.json"
        write_once(metadata, (json.dumps(amo_metadata(), indent=2) + "\n").encode())
        environment = {**{key: value for key, value in os.environ.items() if not key.startswith("WEB_EXT_")},
                       "WEB_EXT_API_KEY": os.environ["AMO_JWT_ISSUER"],
                       "WEB_EXT_API_SECRET": os.environ["AMO_JWT_SECRET"]}
        result = subprocess.run([web_ext, "sign", "--channel", "listed", "--source-dir", str(stage),
            "--no-config-discovery", "--no-input", "--amo-base-url", AMO_API,
            "--amo-metadata", str(metadata), "--upload-source-code", str(directory / receipt["sourceArchive"]["name"]),
            "--artifacts-dir", str(directory / "web-ext-output"), "--approval-timeout", "300000", "--timeout", "300000"],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        # web-ext is not run in verbose mode. Mask both secrets even in failure diagnostics.
        output = result.stdout
        for key in presence:
            output = output.replace(os.environ[key], "[REDACTED]")
        print(output)
        if result.returncode:
            raise ValueError(f"AMO_SUBMISSION_TOOL_FAILED_EXIT_{result.returncode}: inspect the submission before retrying this tag")
        payload = amo_version(version, os.environ)
        if payload is None:
            raise ValueError("AMO_SUBMISSION_NOT_PUBLIC: inspect the AMO developer dashboard; no signing claim")
    # An existing pending version is never resubmitted or mistaken for approval.
    file = accepted_amo_file(payload, version)
    listing = amo_get("addons/addon/" + urllib.parse.quote(ADDON_ID, safe="") + "/", os.environ)
    if listing is None:
        raise ValueError("AMO_LISTING_NOT_PUBLIC_OR_IDENTITY_MISMATCH")
    listing_url = accepted_amo_listing(listing)
    signed = directory / f"are-softwaregpu-diagnostics-{version}-signed.xpi"
    with urllib.request.build_opener(MozillaDownloadRedirect).open(file["url"], timeout=60) as response:
        data = response.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE or hashlib.sha256(data).hexdigest() != file["hash"][7:]:
        raise ValueError("AMO_SIGNED_DOWNLOAD_HASH_MISMATCH")
    write_once(signed, data)
    verify_signed_payload(directory / receipt["package"]["name"], signed)
    result = {"schema": "are.firefox-amo-release.v1", "status": "AMO_PUBLIC_LISTED",
              "source_sha": sha, "version": version, "extension_id": ADDON_ID,
              "unsigned_package_sha256": receipt["package"]["sha256"],
              "source_archive_sha256": receipt["sourceArchive"]["sha256"],
              "amo_version_id": payload.get("id"), "amo_file_id": file.get("id"),
              "amo_listing_url": listing_url, "amo_download_url": file["url"], "signed_package": {
                  "name": signed.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
              "verification": "Authenticated AMO version is listed/public; downloaded bytes match AMO SHA256; every original runtime byte is preserved."}
    report = directory / f"firefox-addon-{version}-amo.json"
    write_once(report, (json.dumps(result, indent=2) + "\n").encode())
    checksums = directory / f"firefox-addon-{version}-signed-SHA256SUMS.txt"
    write_once(checksums, checksum_text([signed, report]).encode())
    return [signed, report, checksums]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "publish", "amo"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--web-ext", default="web-ext")
    args = parser.parse_args()
    version = package.validate_version(args.version)
    if platform.command("git", "rev-parse", "HEAD") != args.sha:
        raise ValueError("FIREFOX_CHECKOUT_SOURCE_MISMATCH")
    if platform.command("git", "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("FIREFOX_RELEASE_REQUIRES_CLEAN_SOURCE")
    if args.command == "prepare":
        if args.stage_dir is None:
            parser.error("--stage-dir is required for prepare")
        prepare_unsigned(args.directory, version, args.sha, args.stage_dir)
        return
    if args.command == "amo":
        presence = credential_presence(os.environ)
        if not all(presence.values()):
            print(json.dumps({"credential_presence": presence}, sort_keys=True))
            raise ValueError("BLOCKED_AMO_CREDENTIALS: see docs/FIREFOX_RELEASE_SIGNING.md")
    with tempfile.TemporaryDirectory(prefix="are-firefox-desktop-gate-") as temporary:
        verify_desktop_release(REPOSITORY, "v" + version, args.sha, temporary)
    if args.command == "publish":
        verify_public_files(args.directory, version, args.sha)
        paths = [args.directory / name for name in unsigned_names(version)]
        print(json.dumps({"status": "GITHUB_UNSIGNED_PUBLISHED", "assets": publish_assets(REPOSITORY, "v" + version, args.sha, paths)}))
    else:
        if args.stage_dir is None:
            parser.error("--stage-dir is required for amo")
        args.directory.mkdir(parents=True, exist_ok=False)
        platform.download_release_files(REPOSITORY, "v" + version, unsigned_names(version), args.directory)
        write_once(args.directory / "package-receipt.json", (args.directory / unsigned_names(version)[2]).read_bytes())
        verify_public_files(args.directory, version, args.sha)
        paths = sign_with_amo(args.directory, args.stage_dir, version, args.sha, args.web_ext)
        print(json.dumps({"status": "AMO_PUBLIC_LISTED_AND_GITHUB_SIGNED_PUBLISHED", "assets": publish_assets(REPOSITORY, "v" + version, args.sha, paths)}))


if __name__ == "__main__":
    main()
