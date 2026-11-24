#!/usr/bin/env python3
"""Owner-run setup of an enduring Android key and four GitHub Actions secrets."""
import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

REPOSITORY = "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"
ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = ("ANDROID_KEYSTORE_BASE64", "ANDROID_KEYSTORE_PASSWORD", "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD")


def private_command(args, env, input_value=None):
    result = subprocess.run([str(value) for value in args], input=input_value,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode:
        raise RuntimeError(f"{Path(str(args[0])).name} failed (exit {result.returncode}); secret-bearing diagnostics suppressed")
    return result.stdout


def prepare_key(path, alias, store_password, key_password, create=False):
    path = Path(path).expanduser().resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Store the signing key outside the repository")
    if not alias or not store_password or not key_password:
        raise ValueError("All key settings must be non-empty")
    env = os.environ.copy()
    env["ARE_SETUP_STORE_PASSWORD"] = store_password
    env["ARE_SETUP_KEY_PASSWORD"] = key_password
    if create:
        if path.exists():
            raise ValueError("Refusing to replace an existing signing key; reuse it without --create")
        path.parent.mkdir(parents=True, exist_ok=True)
        old_mask = os.umask(0o077)
        try:
            private_command(["keytool", "-genkeypair", "-noprompt", "-storetype", "JKS", "-keyalg", "RSA",
                             "-keysize", "3072", "-validity", "10000", "-dname", "CN=ARE SoftwareGPU,O=OuroborosCollective",
                             "-alias", alias, "-keystore", path, "-storepass:env", "ARE_SETUP_STORE_PASSWORD",
                             "-keypass:env", "ARE_SETUP_KEY_PASSWORD"], env)
        finally:
            os.umask(old_mask)
    if not path.is_file():
        raise ValueError("Signing keystore does not exist; use --create only for the first permanent key")
    path.chmod(0o600)
    certificate = private_command(["keytool", "-exportcert", "-alias", alias, "-keystore", path,
                                   "-storepass:env", "ARE_SETUP_STORE_PASSWORD"], env)
    # Verify the private-key password too, before uploading any settings.
    with tempfile.TemporaryDirectory(prefix="are-key-check-") as directory:
        private_command(["keytool", "-certreq", "-alias", alias, "-keystore", path,
                         "-storepass:env", "ARE_SETUP_STORE_PASSWORD", "-keypass:env", "ARE_SETUP_KEY_PASSWORD",
                         "-file", Path(directory) / "public-request.csr"], env)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    if len(encoded) > 48000:
        raise ValueError("Keystore exceeds the GitHub Actions secret budget")
    values = dict(zip(SECRET_NAMES, (encoded, store_password, alias, key_password)))
    return values, hashlib.sha256(certificate).hexdigest()


def configure_github(values):
    for name in SECRET_NAMES:
        # stdin carries values: never command arguments, generated shell, or logs.
        private_command(["gh", "secret", "set", name, "--repo", REPOSITORY], os.environ.copy(), values[name].encode("utf-8"))
    listed = json.loads(private_command(["gh", "secret", "list", "--repo", REPOSITORY, "--json", "name"], os.environ.copy()))
    names = {item["name"] for item in listed}
    if not set(SECRET_NAMES) <= names:
        raise RuntimeError("GitHub secret-name readback is incomplete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keystore", type=Path, required=True)
    parser.add_argument("--alias", default="are-release")
    parser.add_argument("--create", action="store_true", help="Create the first permanent key; never replace an existing one")
    parser.add_argument("--configure-github", action="store_true", help="Upload through your already authenticated gh account")
    args = parser.parse_args()
    password = getpass.getpass("Keystore password: ")
    if args.create and getpass.getpass("Repeat keystore password: ") != password:
        raise SystemExit("Keystore passwords differ")
    key_password = getpass.getpass("Private-key password (Enter uses keystore password): ") or password
    values, fingerprint = prepare_key(args.keystore, args.alias, password, key_password, args.create)
    if args.configure_github:
        configure_github(values)
    print(json.dumps({"status": "SECRET_NAMES_CONFIGURED" if args.configure_github else "LOCAL_KEY_VERIFIED",
                      "repository": REPOSITORY, "signer_certificate_sha256": fingerprint,
                      "secret_names": list(SECRET_NAMES) if args.configure_github else [],
                      "runtime_signing_verified": False}, sort_keys=True))
    print("Back up the keystore and passwords securely. The release workflow must still prove actual APK signing.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from None
