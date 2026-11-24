#!/usr/bin/env python3
"""Build evidence and immutable publication for the Android HTTPS companion."""
import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

if __package__:
    from . import platform_release as platform
    from .release_followup import REPOSITORY, publish_assets, tag_commit
    from .release_gate import (ReleaseGateError, android_version, android_signer_fingerprint,
                               verify_android_badging, verify_android_source)
else:
    import platform_release as platform
    from release_followup import REPOSITORY, publish_assets, tag_commit
    from release_gate import (ReleaseGateError, android_version, android_signer_fingerprint,
                              verify_android_badging, verify_android_source)

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = ("ANDROID_KEYSTORE_BASE64", "ANDROID_KEYSTORE_PASSWORD", "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD")
PACKAGE = "@ouroboroscollective/softwaregpu-gradio-client"


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_receipt(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise ReleaseGateError("Android evidence JSON exceeds its 64-KiB budget")
    return json.loads(path.read_text(encoding="utf-8"))


def checked(*args, cwd=None, env=None, private=False):
    process = subprocess.run([str(arg) for arg in args], cwd=cwd, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    if process.returncode:
        # A signing tool may repeat aliases or inputs. Keep secret-bearing output private.
        detail = "" if private else "\n" + process.stderr[-4000:]
        raise ReleaseGateError(f"{Path(str(args[0])).name} failed with exit {process.returncode}" + detail)
    return process.stdout


def sdk_tools():
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        raise ReleaseGateError("Android SDK is required")
    directory = Path(sdk) / "build-tools" / "35.0.0"
    for name in ("aapt", "apksigner", "zipalign"):
        if not (directory / name).is_file():
            raise ReleaseGateError("Android Build Tools 35.0.0 are required")
    return directory


def source_checkout(sha):
    if checked("git", "rev-parse", "HEAD", cwd=ROOT).strip() != sha:
        raise ReleaseGateError("Android build checkout differs from source SHA")
    if checked("git", "status", "--porcelain", "--untracked-files=no", cwd=ROOT).strip():
        raise ReleaseGateError("Android release requires clean tracked source")


def apk_name(tag):
    return f"ARE-SoftwareGPU-{android_version(tag)['version']}-android-companion.apk"


def verify_apk(path, tag, sha, scope):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ReleaseGateError("Missing regular APK")
    tools = sdk_tools()
    metadata = verify_android_source(path, tag, sha)
    verify_android_badging(checked(tools / "aapt", "dump", "badging", path), tag)
    signer = android_signer_fingerprint(checked(tools / "apksigner", "verify", "--verbose", "--print-certs", path), scope)
    checked(tools / "zipalign", "-c", "-P", "16", "4", path)
    return {**metadata, "schema": "are.android-apk.v1", "signing_scope": scope,
            "signer_certificate_sha256": signer,
            "artifact": {"name": path.name, "bytes": path.stat().st_size, "sha256": platform.digest(path)}}


def signing_environment(directory, ci_test):
    env = os.environ.copy()
    keystore = Path(directory) / "signing.jks"
    if ci_test:
        env["ANDROID_KEYSTORE_PASSWORD"] = "are-ci-test-only-not-a-release-key"
        env["ANDROID_KEY_PASSWORD"] = env["ANDROID_KEYSTORE_PASSWORD"]
        env["ANDROID_KEY_ALIAS"] = "are-ci-test"
        checked("keytool", "-genkeypair", "-noprompt", "-storetype", "JKS", "-keyalg", "RSA",
                "-keysize", "3072", "-validity", "30", "-dname", "CN=ARE CI TEST ONLY",
                "-alias", env["ANDROID_KEY_ALIAS"], "-keystore", keystore,
                "-storepass:env", "ANDROID_KEYSTORE_PASSWORD", "-keypass:env", "ANDROID_KEY_PASSWORD",
                env=env, private=True)
    else:
        missing = [name for name in SECRET_NAMES if not env.get(name)]
        if missing:
            print(json.dumps({"status": "BLOCKED_MISSING_ANDROID_SIGNING_SECRETS", "missing": missing}))
            raise ReleaseGateError("Configure the four persistent signing secrets using docs/ANDROID_RELEASE_SIGNING.md")
        try:
            content = base64.b64decode(env["ANDROID_KEYSTORE_BASE64"], validate=True)
        except (binascii.Error, ValueError) as error:
            raise ReleaseGateError("Android keystore secret is not valid base64") from error
        if not 128 <= len(content) <= 32768:
            raise ReleaseGateError("Android keystore has an invalid size")
        keystore.write_bytes(content)
    keystore.chmod(0o600)
    return keystore, env


def sign_apk(unsigned, tag, sha, output, ci_test=False):
    source_checkout(sha)
    tools = sdk_tools()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / apk_name(tag)
    if target.exists():
        raise ReleaseGateError("Refusing to replace an already staged APK")
    verify_android_source(unsigned, tag, sha)
    with tempfile.TemporaryDirectory(prefix="are-android-sign-") as directory:
        keystore, env = signing_environment(directory, ci_test)
        aligned = Path(directory) / "aligned.apk"
        checked(tools / "zipalign", "-P", "16", "4", unsigned, aligned)
        checked(tools / "apksigner", "sign", "--ks", keystore,
                "--ks-pass", "env:ANDROID_KEYSTORE_PASSWORD", "--ks-key-alias", env["ANDROID_KEY_ALIAS"],
                "--key-pass", "env:ANDROID_KEY_PASSWORD", "--v4-signing-enabled", "false",
                "--out", target, aligned, env=env, private=True)
    result = verify_apk(target, tag, sha, "ci-test" if ci_test else "release")
    write_json(output / "android-apk.json", result)
    return result


def reuse_apk(repo, tag, sha, output):
    """Recover the exact immutable APK even if a previous upload stopped mid-release."""
    platform.verify_tag_identity(repo, tag, sha)
    release = platform.api(f"repos/{repo}/releases/tags/{tag}")
    matching = [asset for asset in release["assets"] if asset.get("name") == apk_name(tag)]
    if len(matching) > 1:
        raise ReleaseGateError("Ambiguous existing Android APK")
    if not matching:
        return False
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    platform.download_release_files(repo, tag, [apk_name(tag)], output)
    result = verify_apk(output / apk_name(tag), tag, sha, "release")
    write_json(output / "android-apk.json", result)
    return True


def verify_signer_continuity(repo, signer):
    """A published APK establishes update identity even before its receipt uploads."""
    for page in range(1, 101):
        releases = platform.api(f"repos/{repo}/releases?per_page=100&page={page}")
        if not isinstance(releases, list):
            raise ReleaseGateError("Malformed release listing for signer continuity")
        for release in releases:
            if release.get("draft") is not False:
                continue
            companion_assets = [a for a in release.get("assets", [])
                                if a.get("name", "").startswith("ARE-SoftwareGPU-")
                                and a["name"].endswith("-android-companion.apk")]
            receipts = [a for a in release.get("assets", []) if a.get("name") == "android-release.json"]
            if not companion_assets and not receipts:
                continue
            previous_tag = release.get("tag_name")
            expected_name = apk_name(previous_tag)
            if len(companion_assets) != 1 or companion_assets[0]["name"] != expected_name or len(receipts) > 1:
                raise ReleaseGateError("Incomplete or ambiguous previous Android publication")
            with tempfile.TemporaryDirectory(prefix="are-android-key-readback-") as directory:
                platform.download_release_files(repo, previous_tag, [expected_name], Path(directory))
                previous = verify_apk(Path(directory) / expected_name, previous_tag, tag_commit(repo, previous_tag), "release")
                if previous["signer_certificate_sha256"] != signer:
                    raise ReleaseGateError("Android signing certificate differs from the published update lineage")
            return
        if len(releases) < 100:
            return  # First production-signed companion, not a key-rotation claim.
    raise ReleaseGateError("Incomplete signer continuity history")


def zip_client(path, files):
    with ZipFile(path, "x", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content, executable in sorted(files):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content, compress_type=ZIP_DEFLATED, compresslevel=9)


def node_assets(tag, output):
    version = android_version(tag)["version"]
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    checked("npm", "test", cwd=ROOT / "clients/node")
    with tempfile.TemporaryDirectory(prefix="are-node-stage-") as directory:
        stage = Path(directory) / "client"
        shutil.copytree(ROOT / "clients/node", stage, ignore=shutil.ignore_patterns("node_modules", ".npmrc", "*.tgz"))
        package = json.loads((stage / "package.json").read_text(encoding="utf-8"))
        package["version"] = version
        write_json(stage / "package.json", package)
        packed = json.loads(checked("npm", "pack", "--json", "--pack-destination", directory, cwd=stage))
        tarball = Path(directory) / packed[0]["filename"]
        with tarfile.open(tarball, "r:gz") as archive:
            manifest = json.load(archive.extractfile("package/package.json"))
            if manifest.get("name") != PACKAGE or manifest.get("version") != version:
                raise ReleaseGateError("Node archive version differs from release")
            for name in ("package/bin/are-gradio.mjs", "package/LICENSE.md", "package/NOTICE"):
                if not archive.getmember(name).isfile():
                    raise ReleaseGateError("Incomplete Node client archive")
        platform.copy_immutable(tarball, output / tarball.name)
        files = [(name, (stage / name).read_bytes(), False) for name in ("README.md", "LICENSE.md", "NOTICE")]
        files.append(("are-gradio.mjs", (stage / "bin/are-gradio.mjs").read_bytes(), False))
        for os_name, wrapper, body in (("linux", "are-gradio", b'#!/bin/sh\nexec node "$(dirname "$0")/are-gradio.mjs" "$@"\n'),
                                      ("windows", "are-gradio.cmd", b'@echo off\r\nnode "%~dp0are-gradio.mjs" %*\r\n')):
            target = Path(directory) / f"ARE-Gradio-{version}-{os_name}-node.zip"
            zip_client(target, files + [(wrapper, body, os_name == "linux")])
            platform.copy_immutable(target, output / target.name)
    return [output / packed[0]["filename"], output / f"ARE-Gradio-{version}-linux-node.zip",
            output / f"ARE-Gradio-{version}-windows-node.zip"]


def publish_node(tarball, tag):
    """GitHub Packages retries compare the actual registry tarball, never just its version."""
    version = android_version(tag)["version"]
    if not os.environ.get("NODE_AUTH_TOKEN"):
        raise ReleaseGateError("GitHub Packages authentication is missing")
    with tempfile.TemporaryDirectory(prefix="are-node-registry-") as directory:
        config = Path(directory) / "npmrc"
        config.write_text('@ouroboroscollective:registry=https://npm.pkg.github.com\n//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n', encoding="utf-8")
        config.chmod(0o600)
        flags = ["--registry=https://npm.pkg.github.com", "--userconfig", str(config)]
        target = f"{PACKAGE}@{version}"
        process = subprocess.run(["npm", "view", target, "version", "--json", *flags], cwd=directory,
                                 capture_output=True, text=True, encoding="utf-8")
        if process.returncode:
            try:
                error = json.loads(process.stdout)["error"]["code"]
            except (ValueError, KeyError, TypeError):
                raise ReleaseGateError("Unable to verify GitHub Packages publication state")
            if error != "E404":
                raise ReleaseGateError("GitHub Packages state is unavailable: " + str(error))
            checked("npm", "publish", Path(tarball).resolve(), "--access", "public", *flags, cwd=directory, private=True)
        elif json.loads(process.stdout) != version:
            raise ReleaseGateError("Registry returned another Node package version")
        packed = json.loads(checked("npm", "pack", target, "--json", "--pack-destination", directory, *flags,
                                    cwd=directory, private=True))
        readback = Path(directory) / packed[0]["filename"]
        if platform.digest(readback) != platform.digest(tarball):
            raise ReleaseGateError("Published Node package differs from release tarball")
    print("GITHUB_PACKAGES_FULL_TARBALL_READBACK_OK")


def complete_receipt(directory, tag, sha, smoke_path, scope):
    directory = Path(directory)
    apk = verify_apk(directory / apk_name(tag), tag, sha, scope)
    smoke = read_receipt(smoke_path)
    required = ("install", "launch", "process_alive", "welcome_ui", "installed_apk_bytes", "uninstall")
    if (smoke.get("schema") != "are.android-emulator-smoke.v1" or smoke.get("passed") is not True
            or smoke.get("source_sha") != sha or smoke.get("version") != android_version(tag)["version"]
            or smoke.get("apk_sha256") != apk["artifact"]["sha256"]
            or smoke.get("signing_scope") != scope or smoke.get("device_kind") != "emulator"
            or type(smoke.get("android_api")) is not int or smoke["android_api"] != 35
            or any(smoke.get("checks", {}).get(name) is not True for name in required)):
        raise ReleaseGateError("Android emulator evidence is incomplete or belongs to another APK")
    names = [apk_name(tag)]
    files = [directory / name for name in names]
    if any(not p.is_file() or p.is_symlink() for p in files):
        raise ReleaseGateError("Incomplete Android release assets")
    receipt = {"schema": "are.android-release.v1", "tag": tag, "source_sha": sha, **android_version(tag),
               "runtime": "https-companion", "signing_scope": scope,
               "signer_certificate_sha256": apk["signer_certificate_sha256"],
               "emulator_checks": {name: True for name in required},
               "assets": [{"name": p.name, "bytes": p.stat().st_size, "sha256": platform.digest(p)} for p in files]}
    write_json(directory / "android-release.json", receipt)
    files.append(directory / "android-release.json")
    checksum = directory / "android-checksums.sha256"
    checksum.write_text("".join(f"{platform.digest(p)}  {p.name}\n" for p in files), encoding="utf-8")
    return files + [checksum], receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    version = sub.add_parser("version")
    version.add_argument("--tag", required=True)
    version.add_argument("--github-output", type=Path)
    for name in ("sign", "reuse", "node", "publish", "publish-node"):
        item = sub.add_parser(name)
        item.add_argument("--tag", required=True)
        item.add_argument("--sha", required=True)
        item.add_argument("--output-dir", type=Path, required=True)
        if name in ("reuse", "publish", "publish-node"):
            item.add_argument("--repo", default=REPOSITORY, choices=[REPOSITORY])
        if name == "sign":
            item.add_argument("--unsigned", type=Path, required=True)
            item.add_argument("--ci-test", action="store_true")
        if name == "reuse":
            item.add_argument("--github-output", type=Path, required=True)
        if name == "publish":
            item.add_argument("--smoke", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "version":
        result = android_version(args.tag)
        text = "".join(f"{key}={value}\n" for key, value in result.items())
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as destination:
                destination.write(text)
        print(text, end="")
    elif args.command == "sign":
        print(json.dumps(sign_apk(args.unsigned, args.tag, args.sha, args.output_dir, args.ci_test), sort_keys=True))
    elif args.command == "reuse":
        reused = reuse_apk(args.repo, args.tag, args.sha, args.output_dir)
        with args.github_output.open("a", encoding="utf-8") as destination:
            destination.write(f"reused={'true' if reused else 'false'}\n")
    elif args.command == "node":
        source_checkout(args.sha)
        print(json.dumps([path.name for path in node_assets(args.tag, args.output_dir)]))
    elif args.command == "publish-node":
        source_checkout(args.sha)
        files = node_assets(args.tag, args.output_dir)
        tarball, = [path for path in files if path.suffix == ".tgz"]
        publish_node(tarball, args.tag)
        receipt = {"schema": "are.node-client-release.v1", "tag": args.tag, "source_sha": args.sha,
                   "version": android_version(args.tag)["version"], "runtime": "external-node-20-plus-https-client",
                   "registry": "https://npm.pkg.github.com", "registry_tarball_sha256": platform.digest(tarball),
                   "assets": [{"name": p.name, "bytes": p.stat().st_size, "sha256": platform.digest(p)} for p in files]}
        write_json(args.output_dir / "node-release.json", receipt)
        files.append(args.output_dir / "node-release.json")
        checksum = args.output_dir / "node-checksums.sha256"
        checksum.write_text("".join(f"{platform.digest(p)}  {p.name}\n" for p in files), encoding="utf-8")
        files.append(checksum)
        print(json.dumps({"status": "PUBLISHED_AND_READ_BACK", "assets": publish_assets(args.repo, args.tag, args.sha, files)}, sort_keys=True))
    else:
        files, receipt = complete_receipt(args.output_dir, args.tag, args.sha, args.smoke, "release")
        verify_signer_continuity(args.repo, receipt["signer_certificate_sha256"])
        print(json.dumps({"status": "PUBLISHED_AND_READ_BACK", "assets": publish_assets(args.repo, args.tag, args.sha, files)}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ReleaseGateError as error:
        raise SystemExit(str(error)) from None
