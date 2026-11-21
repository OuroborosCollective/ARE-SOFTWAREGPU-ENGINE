"""Opt-in, read-only inspection sandbox for the UNRATIFIED glTF 2.1 / GLB v3 draft.

Status basis (read against Khronos primary sources on 2026-11-20, recorded in
``evidence/gltf21-glb3-khronos-status-20261120.json``): the Khronos registry
still names glTF 2.0 as the current version, ``specification/2.1`` exists only
on the ``draft-2.1`` working branch and the glTF 2.1 tracking issue is open.
"GLB version 3" is therefore a working draft whose byte layout may still
change. This module does NOT claim ratification, conformance or
interoperability.

Scope: bounded framing and JSON structure inspection of in-memory bytes behind
an explicit, versioned contract string. It is deliberately disjoint from the
GLB 2.0 path (``tools.glb_container_preflight``): it neither imports nor
replaces it, and it refuses GLB version 2 input. It never decompresses,
decodes images or extension payloads, opens files, resolves URIs or admits an
asset to a renderer. A receipt is diagnostic evidence only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct

CONTRACT = "are.gltf21-glb3-sandbox.v1"
RECEIPT_PROTOCOL = "are.gltf21-glb3-sandbox-receipt.v1"

# Exactly what was read; a later draft or a ratified text needs a new contract.
SPEC_BASIS = {
    "verified_on": "2026-11-20",
    "ratified": False,
    "gltf_2_1": "unratified-working-draft",
    "glb_container_v3": "unratified-working-draft",
    "khronos_registry_current_version": "2.0",
    "draft_repository": "KhronosGroup/glTF",
    "draft_branch": "draft-2.1",
    "draft_commit": "c330f9e5a324c9858145be183d2a1e63718fd3e8",
    "draft_path": "specification/2.1/Specification.adoc",
    "draft_sha256": "83e76b6eb2cdd33a2b525948fcb3929dbcbf10b9554e8027c736d2de84ebecd1",
    "extension_registry_commit": "5b00b913b74c8f0260c64578b98a09ef2dde0b41",
    "extension_registry_sha256": "32868b162d85305f633cbb78747abfddda8ebbf9c51f4bf4456cafc2af54952d",
}

MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
FILE_HEADER_BYTES = 16
CHUNK_HEADER_BYTES = 16

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_CHUNKS = 64
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 64
# Upper bounds on the characters '[', '{' and ',' and on '"' in the JSON chunk.
# They bound the number of values and strings conservatively: characters inside
# string literals are counted as well.
MAX_JSON_VALUES = 524_288
MAX_JSON_QUOTES = 4 * MAX_JSON_VALUES
MAX_INTEGER_DIGITS = 20  # 2**64 - 1, the largest uint64 accessor bound
MAX_SAFE_INTEGER = 2 ** 53
MAX_URI_CHARS = 2048
MAX_EXTERNAL_REFERENCES = 256
MAX_DATA_URI_CHARS = 1024 * 1024
MAX_EXTENSION_NAMES = 256
MAX_EXTENSION_NAME_CHARS = 128
MAX_MEDIA_TYPE_CHARS = 255

LIMITS = {
    "source_bytes": MAX_SOURCE_BYTES, "chunks": MAX_CHUNKS,
    "json_bytes": MAX_JSON_BYTES, "json_depth": MAX_JSON_DEPTH,
    "json_structural_characters": MAX_JSON_VALUES,
    "json_quote_characters": MAX_JSON_QUOTES, "integer_digits": MAX_INTEGER_DIGITS,
    "uri_chars": MAX_URI_CHARS, "external_references": MAX_EXTERNAL_REFERENCES,
    "data_uri_chars": MAX_DATA_URI_CHARS, "extension_names": MAX_EXTENSION_NAMES,
    "extension_name_chars": MAX_EXTENSION_NAME_CHARS,
    "media_type_chars": MAX_MEDIA_TYPE_CHARS, "integer_value": MAX_SAFE_INTEGER,
}

# Leading bytes of common compressed containers. They are refused, never inflated.
_COMPRESSED_SIGNATURES = (b"\x1f\x8b", b"\x28\xb5\x2f\xfd", b"\xfd7zXZ\x00",
                          b"BZh", b"PK\x03\x04")
_BYTE_SWAPPED_VERSIONS = (0x02000000, 0x03000000)

# "Ratified Khronos Extensions" exactly as listed in extensions/README.md at
# SPEC_BASIS["extension_registry_commit"]; anything else stays "unverified".
RATIFIED_EXTENSIONS_2_0 = frozenset((
    "KHR_animation_pointer", "KHR_draco_mesh_compression", "KHR_gaussian_splatting",
    "KHR_interactivity", "KHR_lights_punctual", "KHR_materials_anisotropy",
    "KHR_materials_clearcoat", "KHR_materials_dispersion",
    "KHR_materials_emissive_strength", "KHR_materials_ior",
    "KHR_materials_iridescence", "KHR_materials_sheen", "KHR_materials_specular",
    "KHR_materials_transmission", "KHR_materials_unlit", "KHR_materials_variants",
    "KHR_materials_volume", "KHR_mesh_quantization", "KHR_node_hoverability",
    "KHR_node_selectability", "KHR_node_visibility", "KHR_texture_basisu",
    "KHR_texture_transform", "KHR_xmp_json_ld", "EXT_mesh_gpu_instancing",
    "EXT_meshopt_compression", "EXT_texture_webp",
))
# Announced as required functionality of the 2.1 draft; syntax not final.
PROMOTED_IN_2_1_DRAFT = frozenset((
    "EXT_texture_webp", "KHR_materials_emissive_strength",
    "KHR_mesh_quantization", "KHR_node_visibility",
))

_COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_DRAFT_COMPONENT_BYTES = {5124: 4, 5130: 8, 5131: 2, 5134: 8, 5135: 8}
_TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
                    "MAT2": 4, "MAT3": 9, "MAT4": 16}
_VERSION = re.compile(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\Z")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_IRI_EDGE = "".join(map(chr, range(0x21)))  # U+0000..U+0020
_ENCODED_PATH_CHARACTER = re.compile(r"%(2[eEfF]|5[cC])")  # ".", "/" and "\\"
# Linear time and constant memory: a string always ends at its closing quote or
# at the end of input (no rescans), and the possessive quantifiers (Python >=
# 3.11) keep no backtracking state. The plain ``(?:..|..)*`` form needed about
# 585 MB for one 4 MiB string.
_JSON_TOKEN = re.compile(rb'"(?:[^"\\]++|\\.)*+(?:"|\\?\Z)|[\[\]{}]', re.DOTALL)
_EXTERNAL_ASSET_MEDIA_TYPES = ("model/gltf-binary", "model/gltf+json")


class SandboxRejection(ValueError):
    """Fail-closed refusal; ``code`` is a stable machine-readable reason."""

    def __init__(self, code: str):
        super().__init__("GLB3_SANDBOX_" + code)
        self.code = code

    def __reduce__(self):
        # Rebuild from the code: the default would apply the prefix a second time.
        return (type(self), (self.code,))


def _need(condition, code: str) -> None:
    if not condition:
        raise SandboxRejection(code)


def _u32(view, offset: int) -> int:
    return struct.unpack_from("<I", view, offset)[0]


def _u64(view, offset: int) -> int:
    return struct.unpack_from("<Q", view, offset)[0]


def _view(data):
    _need(type(data) in (bytes, bytearray, memoryview), "SOURCE_TYPE")
    try:
        view = memoryview(data)
        _need(view.ndim == 1 and view.itemsize == 1 and view.c_contiguous, "SOURCE_TYPE")
        view = view.cast("B")
    except (TypeError, ValueError):  # e.g. a memoryview that was already released
        raise SandboxRejection("SOURCE_TYPE") from None
    _need(len(view) <= MAX_SOURCE_BYTES, "SOURCE_BUDGET")
    return view


def _frame(view) -> dict:
    """Draft GLB v3 framing. Check order is mirrored by the native C++ probe."""
    size = len(view)
    head = bytes(view[:8])
    _need(not any(head.startswith(sig) for sig in _COMPRESSED_SIGNATURES),
          "COMPRESSED_INPUT_REFUSED")
    _need(size >= 4, "HEADER_TRUNCATED")
    _need(head[:4] == MAGIC, "MAGIC")
    _need(size >= 8, "HEADER_TRUNCATED")
    version = _u32(view, 4)
    _need(version != 2, "VERSION_2_OUT_OF_SCOPE")
    _need(version not in _BYTE_SWAPPED_VERSIONS, "BIG_ENDIAN_REFUSED")
    _need(version == 3, "VERSION_UNSUPPORTED")
    _need(size >= FILE_HEADER_BYTES, "HEADER_TRUNCATED")
    declared = _u64(view, 8)
    _need(declared >> 63 == 0, "LENGTH_MSB")
    _need(declared == size, "LENGTH_MISMATCH")
    chunks = []
    nonzero_padding = trailing_padding = 0
    position = FILE_HEADER_BYTES
    while position < size:
        _need(size - position >= CHUNK_HEADER_BYTES, "CHUNK_HEADER_TRUNCATED")
        kind = _u32(view, position)
        encoding = _u32(view, position + 4)
        length = _u64(view, position + 8)
        _need(length >> 63 == 0, "CHUNK_LENGTH_MSB")
        payload = position + CHUNK_HEADER_BYTES
        # Compare against the remainder; never add an untrusted 64-bit length.
        _need(length <= size - payload, "CHUNK_LENGTH_OVERFLOW")
        _need(len(chunks) < MAX_CHUNKS, "CHUNK_BUDGET")
        # The draft defines encoding 0 only; nothing is ever decoded here.
        _need(encoding == 0, "CHUNK_ENCODING_REFUSED")
        chunks.append({"type": kind, "encoding": encoding,
                       "offset": payload, "length": length})
        end = payload + length
        if end == size:
            break
        following = end + (-end % 8)
        _need(following <= size, "TRAILING_BYTES")
        nonzero_padding += sum(1 for value in view[end:following] if value)
        if following == size:
            trailing_padding = following - end
        position = following
    _need(chunks, "NO_CHUNKS")
    main = next((i for i, c in enumerate(chunks) if c["type"] == JSON_CHUNK), None)
    _need(main is not None, "JSON_CHUNK_MISSING")
    json_chunk = chunks[main]
    _need(json_chunk["length"] <= MAX_JSON_BYTES, "JSON_BUDGET")
    raw = view[json_chunk["offset"]:json_chunk["offset"] + json_chunk["length"]]
    _need(bytes(raw[:3]) != b"\xef\xbb\xbf", "JSON_BOM")
    try:
        text = str(raw, "utf-8")
    except UnicodeDecodeError:
        raise SandboxRejection("JSON_UTF8") from None
    canonical = ("glb3;chunks=%d;main_json=%d;pad_nonzero=%d;trailing_pad=%d"
                 % (len(chunks), main, nonzero_padding, trailing_padding)
                 + "".join(";%08x:%d:%d:%d" % (c["type"], c["encoding"],
                                               c["offset"], c["length"])
                           for c in chunks))
    return {"size": size, "chunks": chunks, "main_json": main,
            "nonzero_padding_bytes": nonzero_padding,
            "trailing_padding_bytes": trailing_padding,
            "canonical": canonical, "json_text": text, "json_raw": raw}


def frame_verdict(data, *, contract: str) -> str:
    """``A <canonical framing>`` or ``R <CODE>``; compared with the native probe."""
    _need(type(contract) is str and contract == CONTRACT, "OPT_IN_REQUIRED")
    try:
        return "A " + _frame(_view(data))["canonical"]
    except SandboxRejection as rejection:
        return "R " + rejection.code


def _json_budget(raw) -> None:
    """Bound values and nesting before the JSON parser allocates or recurses."""
    data = bytes(raw)
    # Conservative upper bounds (characters inside strings count as well); they
    # also cap the number of tokens the depth scan below has to visit.
    structural = data.count(b"[") + data.count(b"{") + data.count(b",") + 1
    _need(structural <= MAX_JSON_VALUES and data.count(b'"') <= MAX_JSON_QUOTES,
          "JSON_VALUE_BUDGET")
    depth = 0
    for match in _JSON_TOKEN.finditer(data):
        first = data[match.start()]
        if first in (0x5B, 0x7B):
            depth += 1
            _need(depth <= MAX_JSON_DEPTH, "JSON_DEPTH")
        elif first in (0x5D, 0x7D):
            depth -= 1


def _reject_constant(_name):
    raise SandboxRejection("JSON_NONFINITE")


def _finite_float(text):
    value = float(text)
    _need(math.isfinite(value), "JSON_NONFINITE")
    # The draft lets integer properties be written as 100.0 or 1e2; a non-zero
    # fraction stays a float and is refused wherever an integer is required.
    if value.is_integer() and abs(value) <= MAX_SAFE_INTEGER:
        return int(value)
    return value


def _bounded_int(text):
    _need(len(text.lstrip("-")) <= MAX_INTEGER_DIGITS, "JSON_NUMBER_RANGE")
    return int(text)


def _unique_object(pairs):
    result = dict(pairs)
    _need(len(result) == len(pairs), "JSON_DUPLICATE_KEY")
    return result


def _parse_json(text: str, raw) -> dict:
    _json_budget(raw)
    try:
        document = json.loads(text, parse_constant=_reject_constant,
                              parse_float=_finite_float, parse_int=_bounded_int,
                              object_pairs_hook=_unique_object)
    except SandboxRejection:
        raise
    except RecursionError:
        raise SandboxRejection("JSON_DEPTH") from None
    except ValueError:
        raise SandboxRejection("JSON_SYNTAX") from None
    _need(isinstance(document, dict), "JSON_ROOT")
    pending = [document]
    while pending:  # Iterative: no recursion on untrusted nesting.
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise SandboxRejection("JSON_LONE_SURROGATE") from None
    return document


def _index(value, limit: int) -> bool:
    return type(value) is int and 0 <= value < limit


def _size(value, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= MAX_SAFE_INTEGER


def _objects(document: dict, name: str, code: str) -> list:
    value = document.get(name, [])
    _need(isinstance(value, list) and all(isinstance(v, dict) for v in value), code)
    return value


class _Externals:
    """Counts references. The resolution budget is zero: nothing is ever opened."""

    def __init__(self):
        self.external = self.data_chars = self.traversal = self.absolute = 0

    def classify(self, uri) -> str:
        _need(isinstance(uri, str), "URI_TYPE")
        # Classify what a loader would resolve: the draft recommends stripping
        # edge whitespace/control characters and every TAB/LF/CR first, and a
        # loader may percent-decode dots and separators. Budgets use the raw text.
        cleaned = uri.strip(_IRI_EDGE).replace("\t", "").replace("\n", "").replace("\r", "")
        if cleaned[:5].lower() == "data:":
            self.data_chars += len(uri)
            _need(self.data_chars <= MAX_DATA_URI_CHARS, "DATA_URI_BUDGET")
            return "embedded_data_uri_not_decoded"
        _need(len(uri) <= MAX_URI_CHARS, "URI_BUDGET")
        self.count_reference()
        decoded = _ENCODED_PATH_CHARACTER.sub(lambda m: chr(int(m.group(1), 16)), cleaned)
        if ".." in re.split(r"[/\\]", decoded):
            self.traversal += 1
        if _SCHEME.match(cleaned) or decoded[:1] in ("/", "\\"):
            self.absolute += 1
        return "external_unresolved"

    def count_reference(self) -> None:
        self.external += 1
        _need(self.external <= MAX_EXTERNAL_REFERENCES, "EXTERNAL_REFERENCE_BUDGET")


def _asset(document: dict) -> tuple:
    asset = document.get("asset")
    _need(isinstance(asset, dict), "ASSET")
    version = asset.get("version")
    _need(isinstance(version, str) and _VERSION.match(version), "ASSET_VERSION")
    target = tuple(int(part) for part in version.split("."))
    # Pinned draft only: an unknown future minor is not silently accepted.
    _need(target in ((2, 0), (2, 1)), "ASSET_VERSION_UNSUPPORTED")
    minimum = asset.get("minVersion")
    if "minVersion" in asset:
        _need(isinstance(minimum, str) and _VERSION.match(minimum), "ASSET_MIN_VERSION")
        _need(tuple(int(part) for part in minimum.split(".")) <= target,
              "ASSET_MIN_VERSION")
    return asset, version, minimum


def _buffers(document, chunks, main_json, externals, features) -> tuple:
    buffers = _objects(document, "buffers", "BUFFERS")
    records = []
    for position, buffer in enumerate(buffers):
        length = buffer.get("byteLength")
        _need(_size(length, 1), "BUFFER_LENGTH")
        _need(not ("uri" in buffer and "chunk" in buffer), "BUFFER_SOURCE_AMBIGUOUS")
        if "chunk" in buffer:
            _need(_index(buffer["chunk"], len(chunks)), "BUFFER_CHUNK_MISSING")
            _need(chunks[buffer["chunk"]]["length"] >= length, "BUFFER_CHUNK_BOUNDS")
            features.add("buffer_chunk_reference")
            record = {"source": "glb_chunk", "chunk": buffer["chunk"]}
        elif "uri" in buffer:
            record = {"source": externals.classify(buffer["uri"])}
        elif position == 0:
            # glTF 2.0 compatible implicit BIN chunk directly after the JSON chunk.
            _need(main_json == 0 and len(chunks) >= 2
                  and chunks[1]["type"] == BIN_CHUNK, "BUFFER_IMPLICIT_BIN_MISSING")
            _need(chunks[1]["length"] >= length, "BUFFER_CHUNK_BOUNDS")
            record = {"source": "glb_chunk_implicit", "chunk": 1}
        else:
            record = {"source": "undefined_unresolved"}
        record["byte_length"] = length
        records.append(record)
    return buffers, records


def _buffer_views(document, buffers) -> list:
    views = _objects(document, "bufferViews", "BUFFERVIEWS")
    for view in views:
        _need(_index(view.get("buffer"), len(buffers)), "BUFFERVIEW_BUFFER")
        offset = view.get("byteOffset", 0)
        length = view.get("byteLength")
        _need(_size(offset) and _size(length, 1), "BUFFERVIEW_BOUNDS")
        _need(offset + length <= buffers[view["buffer"]]["byteLength"],
              "BUFFERVIEW_BOUNDS")
        if "byteStride" in view:
            stride = view["byteStride"]
            _need(type(stride) is int and 4 <= stride <= 252 and stride % 4 == 0
                  and stride <= length, "BUFFERVIEW_STRIDE")
    return views


def _element_bytes(kind: str, width: int) -> int:
    # Matrix columns are padded to four-byte boundaries (glTF data alignment).
    if kind == "MAT2" and width == 1:
        return 8
    if kind == "MAT3" and width in (1, 2):
        return 12 * width
    return _TYPE_COMPONENTS[kind] * width


def _accessors(document, views, features) -> tuple:
    accessors = _objects(document, "accessors", "ACCESSORS")
    sparse = 0
    for accessor in accessors:
        component = accessor.get("componentType")
        _need(type(component) is int and (component in _COMPONENT_BYTES
                                          or component in _DRAFT_COMPONENT_BYTES),
              "ACCESSOR_COMPONENT_TYPE")
        if component in _DRAFT_COMPONENT_BYTES:
            features.add("accessor_component_types_2_1")
        kind = accessor.get("type")
        _need(isinstance(kind, str) and kind in _TYPE_COMPONENTS, "ACCESSOR_TYPE")
        count = accessor.get("count")
        _need(_size(count, 1), "ACCESSOR_COUNT")
        sparse += "sparse" in accessor
        if "bufferView" not in accessor:
            # Without a buffer view there is nothing an offset could point into.
            _need("byteOffset" not in accessor, "ACCESSOR_BOUNDS")
            continue
        _need(_index(accessor["bufferView"], len(views)), "ACCESSOR_BUFFERVIEW")
        view = views[accessor["bufferView"]]
        offset = accessor.get("byteOffset", 0)
        _need(_size(offset), "ACCESSOR_BOUNDS")
        width = _COMPONENT_BYTES.get(component) or _DRAFT_COMPONENT_BYTES[component]
        element = _element_bytes(kind, width)
        stride = view.get("byteStride", element)
        # Both offsets and a defined stride are multiples of the component size.
        _need(offset % width == 0 and view.get("byteOffset", 0) % width == 0
              and stride % width == 0, "ACCESSOR_ALIGNMENT")
        _need(stride >= element and
              offset + (count - 1) * stride + element <= view["byteLength"],
              "ACCESSOR_BOUNDS")
    return accessors, sparse


def _images(document, views, externals) -> dict:
    states = {"embedded_image_not_decoded": 0, "embedded_data_uri_not_decoded": 0,
              "external_unresolved": 0}
    for image in _objects(document, "images", "IMAGES"):
        _need(not ("uri" in image and "bufferView" in image), "IMAGE_SOURCE_AMBIGUOUS")
        if "bufferView" in image:
            _need(_index(image["bufferView"], len(views)), "IMAGE_BUFFERVIEW")
            states["embedded_image_not_decoded"] += 1
        elif "uri" in image:
            states[externals.classify(image["uri"])] += 1
        else:
            raise SandboxRejection("IMAGE_SOURCE_MISSING")
    return states


def _files(document, buffers, views, main_json, externals, features) -> tuple:
    files = _objects(document, "files", "FILES")
    aliases = 0
    for entry in files:
        media = entry.get("mimeType")
        _need(isinstance(media, str) and 1 <= len(media) <= MAX_MEDIA_TYPE_CHARS,
              "FILE_MIMETYPE")
        _need(not ("uri" in entry and "bufferView" in entry), "FILE_SOURCE_AMBIGUOUS")
        if "bufferView" in entry:
            _need(_index(entry["bufferView"], len(views)), "FILE_BUFFERVIEW")
            buffer = buffers[views[entry["bufferView"]]["buffer"]]
            _need(buffer.get("chunk") != main_json, "FILE_REFERENCES_MAIN_JSON")
        elif "uri" in entry:
            externals.classify(entry["uri"])
        else:
            raise SandboxRejection("FILE_SOURCE_MISSING")
        listed = entry.get("aliases", [])
        _need(isinstance(listed, list), "FILE_ALIASES")
        for alias in listed:
            _need(isinstance(alias, dict) and isinstance(alias.get("alias"), str)
                  and len(alias["alias"]) <= MAX_URI_CHARS
                  and _index(alias.get("file"), len(files)), "FILE_ALIASES")
        aliases += len(listed)
    if files:
        features.add("files")
    externals_assets = _objects(document, "externalAssets", "EXTERNAL_ASSETS")
    for entry in externals_assets:
        _need(_index(entry.get("file"), len(files)), "EXTERNAL_ASSET_FILE")
        _need(files[entry["file"]]["mimeType"] in _EXTERNAL_ASSET_MEDIA_TYPES,
              "EXTERNAL_ASSET_MEDIA_TYPE")
        externals.count_reference()
    if externals_assets:
        features.add("external_assets")
    return len(files), aliases, len(externals_assets)


def _extensions(document) -> list:
    names = {}
    for key in ("extensionsUsed", "extensionsRequired"):
        value = document.get(key, [])
        _need(isinstance(value, list) and len(value) <= MAX_EXTENSION_NAMES
              and all(isinstance(v, str) and 1 <= len(v) <= MAX_EXTENSION_NAME_CHARS
                      for v in value)
              and len(set(value)) == len(value), "EXTENSIONS")
        names[key] = value
    _need(set(names["extensionsRequired"]) <= set(names["extensionsUsed"]),
          "EXTENSIONS_REQUIRED_NOT_USED")
    return [{"name": name,
             "registry_status": ("ratified_khronos_registry_2_0"
                                 if name in RATIFIED_EXTENSIONS_2_0 else "unverified"),
             "promoted_in_2_1_draft": name in PROMOTED_IN_2_1_DRAFT,
             "required": name in names["extensionsRequired"],
             "payload": "not_decoded"}
            for name in sorted(names["extensionsUsed"])]


def _chunk_records(view, frame: dict) -> list:
    records = []
    for position, chunk in enumerate(frame["chunks"]):
        payload = view[chunk["offset"]:chunk["offset"] + chunk["length"]]
        if position == frame["main_json"]:
            role, content = "main_json", "parsed_as_gltf_json"
        elif chunk["type"] == JSON_CHUNK:
            role, content = "additional_json", "opaque_not_decoded"
        elif chunk["type"] == BIN_CHUNK:
            role, content = "binary_buffer", "opaque_not_decoded"
        else:
            role, content = "unknown_type_ignored", "opaque_not_decoded"
        records.append({"index": position, "type": "0x%08x" % chunk["type"],
                        "encoding": chunk["encoding"], "offset": chunk["offset"],
                        "length": chunk["length"], "role": role, "content": content,
                        "sha256": hashlib.sha256(payload).hexdigest()})
    return records


def inspect_glb3_sandbox(data, *, contract: str) -> dict:
    """Return a diagnostic receipt for a draft GLB v3 asset or raise SandboxRejection.

    ``contract`` must equal :data:`CONTRACT`; there is no implicit default so a
    caller cannot reach the unratified path by accident.
    """
    _need(type(contract) is str and contract == CONTRACT, "OPT_IN_REQUIRED")
    try:
        return _inspect(data)
    except SandboxRejection as rejection:
        code = rejection.code
    # Raised from here, after the inner frames are gone: no memoryview of ``data``
    # survives, so a caller may resize its bytearray while handling the refusal.
    raise SandboxRejection(code)


def _inspect(data) -> dict:
    view = _view(data)
    frame = _frame(view)
    document = _parse_json(frame["json_text"], frame["json_raw"])
    chunks, main_json = frame["chunks"], frame["main_json"]
    features = {"glb_container_v3"}
    externals = _Externals()
    asset, version, minimum = _asset(document)
    if version == "2.1":
        features.add("asset_version_2_1")
    if "thumbnail" in asset:
        features.add("asset_thumbnail")
    buffers, buffer_records = _buffers(document, chunks, main_json, externals, features)
    views = _buffer_views(document, buffers)
    accessors, sparse = _accessors(document, views, features)
    images = _images(document, views, externals)
    file_count, alias_count, external_assets = _files(
        document, buffers, views, main_json, externals, features)
    extensions = _extensions(document)
    kinds = [chunk["type"] for chunk in chunks]
    if main_json != 0:
        features.add("chunk_before_main_json")
    if kinds.count(JSON_CHUNK) > 1:
        features.add("multiple_json_chunks")
    if kinds.count(BIN_CHUNK) > 1:
        features.add("multiple_binary_chunks")
    if any(kind not in (JSON_CHUNK, BIN_CHUNK) for kind in kinds):
        features.add("unknown_chunk_types")
    for name in ("shapes", "scenes"):
        _need(isinstance(document.get(name, []), list), "ARRAYS")
    if document.get("shapes"):
        features.add("shapes")
    return {
        "protocol": RECEIPT_PROTOCOL,
        "contract": CONTRACT,
        "authority": "offline-derived",
        "runtime_admission": "refused",
        "verdict": "not_assessed",
        "specification": dict(SPEC_BASIS),
        "source": {"bytes": frame["size"], "sha256": hashlib.sha256(view).hexdigest()},
        "container": {
            "version": 3, "main_json_chunk": main_json,
            "nonzero_padding_bytes": frame["nonzero_padding_bytes"],
            "trailing_padding_bytes": frame["trailing_padding_bytes"],
            "framing": frame["canonical"],
            "chunks": _chunk_records(view, frame),
        },
        "gltf": {
            "asset_version": version, "asset_min_version": minimum,
            "buffers": buffer_records, "buffer_views_checked": len(views),
            "accessors_checked": len(accessors),
            "sparse_accessors_not_checked": sparse,
            "images": images, "files": file_count, "file_aliases": alias_count,
            "external_assets": external_assets,
            "external_asset_cycles": "not_evaluated",
            "scenes": len(document.get("scenes", [])),
            "extensions": extensions,
        },
        "draft_features_observed": sorted(features),
        "external_resolution": {
            "policy": "never", "resolved": 0,
            "external_references": externals.external,
            "absolute_or_scheme_references": externals.absolute,
            "parent_traversal_references": externals.traversal,
            "data_uri_chars_not_decoded": externals.data_chars,
        },
        "decoding": {"chunk_encoding": "plain_only", "decompression": "not_executed",
                     "images": "not_decoded", "extension_payloads": "not_decoded"},
        "limits": dict(LIMITS),
    }


def receipt_digest(receipt: dict) -> str:
    """Canonical SHA-256 of a receipt (sorted keys, compact separators)."""
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("glb", type=Path, help="local file; never uploaded or modified")
    parser.add_argument("--contract", required=True,
                        help="must be exactly " + CONTRACT + " (explicit opt-in)")
    parser.add_argument("--output", default="-",
                        help="new file for the receipt; an existing path is refused")
    args = parser.parse_args(argv)
    try:
        _need(args.contract == CONTRACT, "OPT_IN_REQUIRED")
        _need(not args.glb.is_symlink(), "SOURCE_SYMLINK")
        args.glb.stat()  # a missing path raises here
        # Devices, pipes and directories report size 0 but can be endless.
        _need(args.glb.is_file(), "SOURCE_NOT_REGULAR_FILE")
        with args.glb.open("rb") as source:
            raw = source.read(MAX_SOURCE_BYTES + 1)
        _need(len(raw) <= MAX_SOURCE_BYTES, "SOURCE_BUDGET")
        receipt = inspect_glb3_sandbox(raw, contract=args.contract)
    except (ValueError, OSError) as error:
        code = error.code if isinstance(error, SandboxRejection) else "SOURCE_UNREADABLE"
        parser.exit(2, "GLB3_SANDBOX_REJECTED:" + code + "\n")
    output = json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output == "-":
        print(output, end="")
        return 0
    destination = Path(args.output)
    try:
        # Any existing name is refused, also a directory or a dangling symlink
        # (Windows reports those differently, or would write through the link).
        if destination.is_symlink() or destination.exists():
            raise FileExistsError(args.output)
        # Exclusive creation is the guarantee: an existing path is never truncated
        # or replaced -- not the inspected source, not a hard link to it, nothing.
        with destination.open("x", encoding="utf-8", newline="\n") as target:
            target.write(output)
    except FileExistsError:
        parser.exit(2, "GLB3_SANDBOX_REJECTED:OUTPUT_EXISTS\n")
    except OSError:
        parser.exit(2, "GLB3_SANDBOX_REJECTED:OUTPUT_UNWRITABLE\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
