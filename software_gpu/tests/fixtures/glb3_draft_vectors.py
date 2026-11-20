"""Deterministic vectors and seeded mutations for the UNRATIFIED GLB v3 draft sandbox.

Test support only. The encoders here are written separately from the inspected
parser (``tools.gltf21_glb3_sandbox``) and are never used by it. Nothing here is
a Khronos conformance asset: official GLB v3 conformance files did not exist
when the draft was read on 2026-11-20.

Regenerate the pinned evidence after a deliberate contract change with
``python -m software_gpu.tests.fixtures.glb3_draft_vectors --write``.
"""
from __future__ import annotations

import base64
import copy
import functools
import gzip
import hashlib
import json
from pathlib import Path
import struct

from tools.gltf21_glb3_sandbox import (
    CONTRACT,
    MAX_DATA_URI_CHARS,
    MAX_EXTERNAL_REFERENCES,
    MAX_JSON_DEPTH,
    SPEC_BASIS,
    SandboxRejection,
    frame_verdict,
    inspect_glb3_sandbox,
    receipt_digest,
)

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/gltf21-glb3-sandbox-receipts-v1.json"
EVIDENCE_PROTOCOL = "are.gltf21-glb3-sandbox-evidence.v1"
MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
CUSTOM_CHUNK = 0x0000007B
MASK64 = (1 << 64) - 1
FRAMING_SEED, FRAMING_CASES = 0x284_2026_1120, 4000
JSON_SEED, JSON_CASES = 0x284_0000_0021, 1500
BUNDLE_MAGIC = b"AREGLB3F"


def compact(document) -> bytes:
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def encode_glb3(chunks, *, pad: int = 0, trailing_pad: bool = False,
                byteorder: str = "<") -> bytes:
    """Draft layout: 16-byte file header, 16-byte chunk headers, 8-byte chunk starts.

    Padding is outside ``chunkLength``. ``byteorder='>'`` builds a deliberately
    invalid big-endian file for negative tests.
    """
    body = bytearray()
    for position, chunk in enumerate(chunks):
        kind, payload = chunk[0], chunk[1]
        encoding = chunk[2] if len(chunk) > 2 else 0
        body += struct.pack(byteorder + "IIQ", kind, encoding, len(payload)) + payload
        if position + 1 < len(chunks) or trailing_pad:
            body += bytes([pad]) * (-len(body) % 8)
    return MAGIC + struct.pack(byteorder + "IQ", 3, 16 + len(body)) + bytes(body)


