"""SHA-pinned replay of independent Khronos GLB 2.0 sample assets (opt-in, offline by default).

Purpose: decode receipts that do not depend on this repository's own fixture
encoders. Each pinned Khronos sample is (1) admitted by the UNCHANGED GLB 2.0
preflight, (2) refused by the draft sandbox because it is a version 2
container, and (3) re-wrapped byte-for-byte (same JSON and BIN payloads) into
the unratified GLB v3 draft container, where the sandbox must report the same
payload SHA-256 values.

The assets are not redistributed here. ``--fetch`` downloads them from the
pinned Khronos commit and verifies size and SHA-256; without it only local
files are read. Re-wrapped files exist in memory only. No GLB v3 conformance
or ratification is claimed, and nothing is admitted to a renderer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import urllib.request
from urllib.parse import urlparse

from tools.glb_container_preflight import BIN_CHUNK, JSON_CHUNK, inspect_glb
from tools.gltf21_glb3_sandbox import (
    CONTRACT,
    SandboxRejection,
    inspect_glb3_sandbox,
    receipt_digest,
)

MANIFEST = Path(__file__).resolve().parents[1] / "evidence/gltf21-glb3-independent-assets-v1.json"
PROTOCOL = "are.gltf21-glb3-independent-assets.v1"
REPORT_PROTOCOL = "are.gltf21-glb3-independent-replay.v1"
SOURCE_HOST = "raw.githubusercontent.com"
SOURCE_PATH = re.compile(r"/KhronosGroup/glTF-Sample-Assets/[0-9a-f]{40}/Models/"
                         r"[A-Za-z0-9]+/glTF-Binary/[A-Za-z0-9]+\.glb\Z")
ALIAS = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
FILE = re.compile(r"[A-Za-z0-9]+\.glb\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_ASSET_BYTES = 8 * 1024 * 1024
BLOCK = 1024 * 1024


def _need(condition, code: str) -> None:
    if not condition:
        raise ValueError("INDEPENDENT_ASSET_" + code)


def load_manifest(path=MANIFEST) -> dict:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    _need(isinstance(document, dict) and document.get("protocol") == PROTOCOL, "PROTOCOL")
    _need(document.get("contract") == CONTRACT, "CONTRACT")
    assets = document.get("assets")
    _need(isinstance(assets, list) and 1 <= len(assets) <= 16, "COUNT")
    seen = set()
    for asset in assets:
        _need(isinstance(asset, dict), "ENTRY")
        alias = asset.get("alias")
        _need(isinstance(alias, str) and ALIAS.match(alias) and alias not in seen, "ALIAS")
        seen.add(alias)
        _need(isinstance(asset.get("file"), str) and FILE.match(asset["file"]), "FILE")
        _need(type(asset.get("bytes")) is int and 20 <= asset["bytes"] <= MAX_ASSET_BYTES
              and isinstance(asset.get("sha256"), str) and HEX64.match(asset["sha256"]),
              "HASH_OR_SIZE")
        url = urlparse(str(asset.get("source_url")))
        _need(url.scheme == "https" and url.hostname == SOURCE_HOST
              and SOURCE_PATH.match(url.path) and not url.query and not url.fragment,
              "SOURCE")
        _need(isinstance(asset.get("license"), str) and asset["license"], "LICENSE")
        _need(isinstance(asset.get("expected"), dict), "EXPECTED")
    return document


def verify(path, asset: dict) -> bytes:
    """Return the file bytes only if size and SHA-256 match the pin."""
    path = Path(path)
    _need(path.is_file() and not path.is_symlink()
          and path.stat().st_size == asset["bytes"], "SIZE_MISMATCH")
    raw = path.read_bytes()
    _need(hashlib.sha256(raw).hexdigest() == asset["sha256"], "HASH_MISMATCH")
    return raw


def fetch_one(asset: dict, destination) -> bytes:
    destination = Path(destination)
    if destination.is_file():
        return verify(destination, asset)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".unverified")
    temporary.unlink(missing_ok=True)
    try:
        request = urllib.request.Request(
            asset["source_url"], headers={"User-Agent": "glb-asset-verification/1.0"})
        with urllib.request.urlopen(request, timeout=40) as response, \
                temporary.open("wb") as output:
            _need(response.status == 200, "HTTP_STATUS")
            written = 0
            while block := response.read(BLOCK):
                written += len(block)
                _need(written <= asset["bytes"], "TOO_LARGE")
                output.write(block)
        raw = verify(temporary, asset)
        temporary.replace(destination)
        return raw
    finally:
        temporary.unlink(missing_ok=True)


def split_glb2(raw: bytes) -> tuple:
    """JSON and optional BIN payloads of a GLB 2.0 file admitted by the GLB2 preflight."""
    inspect_glb(raw)
    json_length = struct.unpack_from("<I", raw, 12)[0]
    payload = raw[20:20 + json_length]
    position = 20 + json_length
    if position == len(raw):
        return payload, None
    binary_length = struct.unpack_from("<I", raw, position)[0]
    return payload, raw[position + 8:position + 8 + binary_length]


def rewrap_as_glb3_draft(json_payload: bytes, binary_payload) -> bytes:
    """Same payload bytes inside the draft container (8-byte aligned chunk starts)."""
    chunks = [(JSON_CHUNK, json_payload)]
    if binary_payload is not None:
        chunks.append((BIN_CHUNK, binary_payload))
    body = bytearray()
    for position, (kind, payload) in enumerate(chunks):
        body += struct.pack("<IIQ", kind, 0, len(payload)) + payload
        if position + 1 < len(chunks):
            body += bytes(-len(body) % 8)
    return b"glTF" + struct.pack("<IQ", 3, 16 + len(body)) + bytes(body)


def replay_asset(raw: bytes) -> dict:
    """Decode one independent GLB 2.0 asset through both disjoint paths."""
    preflight = inspect_glb(raw)
    try:
        inspect_glb3_sandbox(raw, contract=CONTRACT)
    except SandboxRejection as rejection:
        refusal = rejection.code
    else:
        refusal = "UNEXPECTEDLY_ACCEPTED"
    json_payload, binary_payload = split_glb2(raw)
    wrapped = rewrap_as_glb3_draft(json_payload, binary_payload)
    receipt = inspect_glb3_sandbox(wrapped, contract=CONTRACT)
    payloads = [json_payload] + ([] if binary_payload is None else [binary_payload])
    digests = [hashlib.sha256(payload).hexdigest() for payload in payloads]
    _need([chunk["sha256"] for chunk in receipt["container"]["chunks"]] == digests,
          "PAYLOAD_DIGEST_DRIFT")
    return {
        "glb2_preflight": preflight,
        "draft_sandbox_on_glb2": refusal,
        "payload_sha256": digests,
        "rewrapped_glb3_draft": {
            "bytes": len(wrapped), "sha256": hashlib.sha256(wrapped).hexdigest(),
            "receipt_sha256": receipt_digest(receipt),
            "asset_version": receipt["gltf"]["asset_version"],
            "buffer_views_checked": receipt["gltf"]["buffer_views_checked"],
            "accessors_checked": receipt["gltf"]["accessors_checked"],
            "draft_features_observed": receipt["draft_features_observed"],
        },
    }


def replay(directory, manifest: dict, *, fetch: bool = False) -> dict:
    results = []
    for asset in manifest["assets"]:
        path = Path(directory) / asset["file"]
        raw = fetch_one(asset, path) if fetch else verify(path, asset)
        observed = replay_asset(raw)
        _need(observed["draft_sandbox_on_glb2"] == "VERSION_2_OUT_OF_SCOPE",
              "GLB2_NOT_REFUSED:" + asset["alias"])
        _need(observed == asset["expected"], "REPLAY_DRIFT:" + asset["alias"])
        results.append({"alias": asset["alias"], "bytes": asset["bytes"],
                        "sha256": asset["sha256"], "replay": observed})
    return {"protocol": REPORT_PROTOCOL, "contract": CONTRACT, "status": "PASS",
            "assets_modified": False, "ratification_claimed": False,
            "runtime_admission": "refused", "results": results}


def rebuild_expected(directory, manifest_path) -> dict:
    """Deliberately re-derive the ``expected`` blocks from SHA-verified originals.

    Needed after an intentional change of the sandbox receipt; the asset pins
    (size and SHA-256) are never rewritten.
    """
    manifest = load_manifest(manifest_path)
    for asset in manifest["assets"]:
        asset["expected"] = replay_asset(verify(Path(directory) / asset["file"], asset))
    Path(manifest_path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8", newline="\n")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--fetch", action="store_true",
                        help="download missing pinned assets (network)")
    parser.add_argument("--rebuild-expected", action="store_true",
                        help="rewrite expected blocks from verified local originals")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.rebuild_expected:
            rebuild_expected(args.assets_dir, args.manifest)
        report = replay(args.assets_dir, load_manifest(args.manifest), fetch=args.fetch)
    except (ValueError, OSError) as error:
        parser.exit(2, "INDEPENDENT_REPLAY_REJECTED:%s\n" % error)
    text = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.receipt:
        try:
            if args.receipt.is_symlink() or args.receipt.exists():
                raise FileExistsError(str(args.receipt))
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation: never replace an existing file, e.g. a pinned asset.
            with args.receipt.open("x", encoding="utf-8", newline="\n") as target:
                target.write(text)
        except FileExistsError:
            parser.exit(2, "INDEPENDENT_REPLAY_REJECTED:RECEIPT_EXISTS\n")
        except OSError as error:
            parser.exit(2, "INDEPENDENT_REPLAY_REJECTED:RECEIPT_UNWRITABLE:%s\n"
                        % type(error).__name__)
    print(json.dumps({"status": report["status"], "assets": len(report["results"])},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