def loaders_gl_style_glb3(document, binaries=(), prefix=()) -> bytes:
    """Port of ``createGLBV3`` from visgl/loaders.gl (MIT) at commit
    a4faaba29ad530c05d89cbfa1285122b997e9892,
    ``modules/scene/test/gltf/test-utils/create-glb-v3.ts``.

    That independent implementation pads every payload to FOUR bytes inside
    ``chunkLength`` and writes the next chunk header immediately. It agrees with
    the Khronos draft only while every padded length is a multiple of eight.
    """
    chunks = list(prefix) + [(JSON_CHUNK, compact(document))]
    chunks += [(BIN_CHUNK, binary) for binary in binaries]
    body = bytearray()
    for kind, payload in chunks:
        padded = -(-len(payload) // 4) * 4
        fill = b" " if kind == JSON_CHUNK else b"\x00"
        body += struct.pack("<IIQ", kind, 0, padded) + payload
        body += fill * (padded - len(payload))
    return MAGIC + struct.pack("<IQ", 3, 16 + len(body)) + bytes(body)


def khronos_issue_2594_custom_before_json() -> bytes:
    """Layout table published in KhronosGroup/glTF issue #2594 (2026-10-10 comment):

    glTF | 3 | 96 | 123 | 0 | 16 | customData?????? |
    JSON | 0 | 32 | {"asset":{"version":"2.1"}} followed by five spaces

    The six filler bytes are not published, so this is a layout reconstruction
    (filled with zeros), NOT a byte copy of the community archive.
    """
    custom = b"customData" + bytes(6)
    document = b'{"asset":{"version":"2.1"}}' + b" " * 5
    data = encode_glb3([(CUSTOM_CHUNK, custom), (JSON_CHUNK, document)])
    assert len(data) == 96
    return data


TRIANGLE_BIN = (struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
                + struct.pack("<3H", 0, 1, 2))


def triangle_document(version: str = "2.0", **buffer) -> dict:
    return {
        "asset": {"version": version},
        "buffers": [dict(byteLength=len(TRIANGLE_BIN), **buffer)],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                        {"buffer": 0, "byteOffset": 36, "byteLength": 6}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3,
                       "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
                      {"bufferView": 1, "componentType": 5123, "count": 3,
                       "type": "SCALAR"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0,
    }


def complex_document() -> dict:
    """Uses the draft-only properties the sandbox reports but never resolves."""
    return {
        "asset": {"version": "2.1", "minVersion": "2.1", "thumbnail": 0},
        "extensionsUsed": ["KHR_mesh_quantization", "KHR_node_visibility",
                           "VENDOR_unverified_demo"],
        "extensionsRequired": ["KHR_mesh_quantization"],
        "buffers": [{"byteLength": 42, "chunk": 1}, {"byteLength": 24, "chunk": 2},
                    {"byteLength": 27, "chunk": 3},
                    {"byteLength": 504, "uri": "external.bin"}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                        {"buffer": 0, "byteOffset": 36, "byteLength": 6},
                        {"buffer": 1, "byteLength": 24},
                        {"buffer": 2, "byteLength": 27}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3,
                       "type": "VEC3"},
                      {"bufferView": 1, "componentType": 5123, "count": 3,
                       "type": "SCALAR"},
                      {"bufferView": 2, "componentType": 5130, "count": 3,
                       "type": "SCALAR"}],
        "images": [{"bufferView": 2, "mimeType": "image/png"},
                   {"uri": "../textures/albedo.png"}],
        "files": [{"bufferView": 3, "mimeType": "model/gltf+json"},
                  {"uri": "parts/a.glb", "mimeType": "model/gltf-binary",
                   "aliases": [{"alias": "parts/a.bin", "file": 2}]},
                  {"uri": "https://example.org/a.bin",
                   "mimeType": "application/gltf-buffer"}],
        "externalAssets": [{"file": 0}, {"file": 1}],
        "shapes": [{"type": "box"}],
        "scenes": [{"nodes": []}],
    }


def complex_chunks() -> list:
    return [(JSON_CHUNK, compact(complex_document())), (BIN_CHUNK, TRIANGLE_BIN),
            (BIN_CHUNK, struct.pack("<3d", 1.0, 2.0, 3.0)),
            (JSON_CHUNK, b'{"asset":{"version":"2.1"}}')]


def _loaders_document(remainder: int) -> dict:
    """Smallest document whose loaders.gl-padded JSON length is ``remainder`` mod 8."""
    for extra in range(8):
        document = {"asset": {"version": "2.0", "generator": "loaders.gl" + "x" * extra},
                    "buffers": [{"byteLength": 8}]}
        if -(-len(compact(document)) // 4) * 4 % 8 == remainder:
            return document
    raise AssertionError("no document for remainder")


def _depth_bomb() -> bytes:
    return (b'{"asset":{"version":"2.1"},"extras":' + b"[" * (MAX_JSON_DEPTH + 1)
            + b"]" * (MAX_JSON_DEPTH + 1) + b"}")


# Platform-independent stand-in: only the gzip signature matters to the sandbox.
# (Real ``gzip.compress`` output differs per zlib build, so it is never pinned.)
GZIP_SIGNATURE_BLOB = bytes.fromhex("1f8b0800000000000003") + bytes(16)


def gzip_bomb(megabytes: int = 32) -> bytes:
    """Real bomb: a few kilobytes that inflate to ``megabytes`` MiB of zeros.

    Used by unpinned runtime tests only; the sandbox must never inflate it.
    """
    return gzip.compress(bytes(megabytes * 1024 * 1024), compresslevel=9)


def repair_length(data: bytes) -> bytes:
    """Make the declared 64-bit file length consistent with the actual size."""
    return data[:8] + struct.pack("<Q", len(data)) + data[16:]


def accepted_vectors() -> list:
    """(name, origin, bytes) for vectors the draft sandbox must accept."""
    minimal = b'{"asset":{"version":"2.1"}}'
    return [
        ("minimal-json-only", "in-process draft encoder",
         encode_glb3([(JSON_CHUNK, minimal)])),
        ("implicit-bin-triangle-gltf20", "in-process draft encoder",
         encode_glb3([(JSON_CHUNK, compact(triangle_document())),
                      (BIN_CHUNK, TRIANGLE_BIN)])),
        ("custom-chunk-before-json-explicit-bin", "in-process draft encoder",
         encode_glb3([(CUSTOM_CHUNK, b"producer-private"),
                      (JSON_CHUNK, compact(triangle_document("2.1", chunk=2))),
                      (BIN_CHUNK, TRIANGLE_BIN)], pad=0x5A)),
        ("multi-chunk-files-external-assets", "in-process draft encoder",
         encode_glb3(complex_chunks())),
        ("trailing-padding-after-last-chunk", "in-process draft encoder",
         encode_glb3([(JSON_CHUNK, minimal)], trailing_pad=True)),
        ("khronos-issue-2594-custom-before-json-layout",
         "layout table by a Khronos contributor, issue #2594, 2026-10-10",
         khronos_issue_2594_custom_before_json()),
        ("loaders-gl-a4faaba-lengths-multiple-of-8",
         "port of visgl/loaders.gl createGLBV3 (independent implementation)",
         loaders_gl_style_glb3(_loaders_document(0), [bytes(range(8))])),
        ("data-uri-with-gzip-signature-not-decoded", "in-process draft encoder",
         encode_glb3([(JSON_CHUNK, compact({
             "asset": {"version": "2.1"},
             "images": [{"uri": "data:application/gzip;base64,"
                         + base64.b64encode(GZIP_SIGNATURE_BLOB).decode("ascii")}]}))])),
        ("bin-chunk-with-gzip-signature-stays-opaque", "in-process draft encoder",
         encode_glb3([(JSON_CHUNK, compact({
             "asset": {"version": "2.1"},
             "buffers": [{"byteLength": len(GZIP_SIGNATURE_BLOB), "chunk": 1}]})),
                      (BIN_CHUNK, GZIP_SIGNATURE_BLOB)])),
    ]


def rejected_vectors() -> list:
    """(name, origin, bytes) for vectors the draft sandbox must refuse."""
    minimal = b'{"asset":{"version":"2.1"}}'
    valid = encode_glb3([(JSON_CHUNK, compact(triangle_document())),
                         (BIN_CHUNK, TRIANGLE_BIN)])
    own = "in-process negative"

    def patched(offset: int, fmt: str, value: int) -> bytes:
        data = bytearray(valid)
        struct.pack_into(fmt, data, offset, value)
        return bytes(data)

    def with_json(text: bytes) -> bytes:
        return encode_glb3([(JSON_CHUNK, text)])

    def with_document(document) -> bytes:
        return encode_glb3([(JSON_CHUNK, compact(document)), (BIN_CHUNK, TRIANGLE_BIN)])

    out_of_bounds = triangle_document()
    out_of_bounds["bufferViews"][1]["byteLength"] = 7
    too_small = triangle_document()
    too_small["buffers"][0]["byteLength"] = len(TRIANGLE_BIN) + 1
    too_small["bufferViews"] = []
    too_small["accessors"] = []
    many = {"asset": {"version": "2.1"},
            "images": [{"uri": "t%d.png" % i} for i in range(MAX_EXTERNAL_REFERENCES + 1)]}
    main_json_file = {"asset": {"version": "2.1"},
                      "buffers": [{"byteLength": 8, "chunk": 0}],
                      "bufferViews": [{"buffer": 0, "byteLength": 8}],
                      "files": [{"bufferView": 0, "mimeType": "model/gltf+json"}]}
    return [
        ("loaders-gl-a4faaba-4-byte-alignment-divergence",
         "port of visgl/loaders.gl createGLBV3 (independent implementation)",
         loaders_gl_style_glb3(_loaders_document(4), [bytes(range(8))])),
        ("big-endian-file", own,
         encode_glb3([(JSON_CHUNK, minimal)], byteorder=">")),
        ("glb-version-2-container", own,
         MAGIC + struct.pack("<II", 2, 12 + 8 + 28) + struct.pack("<II", 28, JSON_CHUNK)
         + minimal + b" "),
        ("glb-version-4-container", own, MAGIC + struct.pack("<IQ", 4, 16)),
        ("declared-length-msb", own, patched(8, "<Q", (1 << 63) | len(valid))),
        ("declared-length-32-bit-truncation-trap", own,
         patched(8, "<Q", (1 << 32) + len(valid))),
        ("chunk-length-msb-wraparound", own, patched(24, "<Q", MASK64 - 15)),
        ("chunk-length-32-bit-truncation-trap", own,
         patched(24, "<Q", (1 << 32) + struct.unpack_from("<Q", valid, 24)[0])),
        ("chunk-length-beyond-file", own, patched(24, "<Q", (1 << 63) - 1)),
        ("truncated-inside-chunk-header", own, valid[:24]),
        ("truncated-inside-chunk-header-length-repaired", own, repair_length(valid[:24])),
        ("truncated-inside-payload", own, valid[:len(valid) - 5]),
        ("truncated-inside-payload-length-repaired", own,
         repair_length(valid[:len(valid) - 5])),
        ("stray-bytes-short-of-alignment", own,
         repair_length(encode_glb3([(JSON_CHUNK, minimal)]) + bytes(2))),
        ("header-only-no-chunks", own, MAGIC + struct.pack("<IQ", 3, 16)),
        ("bin-only-no-json-chunk", own, encode_glb3([(BIN_CHUNK, TRIANGLE_BIN)])),
        ("chunk-encoding-nonzero-is-never-decoded", own,
         encode_glb3([(JSON_CHUNK, minimal), (BIN_CHUNK, GZIP_SIGNATURE_BLOB, 1)])),
        ("gzip-signature-instead-of-glb", own, GZIP_SIGNATURE_BLOB),
        ("zip-signature-instead-of-glb", own, b"PK\x03\x04" + bytes(26)),
        ("json-utf8-bom", own, with_json(b"\xef\xbb\xbf" + minimal)),
        ("json-invalid-utf8-overlong", own,
         with_json(b'{"asset":{"version":"2.1","generator":"\xc0\xaf"}}')),
        ("json-nan-constant", own,
         with_json(b'{"asset":{"version":"2.1"},"extras":NaN}')),
        ("json-float-overflow", own,
         with_json(b'{"asset":{"version":"2.1"},"extras":1e999}')),
        ("json-duplicate-key", own,
         with_json(b'{"asset":{"version":"2.1"},"asset":{"version":"2.1"}}')),
        ("json-depth-bomb", own, with_json(_depth_bomb())),
        ("json-lone-surrogate-escape", own,
         with_json(b'{"asset":{"version":"2.1","generator":"\\ud800"}}')),
        ("json-trailing-nul-padding-inside-chunk", own, with_json(minimal + b"\x00")),
        ("asset-version-2-2-unknown-minor", own,
         with_json(b'{"asset":{"version":"2.2"}}')),
        ("asset-min-version-above-version", own,
         with_json(b'{"asset":{"version":"2.0","minVersion":"2.1"}}')),
        ("bufferview-out-of-bounds", own, with_document(out_of_bounds)),
        ("buffer-larger-than-chunk", own, with_document(too_small)),
        ("buffer-chunk-index-missing", own,
         with_document(triangle_document("2.1", chunk=9))),
        ("buffer-chunk-and-uri-ambiguous", own,
         with_document(triangle_document("2.1", chunk=1, uri="a.bin"))),
        ("file-references-main-json-chunk", own, with_json(compact(main_json_file))),
        ("external-reference-budget", own, with_json(compact(many))),
        ("data-uri-over-budget", own, with_json(compact({
            "asset": {"version": "2.1"},
            "images": [{"uri": "data:application/octet-stream;base64,"
                        + "A" * MAX_DATA_URI_CHARS}]}))),
    ]


class SplitMix64:
    """Tiny explicit PRNG so the corpus is identical on every Python and platform."""

    def __init__(self, seed: int):
        self.state = seed & MASK64

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
        return value ^ (value >> 31)

    def below(self, bound: int) -> int:
        return self.next() % bound


_EDGE_32 = (0, 1, 2, 3, 4, 7, 8, 16, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF,
            JSON_CHUNK, BIN_CHUNK, 0x03000000)
_EDGE_64 = (0, 1, 7, 8, 16, 0xFFFFFFFF, 1 << 32, (1 << 63) - 1, 1 << 63,
            MASK64, MASK64 - 15, MASK64 - 31)


def _mutate(data: bytearray, rng: SplitMix64, seeds: list) -> None:
    operation = rng.below(12)
    size = len(data)
    if operation == 0 and size:
        data[rng.below(size)] ^= 1 << rng.below(8)
    elif operation == 1 and size:
        data[rng.below(size)] = rng.below(256)
    elif operation == 2 and size:
        del data[rng.below(size):]
    elif operation == 3:
        data.extend(rng.below(256) for _ in range(1 + rng.below(24)))
    elif operation == 4 and size >= 4:
        offset = 4 * rng.below(size // 4)
        struct.pack_into("<I", data, offset, _EDGE_32[rng.below(len(_EDGE_32))])
    elif operation == 5 and size >= 8:
        offset = 8 * rng.below(size // 8)
        edges = _EDGE_64 + (size, size - 1, size + 1, size - 16, (1 << 32) + size)
        struct.pack_into("<Q", data, offset, edges[rng.below(len(edges))] & MASK64)
    elif operation == 6 and size >= 16:
        struct.pack_into("<Q", data, 8, size)
    elif operation == 7 and size >= 4:
        offset = 4 * rng.below(size // 4)
        data[offset:offset + 4] = data[offset:offset + 4][::-1]
    elif operation == 8 and size >= 8:
        offset = 8 * rng.below(size // 8)
        data[offset:offset + 8] = data[offset:offset + 8][::-1]
    elif operation == 9:
        other = seeds[rng.below(len(seeds))]
        data[rng.below(size + 1):] = other[rng.below(len(other) + 1):]
    elif operation == 10 and size:
        start = rng.below(size)
        stop = start + 1 + rng.below(min(32, size - start))
        data[start:start] = data[start:stop]
    elif operation == 11 and size:
        start = rng.below(size)
        stop = start + 1 + rng.below(min(32, size - start))
        data[start:stop] = bytes(stop - start)


def framing_corpus(seed: int = FRAMING_SEED, cases: int = FRAMING_CASES) -> list:
    """Seeded byte-level mutations of every accepted vector (framing stage)."""
    return list(_framing_corpus(seed, cases))


@functools.lru_cache(maxsize=2)
def _framing_corpus(seed: int, cases: int) -> tuple:
    seeds = [data for _name, _origin, data in accepted_vectors()]
    assert all(len(data) <= 4096 for data in seeds)
    rng = SplitMix64(seed)
    corpus = list(seeds)
    while len(corpus) < cases:
        data = bytearray(seeds[rng.below(len(seeds))])
        for _ in range(1 + rng.below(3)):
            _mutate(data, rng, seeds)
        if rng.below(4) == 0 and len(data) >= 16:
            struct.pack_into("<Q", data, 8, len(data))
        corpus.append(bytes(data))
    return tuple(corpus)


def bundle(corpus: list) -> bytes:
    """Container handed to the native probe in a single process."""
    return (BUNDLE_MAGIC + struct.pack("<I", len(corpus))
            + b"".join(struct.pack("<I", len(case)) + case for case in corpus))


_HOSTILE = (None, True, False, -1, 0, 1, 7, 2 ** 53, 2 ** 53 + 1, 1.5, "", "x",
            "../../secret", "data:,x", [], {}, [[]], {"chunk": 0}, 10 ** 18)


def _mutate_document(document, rng: SplitMix64):
    """Replace, delete or duplicate one randomly chosen node (structure-aware)."""
    node, parent, key = document, None, None
    for _ in range(1 + rng.below(5)):
        if isinstance(node, dict) and node:
            parent, key = node, sorted(node)[rng.below(len(node))]
        elif isinstance(node, list) and node:
            parent, key = node, rng.below(len(node))
        else:
            break
        node = parent[key]
    if parent is None:
        return document
    action = rng.below(8)
    if action == 0:
        del parent[key]
    elif action == 1 and isinstance(parent, list):
        parent.append(parent[key])
    elif action == 2 and isinstance(node, int) and not isinstance(node, bool):
        parent[key] = node + (-1, 1, 2 ** 31, 2 ** 53)[rng.below(4)]
    else:
        # Fresh copy: a shared list or dict would leak state between cases.
        parent[key] = copy.deepcopy(_HOSTILE[rng.below(len(_HOSTILE))])
    return document


def json_corpus(seed: int = JSON_SEED, cases: int = JSON_CASES) -> list:
    """Valid framing around structurally or textually corrupted glTF JSON."""
    return list(_json_corpus(seed, cases))


@functools.lru_cache(maxsize=2)
def _json_corpus(seed: int, cases: int) -> tuple:
    templates = [([(JSON_CHUNK, None), (BIN_CHUNK, TRIANGLE_BIN)], triangle_document()),
                 ([(CUSTOM_CHUNK, b"producer-private"), (JSON_CHUNK, None),
                   (BIN_CHUNK, TRIANGLE_BIN)], triangle_document("2.1", chunk=2)),
                 ([(JSON_CHUNK, None)] + complex_chunks()[1:], complex_document())]
    rng = SplitMix64(seed)
    corpus = []
    while len(corpus) < cases:
        chunks, template = templates[rng.below(len(templates))]
        document = json.loads(json.dumps(template))
        for _ in range(1 + rng.below(3)):
            document = _mutate_document(document, rng)
        text = bytearray(compact(document))
        if rng.below(3) == 0 and text:
            for _ in range(1 + rng.below(3)):
                text[rng.below(len(text))] = rng.below(256)
        corpus.append(encode_glb3([(kind, bytes(text) if payload is None else payload)
                                   for kind, payload in chunks]))
    return tuple(corpus)


def full_verdict(data: bytes) -> str:
    """``A <receipt sha256>`` or ``R <CODE>`` for the complete inspection."""
    try:
        return "A " + receipt_digest(inspect_glb3_sandbox(data, contract=CONTRACT))
    except SandboxRejection as rejection:
        return "R " + rejection.code


def _summary(lines: list) -> dict:
    codes = {}
    for line in lines:
        if line.startswith("R "):
            codes[line[2:]] = codes.get(line[2:], 0) + 1
    return {"cases": len(lines), "accepted": sum(line.startswith("A ") for line in lines),
            "rejected": sum(codes.values()), "codes": dict(sorted(codes.items())),
            "verdicts_sha256": hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()}


def evidence_digest(document: dict) -> str:
    raw = json.dumps({k: v for k, v in document.items() if k != "sha256"},
                     sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_evidence() -> dict:
    """Recompute every pinned decode receipt from the vectors above."""
    vectors = []
    for expected, group in (("accepted", accepted_vectors()),
                            ("rejected", rejected_vectors())):
        for name, origin, data in group:
            record = {"name": name, "origin": origin, "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "framing": frame_verdict(data, contract=CONTRACT)}
            try:
                receipt = inspect_glb3_sandbox(data, contract=CONTRACT)
            except SandboxRejection as rejection:
                record.update(verdict="rejected", code=rejection.code)
            else:
                record.update(verdict="accepted",
                              receipt_sha256=receipt_digest(receipt),
                              draft_features_observed=receipt["draft_features_observed"])
            assert record["verdict"] == expected, name
            vectors.append(record)
    framing = framing_corpus()
    full = json_corpus()
    document = {
        "protocol": EVIDENCE_PROTOCOL, "contract": CONTRACT,
        "specification": dict(SPEC_BASIS),
        "authority": "generated-in-process-test-vectors",
        "claims": {"ratified": False, "khronos_conformance": "not_claimed",
                   "interoperability": "not_established",
                   "runtime_admission": "refused", "performance": "not_measured"},
        "vectors": vectors,
        "fuzz": {
            "framing": dict(seed=FRAMING_SEED,
                            corpus_sha256=hashlib.sha256(bundle(framing)).hexdigest(),
                            **_summary([frame_verdict(case, contract=CONTRACT)
                                        for case in framing])),
            "json": dict(seed=JSON_SEED,
                         corpus_sha256=hashlib.sha256(bundle(full)).hexdigest(),
                         **_summary([full_verdict(case) for case in full])),
        },
    }
    document["sha256"] = evidence_digest(document)
    return document


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true",
                        help="rewrite the pinned evidence file")
    args = parser.parse_args(argv)
    text = json.dumps(build_evidence(), sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.write:
        EVIDENCE.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
