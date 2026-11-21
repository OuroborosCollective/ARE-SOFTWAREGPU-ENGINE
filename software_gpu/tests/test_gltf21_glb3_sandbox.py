"""Contract, negative and receipt tests for the opt-in glTF 2.1 / GLB v3 DRAFT sandbox.

Real bytes go through the real parser; nothing is mocked. The draft is not
ratified, so these tests pin fail-closed inspection behaviour only. They are not
conformance, renderer-admission or performance evidence.
"""
import ast
import base64
import hashlib
import inspect
import json
import os
from pathlib import Path
import pickle
import re
import struct
import subprocess
import sys
import tempfile
import tracemalloc
import unittest

from software_gpu.tests.fixtures import glb3_draft_vectors as vectors
from software_gpu.tests.test_glb_container_preflight import glb as glb2
from software_gpu.tests.test_glb_diagnostic_evidence import QUAD, make_glb
from tools import gltf21_glb3_sandbox as sandbox
from tools.glb_container_preflight import inspect_glb
from tools.gltf21_glb3_sandbox import (
    CONTRACT,
    SandboxRejection,
    frame_verdict,
    inspect_glb3_sandbox,
    receipt_digest,
)

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "evidence/gltf21-glb3-khronos-status-20261120.json"
DOCUMENT = ROOT / "docs/GLTF21_GLB3_SANDBOX_20261120.md"
MINIMAL = b'{"asset":{"version":"2.1"}}'
# LF-normalised SHA-256 of the GLB 2.0 container parser as it is on main. This
# change must not touch it; a deliberate GLB2 change updates this pin itself.
GLB2_PREFLIGHT_SHA256 = "0f8c42e890a8ca145caeece00df8fae7ff116eacb302c0e88446e5e5f9f556b0"
GLB2_DECISIONS_SHA256 = "122927ab99d9be9d33c3ef0af9ee8c8582cf3efedd056ae03592a1cc5d5f9ad8"

EXPECTED_REJECTIONS = {
    "loaders-gl-a4faaba-4-byte-alignment-divergence": "CHUNK_LENGTH_OVERFLOW",
    "big-endian-file": "BIG_ENDIAN_REFUSED",
    "glb-version-2-container": "VERSION_2_OUT_OF_SCOPE",
    "glb-version-4-container": "VERSION_UNSUPPORTED",
    "declared-length-msb": "LENGTH_MSB",
    "declared-length-32-bit-truncation-trap": "LENGTH_MISMATCH",
    "chunk-length-msb-wraparound": "CHUNK_LENGTH_MSB",
    "chunk-length-32-bit-truncation-trap": "CHUNK_LENGTH_OVERFLOW",
    "chunk-length-beyond-file": "CHUNK_LENGTH_OVERFLOW",
    "truncated-inside-chunk-header": "LENGTH_MISMATCH",
    "truncated-inside-chunk-header-length-repaired": "CHUNK_HEADER_TRUNCATED",
    "truncated-inside-payload": "LENGTH_MISMATCH",
    "truncated-inside-payload-length-repaired": "CHUNK_LENGTH_OVERFLOW",
    "stray-bytes-short-of-alignment": "TRAILING_BYTES",
    "header-only-no-chunks": "NO_CHUNKS",
    "bin-only-no-json-chunk": "JSON_CHUNK_MISSING",
    "chunk-encoding-nonzero-is-never-decoded": "CHUNK_ENCODING_REFUSED",
    "gzip-signature-instead-of-glb": "COMPRESSED_INPUT_REFUSED",
    "zip-signature-instead-of-glb": "COMPRESSED_INPUT_REFUSED",
    "json-utf8-bom": "JSON_BOM",
    "json-invalid-utf8-overlong": "JSON_UTF8",
    "json-nan-constant": "JSON_NONFINITE",
    "json-float-overflow": "JSON_NONFINITE",
    "json-duplicate-key": "JSON_DUPLICATE_KEY",
    "json-depth-bomb": "JSON_DEPTH",
    "json-lone-surrogate-escape": "JSON_LONE_SURROGATE",
    "json-trailing-nul-padding-inside-chunk": "JSON_SYNTAX",
    "asset-version-2-2-unknown-minor": "ASSET_VERSION_UNSUPPORTED",
    "asset-min-version-above-version": "ASSET_MIN_VERSION",
    "bufferview-out-of-bounds": "BUFFERVIEW_BOUNDS",
    "buffer-larger-than-chunk": "BUFFER_CHUNK_BOUNDS",
    "buffer-chunk-index-missing": "BUFFER_CHUNK_MISSING",
    "buffer-chunk-and-uri-ambiguous": "BUFFER_SOURCE_AMBIGUOUS",
    "file-references-main-json-chunk": "FILE_REFERENCES_MAIN_JSON",
    "external-reference-budget": "EXTERNAL_REFERENCE_BUDGET",
    "data-uri-over-budget": "DATA_URI_BUDGET",
}

_AUDIT = {"armed": False, "events": []}
_WATCHED = ("open", "socket.", "urllib.", "subprocess.", "os.", "shutil.", "glob.",
            "pathlib.", "ctypes.", "http.")


def _audit_hook(event, arguments):
    if _AUDIT["armed"] and event.startswith(_WATCHED):
        _AUDIT["events"].append((event, repr(arguments)[:120]))


sys.addaudithook(_audit_hook)


def code_of(data, **kwargs):
    try:
        inspect_glb3_sandbox(data, contract=CONTRACT, **kwargs)
    except SandboxRejection as rejection:
        return rejection.code
    return "ACCEPTED"


def accepted(name):
    return next(data for found, _origin, data in vectors.accepted_vectors() if found == name)


def with_document(document, *chunks):
    return vectors.encode_glb3([(vectors.JSON_CHUNK, vectors.compact(document)), *chunks])


def normalised_sha256(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def glb2_decisions():
    """Frozen GLB 2.0 preflight behaviour over real GLB2 bytes and every v3 vector."""
    quad = make_glb(QUAD, [(0, 1, 2), (0, 2, 3)], [(0, 0), (1, 0), (1, 1), (0, 1)])
    cases = [
        ("quad", quad),
        ("json-only", glb2({"asset": {"version": "2.0"}})),
        ("embedded-buffer", glb2({"asset": {"version": "2.0"},
                                  "buffers": [{"byteLength": 1}]}, b"x")),
        ("morph-target", glb2({"asset": {"version": "2.0"},
                               "meshes": [{"primitives": [{"targets": [{}]}]}]})),
        ("wrong-asset-version", glb2({"asset": {"version": "2.1"}})),
        ("missing-bin", glb2({"asset": {"version": "2.0"},
                              "buffers": [{"byteLength": 5}]})),
        ("unreferenced-bin", glb2({"asset": {"version": "2.0"}}, b"data")),
        ("quad-truncated", quad[:-4]),
        ("quad-version-3-header", quad[:4] + struct.pack("<I", 3) + quad[8:]),
    ]
    cases += [("v3:" + name, data) for name, _origin, data in vectors.accepted_vectors()]
    lines = []
    for name, data in cases:
        try:
            lines.append(name + " " + json.dumps(inspect_glb(data), sort_keys=True))
        except ValueError as error:
            lines.append(name + " ValueError:" + str(error))
    return lines


class OptInContractTests(unittest.TestCase):
    def test_exact_contract_string_is_required_and_has_no_default(self):
        parameter = inspect.signature(inspect_glb3_sandbox).parameters["contract"]
        self.assertIs(parameter.default, inspect.Parameter.empty)
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        data = accepted("minimal-json-only")
        for wrong in (None, "", True, "are.gltf21-glb3-sandbox.v2", CONTRACT + " ",
                      CONTRACT.encode(), CONTRACT.upper()):
            with self.assertRaisesRegex(SandboxRejection, "OPT_IN_REQUIRED"):
                inspect_glb3_sandbox(data, contract=wrong)
            with self.assertRaisesRegex(SandboxRejection, "OPT_IN_REQUIRED"):
                frame_verdict(data, contract=wrong)
        with self.assertRaises(TypeError):
            inspect_glb3_sandbox(data)  # pylint: disable=missing-kwoa

    def test_only_byte_buffers_are_inspected_and_input_is_never_modified(self):
        data = bytearray(accepted("multi-chunk-files-external-assets"))
        frozen = bytes(data)
        receipts = [inspect_glb3_sandbox(candidate, contract=CONTRACT)
                    for candidate in (frozen, data, memoryview(data), memoryview(frozen))]
        self.assertEqual(bytes(data), frozen)
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        for wrong in ("glTF", None, 3, [103, 108], Path("asset.glb")):
            with self.assertRaisesRegex(SandboxRejection, "SOURCE_TYPE"):
                inspect_glb3_sandbox(wrong, contract=CONTRACT)
        released = memoryview(frozen)
        released.release()
        with self.assertRaisesRegex(SandboxRejection, "SOURCE_TYPE"):
            inspect_glb3_sandbox(released, contract=CONTRACT)
        self.assertEqual(frame_verdict(released, contract=CONTRACT), "R SOURCE_TYPE")

    def test_a_refusal_leaves_no_lock_on_the_callers_buffer(self):
        for hostile in (b"glTF\x03\x00\x00\x00junkjunkjunk",
                        vectors.rejected_vectors()[0][2],
                        with_document({"asset": {"version": "9.9"}})):
            buffer = bytearray(hostile)
            try:
                inspect_glb3_sandbox(buffer, contract=CONTRACT)
            except SandboxRejection as rejection:
                self.assertRegex(rejection.code, r"\A[A-Z0-9_]+\Z")
                buffer.clear()  # BufferError here if a view were still exported
            else:
                self.fail("hostile input was accepted")
            self.assertEqual(len(buffer), 0)
        good = bytearray(accepted("minimal-json-only"))
        inspect_glb3_sandbox(good, contract=CONTRACT)
        self.assertEqual(frame_verdict(good, contract=CONTRACT)[:2], "A ")
        good.extend(b"x")

    def test_rejection_keeps_code_and_message_through_pickle_and_copy(self):
        import copy
        try:
            inspect_glb3_sandbox(b"", contract=CONTRACT)
        except SandboxRejection as rejection:
            for clone in (pickle.loads(pickle.dumps(rejection)), copy.copy(rejection)):
                self.assertIs(type(clone), SandboxRejection)
                self.assertEqual(clone.code, "HEADER_TRUNCATED")
                self.assertEqual(str(clone), "GLB3_SANDBOX_HEADER_TRUNCATED")
                self.assertEqual(clone.args, rejection.args)

    def test_cli_needs_the_contract_and_writes_the_same_receipt(self):
        data = accepted("custom-chunk-before-json-explicit-bin")
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "draft.glb"
            source.write_bytes(data)
            base = [sys.executable, "-m", "tools.gltf21_glb3_sandbox", str(source)]
            missing = subprocess.run(base, cwd=ROOT, capture_output=True, text=True,
                                     timeout=60)
            self.assertEqual(missing.returncode, 2)
            self.assertIn("--contract", missing.stderr)
            wrong = subprocess.run(base + ["--contract", "yes"], cwd=ROOT,
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(wrong.returncode, 2)
            self.assertIn("GLB3_SANDBOX_REJECTED:OPT_IN_REQUIRED", wrong.stderr)
            self.assertEqual(wrong.stdout, "")
            good = subprocess.run(base + ["--contract", CONTRACT], cwd=ROOT,
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads(good.stdout),
                             inspect_glb3_sandbox(data, contract=CONTRACT))
            source.write_bytes(data[:40])
            broken = subprocess.run(base + ["--contract", CONTRACT], cwd=ROOT,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(broken.returncode, 2)
            self.assertIn("GLB3_SANDBOX_REJECTED:LENGTH_MISMATCH", broken.stderr)
            absent = subprocess.run(
                [sys.executable, "-m", "tools.gltf21_glb3_sandbox",
                 str(Path(folder) / "absent.glb"), "--contract", CONTRACT],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(absent.returncode, 2)
            self.assertIn("GLB3_SANDBOX_REJECTED:SOURCE_UNREADABLE", absent.stderr)


class CliReadOnlyTests(unittest.TestCase):
    """The CLI must never modify the inspected asset or any existing file."""

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "tools.gltf21_glb3_sandbox", *map(str, arguments),
             "--contract", CONTRACT], cwd=ROOT, capture_output=True, text=True, timeout=60)

    def test_output_can_never_overwrite_the_source_or_any_existing_file(self):
        data = accepted("custom-chunk-before-json-explicit-bin")
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "draft.glb"
            source.write_bytes(data)
            other = folder / "unrelated.txt"
            other.write_bytes(b"keep me")
            targets = {"the source itself": source, "an unrelated existing file": other,
                       "a directory": folder}
            hard = folder / "hardlink.glb"
            try:
                os.link(source, hard)
                targets["a hard link to the source"] = hard
            except (OSError, NotImplementedError):
                pass
            for name, target in (("a symlink to the source", source),
                                 ("a dangling symlink", folder / "nowhere")):
                link = folder / (name.replace(" ", "-") + ".lnk")
                try:
                    os.symlink(target, link)
                    targets[name] = link
                except (OSError, NotImplementedError):
                    pass  # unprivileged Windows cannot create symlinks
            self.assertGreaterEqual(len(targets), 3)
            for name, target in targets.items():
                result = self.run_cli(source, "--output", target)
                self.assertEqual(result.returncode, 2, name)
                self.assertIn("GLB3_SANDBOX_REJECTED:OUTPUT_EXISTS", result.stderr, name)
                self.assertEqual(source.read_bytes(), data, name)
                self.assertEqual(other.read_bytes(), b"keep me", name)
            self.assertFalse((folder / "nowhere").exists())
            fresh = folder / "receipt.json"
            written = self.run_cli(source, "--output", fresh)
            self.assertEqual(written.returncode, 0, written.stderr)
            self.assertEqual(json.loads(fresh.read_text(encoding="utf-8")),
                             inspect_glb3_sandbox(data, contract=CONTRACT))
            again = self.run_cli(source, "--output", fresh)
            self.assertEqual(again.returncode, 2)
            self.assertIn("GLB3_SANDBOX_REJECTED:OUTPUT_EXISTS", again.stderr)
            missing_parent = self.run_cli(source, "--output", folder / "no" / "dir" / "r.json")
            self.assertEqual(missing_parent.returncode, 2)
            self.assertIn("GLB3_SANDBOX_REJECTED:OUTPUT_UNWRITABLE", missing_parent.stderr)
            self.assertEqual(source.read_bytes(), data)

    def test_only_regular_files_are_read_and_never_beyond_the_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = self.run_cli(folder)
            self.assertEqual(directory.returncode, 2)
            self.assertIn("GLB3_SANDBOX_REJECTED:SOURCE_NOT_REGULAR_FILE", directory.stderr)
            large = Path(folder) / "large.glb"
            with large.open("wb") as handle:
                handle.truncate(sandbox.MAX_SOURCE_BYTES + 1)  # sparse, no real bytes
            over = self.run_cli(large)
            self.assertEqual(over.returncode, 2)
            self.assertIn("GLB3_SANDBOX_REJECTED:SOURCE_BUDGET", over.stderr)
        if os.path.exists("/dev/zero"):  # endless character device, size 0 in stat
            endless = self.run_cli("/dev/zero")
            self.assertEqual(endless.returncode, 2)
            self.assertIn("GLB3_SANDBOX_REJECTED:SOURCE_NOT_REGULAR_FILE", endless.stderr)


class RatificationClaimTests(unittest.TestCase):
    CLAIM = re.compile(r"(?i)(glb\s?v?3|gltf\s?2\.1|binary format version 3)[^.|\n]{0,80}"
                       r"\b(ist|is|wurde|was|sind|are)\s+(bereits\s+|already\s+|now\s+)?"
                       r"(ratifiziert|ratified|final(isiert)?|standardisiert)\b")

    def test_every_receipt_says_unratified_draft_and_refuses_runtime_admission(self):
        for _name, _origin, data in vectors.accepted_vectors():
            receipt = inspect_glb3_sandbox(data, contract=CONTRACT)
            basis = receipt["specification"]
            self.assertIs(basis["ratified"], False)
            self.assertEqual(basis["gltf_2_1"], "unratified-working-draft")
            self.assertEqual(basis["glb_container_v3"], "unratified-working-draft")
            self.assertEqual(basis["khronos_registry_current_version"], "2.0")
            self.assertEqual(receipt["runtime_admission"], "refused")
            self.assertEqual(receipt["verdict"], "not_assessed")
            self.assertEqual(receipt["authority"], "offline-derived")
            self.assertEqual(receipt["contract"], CONTRACT)

    def test_status_readback_names_primary_sources_and_matches_the_code(self):
        status = json.loads(STATUS.read_text(encoding="utf-8"))
        self.assertEqual(status["protocol"], "are.khronos-spec-status-readback.v1")
        self.assertEqual(status["sha256"], vectors.evidence_digest(status))
        self.assertEqual(status["basis"], sandbox.SPEC_BASIS)
        self.assertIs(status["conclusion"]["ratified"], False)
        self.assertIs(status["conclusion"]["released"], False)
        self.assertEqual(status["interoperability"]["status"], "not_established")
        hosts = {"registry.khronos.org", "www.khronos.org", "github.com"}
        self.assertGreaterEqual(len(status["sources"]), 6)
        for source in status["sources"]:
            self.assertEqual(source["read_on"], "2026-11-20")
            self.assertIn(source["url"].split("/")[2], hosts)
            self.assertTrue(source["observed"])
        self.assertRegex(sandbox.SPEC_BASIS["draft_commit"], r"\A[0-9a-f]{40}\Z")
        self.assertRegex(sandbox.SPEC_BASIS["draft_sha256"], r"\A[0-9a-f]{64}\Z")
        ratified = set(status["extension_registry"]["ratified_khronos_extensions"])
        self.assertEqual(ratified, set(sandbox.RATIFIED_EXTENSIONS_2_0))
        self.assertLessEqual(sandbox.PROMOTED_IN_2_1_DRAFT, ratified)

    def test_documents_state_the_draft_status_and_never_claim_ratification(self):
        self.assertTrue(self.CLAIM.search("GLB v3 ist bereits ratifiziert"))
        self.assertTrue(self.CLAIM.search("glTF 2.1 is ratified"))
        self.assertFalse(self.CLAIM.search("glTF 2.1 ist nicht ratifiziert"))
        texts = {path: path.read_text(encoding="utf-8") for path in (
            DOCUMENT, ROOT / "README.md", ROOT / "docs/CPU_WAVE_RANGLISTEN.md",
            ROOT / "docs/VISUAL_ASSET_LAB_20261119.md", STATUS, vectors.EVIDENCE,
            ROOT / "tools/gltf21_glb3_sandbox.py")}
        for path, text in texts.items():
            self.assertIsNone(self.CLAIM.search(text), path.name)
        self.assertIn("nicht ratifiziert", texts[DOCUMENT])
        self.assertIn("nicht ratifiziert", texts[ROOT / "README.md"])
        self.assertIn(CONTRACT, texts[DOCUMENT])
        evidence = json.loads(vectors.EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["claims"], {
            "ratified": False, "khronos_conformance": "not_claimed",
            "interoperability": "not_established", "runtime_admission": "refused",
            "performance": "not_measured"})


class Glb2DisjointnessTests(unittest.TestCase):
    def test_glb2_container_parser_source_is_byte_identical_to_main(self):
        self.assertEqual(normalised_sha256(ROOT / "tools/glb_container_preflight.py"),
                         GLB2_PREFLIGHT_SHA256)

    def test_glb2_preflight_decisions_are_frozen_and_reject_every_v3_vector(self):
        lines = glb2_decisions()
        for line in lines:
            if line.startswith("v3:"):
                self.assertTrue(line.endswith("ValueError:GLB version/length mismatch"),
                                line)
        self.assertIn('quad {"animations": 0, "bytes": 624, "meshes": 1, '
                      '"morph_targets": 0}', lines)
        self.assertIn("wrong-asset-version ValueError:not a glTF 2.0 asset", lines)
        self.assertEqual(
            hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
            GLB2_DECISIONS_SHA256)

    def test_sandbox_refuses_real_glb2_files_instead_of_parsing_them(self):
        quad = make_glb(QUAD, [(0, 1, 2), (0, 2, 3)])
        for data in (quad, glb2({"asset": {"version": "2.0"}}),
                     glb2({"asset": {"version": "2.0"},
                           "buffers": [{"byteLength": 1}]}, b"x")):
            inspect_glb(data)
            self.assertEqual(code_of(data), "VERSION_2_OUT_OF_SCOPE")
            self.assertEqual(frame_verdict(data, contract=CONTRACT),
                             "R VERSION_2_OUT_OF_SCOPE")

    def test_sandbox_imports_no_glb2_code_compression_network_or_filesystem_walkers(self):
        tree = ast.parse((ROOT / "tools/gltf21_glb3_sandbox.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"__future__", "argparse", "hashlib", "json", "math",
                                    "pathlib", "re", "struct"})
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertFalse(names & {"eval", "exec", "__import__", "open", "compile"})

    def test_no_default_runtime_or_native_renderer_path_reaches_the_sandbox(self):
        allowed = {ROOT / "tools/gltf21_glb3_sandbox.py",
                   ROOT / "tools/gltf21_glb3_independent_assets.py"}
        scanned = 0
        for folder, pattern in (("software_gpu", "*.py"), ("tools", "*.py"),
                                ("plugins", "*.py"), ("scripts", "*.py"),
                                ("native", "*.[ch]pp")):
            for path in sorted((ROOT / folder).rglob(pattern)):
                relative = path.relative_to(ROOT).as_posix()
                if (path in allowed or relative.startswith("software_gpu/tests/")
                        or relative.startswith("native/gltf/")):
                    continue
                scanned += 1
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("gltf21_glb3", text, relative)
                self.assertNotIn("glb3_container_probe", text, relative)
        self.assertGreater(scanned, 150)
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        setup = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertNotIn("glb3", main.lower())
        self.assertNotIn("glb3", setup.lower())


class EndiannessAndLengthTests(unittest.TestCase):
    def test_big_endian_and_mixed_endian_files_are_refused_without_guessing(self):
        chunks = [(vectors.JSON_CHUNK, MINIMAL), (vectors.BIN_CHUNK, bytes(8))]
        little = vectors.encode_glb3(chunks)
        big = vectors.encode_glb3(chunks, byteorder=">")
        self.assertEqual(len(little), len(big))
        self.assertEqual(code_of(little), "ACCEPTED")
        self.assertEqual(code_of(big), "BIG_ENDIAN_REFUSED")
        big_v2 = b"glTF" + struct.pack(">II", 2, 12)
        self.assertEqual(code_of(big_v2), "BIG_ENDIAN_REFUSED")
        # Little-endian file header in front of big-endian chunk headers.
        self.assertEqual(code_of(little[:16] + big[16:]), "CHUNK_LENGTH_OVERFLOW")
        # Big-endian file header in front of little-endian chunks.
        self.assertEqual(code_of(big[:16] + little[16:]), "BIG_ENDIAN_REFUSED")
        # Only the 64-bit length is byte swapped.
        self.assertEqual(code_of(little[:8] + little[8:16][::-1] + little[16:]),
                         "LENGTH_MISMATCH")

    def test_64_bit_lengths_cannot_overflow_wrap_or_be_truncated_to_32_bits(self):
        valid = accepted("implicit-bin-triangle-gltf20")
        size = len(valid)
        first = struct.unpack_from("<Q", valid, 24)[0]
        second = 16 + 16 + first + (-first % 8) + 8

        def patched(offset, value):
            data = bytearray(valid)
            struct.pack_into("<Q", data, offset, value)  # raises beyond 64 bits
            return bytes(data)

        expectations = [
            (8, 1 << 63, "LENGTH_MSB"), (8, vectors.MASK64, "LENGTH_MSB"),
            (8, (1 << 63) | size, "LENGTH_MSB"), (8, (1 << 63) - 1, "LENGTH_MISMATCH"),
            (8, (1 << 32) + size, "LENGTH_MISMATCH"), (8, size + 1, "LENGTH_MISMATCH"),
            (8, size - 1, "LENGTH_MISMATCH"), (8, 0, "LENGTH_MISMATCH"),
            (24, 1 << 63, "CHUNK_LENGTH_MSB"),
            # 32 + length would wrap to offset 0, to 16 (the first chunk header
            # again: an endless loop) or to 31 (inside that header).
            (24, (1 << 64) - 32, "CHUNK_LENGTH_MSB"),
            (24, (1 << 64) - 16, "CHUNK_LENGTH_MSB"),
            (24, (1 << 64) - 1, "CHUNK_LENGTH_MSB"),
            # No unsigned wrap, but a signed 64-bit offset would turn negative.
            (24, (1 << 63) - 1, "CHUNK_LENGTH_OVERFLOW"),
            (24, (1 << 32) + first, "CHUNK_LENGTH_OVERFLOW"),
            (24, size - 32 + 1, "CHUNK_LENGTH_OVERFLOW"),
            (second, (1 << 63) + 42, "CHUNK_LENGTH_MSB"),
            (second, 43, "CHUNK_LENGTH_OVERFLOW"),
            (second, (1 << 32) + 42, "CHUNK_LENGTH_OVERFLOW"),
        ]
        self.assertEqual(struct.unpack_from("<Q", valid, second)[0], 42)
        for offset, value, expected in expectations:
            self.assertEqual(code_of(patched(offset, value)), expected, (offset, value))
        # A first chunk swallowing the whole file leaves no implicit BIN chunk.
        self.assertEqual(frame_verdict(patched(24, size - 32), contract=CONTRACT),
                         "R JSON_UTF8")

    def test_budgets_for_source_chunks_and_json_fail_closed(self):
        self.assertEqual(code_of(bytes(sandbox.MAX_SOURCE_BYTES + 1)), "SOURCE_BUDGET")
        empty = (vectors.CUSTOM_CHUNK, b"")
        most = [(vectors.JSON_CHUNK, MINIMAL)] + [empty] * (sandbox.MAX_CHUNKS - 1)
        self.assertEqual(code_of(vectors.encode_glb3(most)), "ACCEPTED")
        self.assertEqual(code_of(vectors.encode_glb3(most + [empty])), "CHUNK_BUDGET")
        padded = MINIMAL + b" " * (sandbox.MAX_JSON_BYTES - len(MINIMAL))
        self.assertEqual(code_of(vectors.encode_glb3([(vectors.JSON_CHUNK, padded)])),
                         "ACCEPTED")
        self.assertEqual(
            code_of(vectors.encode_glb3([(vectors.JSON_CHUNK, padded + b" ")])),
            "JSON_BUDGET")

    def test_padding_is_outside_chunk_length_and_only_whole_alignment_may_trail(self):
        base = vectors.encode_glb3([(vectors.JSON_CHUNK, MINIMAL)])
        self.assertEqual(len(base), 59)
        for extra in range(1, 5):
            self.assertEqual(code_of(vectors.repair_length(base + bytes(extra))),
                             "TRAILING_BYTES")
        padded = vectors.repair_length(base + b"\x00\x07\x00\x00\x09")
        receipt = inspect_glb3_sandbox(padded, contract=CONTRACT)
        self.assertEqual(receipt["container"]["trailing_padding_bytes"], 5)
        self.assertEqual(receipt["container"]["nonzero_padding_bytes"], 2)
        self.assertEqual(receipt["container"]["chunks"][0]["length"], len(MINIMAL))
        # Sixteen aligned stray bytes are a chunk header, never silent padding.
        self.assertEqual(code_of(vectors.repair_length(padded + bytes(8))),
                         "CHUNK_HEADER_TRUNCATED")


class TruncationTests(unittest.TestCase):
    def test_every_prefix_of_every_accepted_vector_is_refused(self):
        checked = 0
        for name, _origin, data in vectors.accepted_vectors():
            for cut in range(len(data)):
                checked += 1
                self.assertNotEqual(code_of(data[:cut]), "ACCEPTED", (name, cut))
        self.assertGreater(checked, 3000)

    def test_length_repaired_prefixes_only_survive_by_dropping_pure_padding(self):
        survivors = []
        for name, _origin, data in vectors.accepted_vectors():
            original = inspect_glb3_sandbox(data, contract=CONTRACT)["container"]
            for cut in range(16, len(data)):
                candidate = vectors.repair_length(data[:cut])
                try:
                    receipt = inspect_glb3_sandbox(candidate, contract=CONTRACT)
                except SandboxRejection:
                    continue
                survivors.append((name, cut))
                self.assertEqual(len(data) - cut, original["trailing_padding_bytes"])
                self.assertEqual(
                    [(c["type"], c["length"], c["sha256"])
                     for c in receipt["container"]["chunks"]],
                    [(c["type"], c["length"], c["sha256"]) for c in original["chunks"]])
        self.assertEqual(survivors, [("trailing-padding-after-last-chunk", 59)])

    def test_a_cut_at_a_chunk_boundary_that_leaves_a_valid_file_is_a_valid_file(self):
        # Not a general "truncation is always refused" property: dropping a
        # trailing chunk that the JSON does not reference leaves a draft-valid
        # smaller file, and that is accepted as what it is.
        whole = vectors.encode_glb3([(vectors.JSON_CHUNK, MINIMAL),
                                     (vectors.CUSTOM_CHUNK, b"12345678")])
        self.assertEqual(len(whole), 88)
        self.assertEqual(code_of(whole), "ACCEPTED")
        self.assertEqual(code_of(whole[:59]), "LENGTH_MISMATCH")
        smaller = inspect_glb3_sandbox(vectors.repair_length(whole[:59]),
                                       contract=CONTRACT)
        self.assertEqual(len(smaller["container"]["chunks"]), 1)
        # Only three lengths are files of their own: the JSON chunk alone (59),
        # the same with its alignment padding (64) and the whole file (88).
        valid = [cut for cut in range(16, 89)
                 if code_of(vectors.repair_length(whole[:cut])) == "ACCEPTED"]
        self.assertEqual(valid, [59, 64, 88])


class JsonAndBoundsTests(unittest.TestCase):
    def test_every_named_negative_vector_is_refused_with_its_stated_reason(self):
        found = {name: code_of(data) for name, _origin, data in vectors.rejected_vectors()}
        self.assertEqual(found, EXPECTED_REJECTIONS)

    def test_strict_utf8_matrix(self):
        cases = [
            (b"\xc3\xa4", True), (b"\xe2\x82\xac", True), (b"\xf0\x9f\x98\x80", True),
            (b"\xef\xbf\xbf", True), (b"\xf4\x8f\xbf\xbf", True), (b"\xed\x9f\xbf", True),
            (b"\xc0\xaf", False), (b"\xc1\xbf", False), (b"\xe0\x80\xaf", False),
            (b"\xf0\x80\x80\xaf", False), (b"\xed\xa0\x80", False),
            (b"\xed\xbf\xbf", False), (b"\xf4\x90\x80\x80", False),
            (b"\xf5\x80\x80\x80", False), (b"\x80", False), (b"\xbf", False),
            (b"\xe2\x82", False), (b"\xf0\x9f\x98", False), (b"\xff", False),
            (b"\xfe", False), (b"\xc3", False),
        ]
        for raw, valid in cases:
            text = b'{"asset":{"version":"2.1","generator":"' + raw + b'"}}'
            code = code_of(vectors.encode_glb3([(vectors.JSON_CHUNK, text)]))
            self.assertEqual(code, "ACCEPTED" if valid else "JSON_UTF8", raw)

    def test_json_grammar_and_number_edges(self):
        def code(text):
            return code_of(vectors.encode_glb3([(vectors.JSON_CHUNK, text)]))

        self.assertEqual(code(MINIMAL + b" \t\r\n"), "ACCEPTED")
        self.assertEqual(code(b" " + MINIMAL), "ACCEPTED")
        self.assertEqual(code(b""), "JSON_SYNTAX")
        self.assertEqual(code(b"[]"), "JSON_ROOT")
        self.assertEqual(code(b"null"), "JSON_ROOT")
        self.assertEqual(code(MINIMAL + MINIMAL), "JSON_SYNTAX")
        self.assertEqual(code(MINIMAL[:-1]), "JSON_SYNTAX")
        self.assertEqual(code(b"{'asset':{'version':'2.1'}}"), "JSON_SYNTAX")
        self.assertEqual(code(b'{"asset":{"version":"2.1",}}'), "JSON_SYNTAX")
        self.assertEqual(code(b'{"asset":{"version":"2.1"},"x":"\x01"}'), "JSON_SYNTAX")
        for constant in (b"NaN", b"Infinity", b"-Infinity", b"1e400", b"-1e400"):
            self.assertEqual(code(b'{"asset":{"version":"2.1"},"x":' + constant + b"}"),
                             "JSON_NONFINITE", constant)
        digits = b"9" * sandbox.MAX_INTEGER_DIGITS
        self.assertEqual(code(b'{"asset":{"version":"2.1"},"x":-' + digits + b"}"),
                         "ACCEPTED")
        self.assertEqual(code(b'{"asset":{"version":"2.1"},"x":' + digits + b"9}"),
                         "JSON_NUMBER_RANGE")
        self.assertEqual(code(b'{"asset":{"version":"2.1"},"x":' + b"7" * 5000 + b"}"),
                         "JSON_NUMBER_RANGE")
        self.assertEqual(code(b'{"asset":{"version":"2.1"},"x":{"a":1,"a":1}}'),
                         "JSON_DUPLICATE_KEY")
        self.assertEqual(code(b'{"asset":{"version":"2.1"},"x":"\\udfff"}'),
                         "JSON_LONE_SURROGATE")
        self.assertEqual(code(b'{"asset":{"version":"2.1"},"x":"\\ud83d\\ude00"}'),
                         "ACCEPTED")
        # Bounds of the draft's 64-bit accessor types need up to twenty digits.
        self.assertEqual(sandbox.MAX_INTEGER_DIGITS, len(str(2 ** 64 - 1)))
        wide = {"asset": {"version": "2.1"},
                "accessors": [{"componentType": 5135, "count": 1, "type": "SCALAR",
                               "min": [0], "max": [2 ** 64 - 1]},
                              {"componentType": 5134, "count": 1, "type": "SCALAR",
                               "min": [-2 ** 63], "max": [2 ** 63 - 1]}]}
        self.assertEqual(code(vectors.compact(wide)), "ACCEPTED")

    def test_asset_version_syntax_and_minimum_version(self):
        def code(asset):
            return code_of(with_document({"asset": asset}))

        self.assertEqual(code({"version": "2.0"}), "ACCEPTED")
        self.assertEqual(code({"version": "2.1", "minVersion": "2.0"}), "ACCEPTED")
        self.assertEqual(code({"version": "2.1", "minVersion": "1.0"}), "ACCEPTED")
        for invalid in ("+2.1", "2.1.0", "2.01", "02.1", "2", "2.", ".1", "", "2.1 ",
                        "2.1\n", "2,1", "²·¹", "2." + "1" * 10):
            self.assertEqual(code({"version": invalid}), "ASSET_VERSION", invalid)
        for wrong in (2.1, 2, None, ["2.1"], True):
            self.assertEqual(code({"version": wrong}), "ASSET_VERSION", wrong)
        for future in ("2.2", "2.10", "3.0", "1.0", "0.0", "999999999.999999999"):
            self.assertEqual(code({"version": future}), "ASSET_VERSION_UNSUPPORTED",
                             future)
        self.assertEqual(code({"version": "2.0", "minVersion": "2.1"}),
                         "ASSET_MIN_VERSION")
        self.assertEqual(code({"version": "2.1", "minVersion": 2}), "ASSET_MIN_VERSION")
        self.assertEqual(code({"version": "2.1", "minVersion": None}),
                         "ASSET_MIN_VERSION")
        self.assertEqual(code_of(with_document({})), "ASSET")
        self.assertEqual(code_of(with_document({"asset": "2.1"})), "ASSET")

    def test_buffer_view_and_accessor_bounds_are_exact(self):
        bin_chunk = (vectors.BIN_CHUNK, vectors.TRIANGLE_BIN)

        def code(mutate):
            document = vectors.triangle_document()
            mutate(document)
            return code_of(with_document(document, bin_chunk))

        def view(index, **changes):
            return lambda document: document["bufferViews"][index].update(changes)

        def accessor(index, **changes):
            return lambda document: document["accessors"][index].update(changes)

        self.assertEqual(code(lambda document: None), "ACCEPTED")
        self.assertEqual(code(view(1, byteLength=7)), "BUFFERVIEW_BOUNDS")
        self.assertEqual(code(view(1, byteOffset=37)), "BUFFERVIEW_BOUNDS")
        self.assertEqual(code(view(0, byteOffset=-1)), "BUFFERVIEW_BOUNDS")
        self.assertEqual(code(view(0, byteLength=0)), "BUFFERVIEW_BOUNDS")
        self.assertEqual(code(view(0, byteLength=36.5)), "BUFFERVIEW_BOUNDS")
        self.assertEqual(code(view(0, byteLength=True)), "BUFFERVIEW_BOUNDS")
        self.assertEqual(code(view(0, byteLength=2 ** 53 + 1)), "BUFFERVIEW_BOUNDS")
        self.assertEqual(code(view(0, buffer=1)), "BUFFERVIEW_BUFFER")
        self.assertEqual(code(view(0, buffer=-1)), "BUFFERVIEW_BUFFER")
        self.assertEqual(code(view(0, buffer=0.5)), "BUFFERVIEW_BUFFER")
        self.assertEqual(code(view(0, byteStride=12)), "ACCEPTED")
        self.assertEqual(code(view(0, byteStride=16)), "ACCESSOR_BOUNDS")
        for stride in (0, 2, 6, 256, 12.5, "12", True):
            self.assertEqual(code(view(0, byteStride=stride)), "BUFFERVIEW_STRIDE", stride)
        # A stride may not be larger than the view it steps through.
        self.assertEqual(code(view(0, byteStride=36)), "ACCESSOR_BOUNDS")
        self.assertEqual(code(view(0, byteStride=40)), "BUFFERVIEW_STRIDE")
        self.assertEqual(code(view(1, byteStride=8)), "BUFFERVIEW_STRIDE")
        self.assertEqual(code(accessor(0, count=4)), "ACCESSOR_BOUNDS")
        # Offsets are multiples of the component size (float32: four bytes).
        for misaligned in (1, 2, 3):
            self.assertEqual(code(accessor(0, byteOffset=misaligned)),
                             "ACCESSOR_ALIGNMENT", misaligned)
        self.assertEqual(code(accessor(0, byteOffset=4)), "ACCESSOR_BOUNDS")
        self.assertEqual(code(accessor(0, byteOffset=4, count=2)), "ACCEPTED")
        self.assertEqual(code(accessor(1, byteOffset=1, count=2)), "ACCESSOR_ALIGNMENT")
        self.assertEqual(code(accessor(1, byteOffset=2, count=2)), "ACCEPTED")
        self.assertEqual(code(accessor(1, count=4)), "ACCESSOR_BOUNDS")
        self.assertEqual(code(accessor(1, componentType=5125)), "ACCESSOR_BOUNDS")
        self.assertEqual(code(accessor(1, componentType=5121)), "ACCEPTED")
        self.assertEqual(code(accessor(0, count=0)), "ACCESSOR_COUNT")
        self.assertEqual(code(accessor(0, bufferView=2)), "ACCESSOR_BUFFERVIEW")
        self.assertEqual(code(accessor(0, type="VEC5")), "ACCESSOR_TYPE")
        self.assertEqual(code(accessor(0, type=["VEC3"])), "ACCESSOR_TYPE")
        for component in (5127, 5126.5, True, "5126", None, 0):
            self.assertEqual(code(accessor(0, componentType=component)),
                             "ACCESSOR_COMPONENT_TYPE", component)
        # Matrix columns are padded: nine one-byte components need twelve bytes.
        self.assertEqual(code(accessor(0, type="MAT3", componentType=5121, count=3)),
                         "ACCEPTED")
        self.assertEqual(code(accessor(0, type="MAT3", componentType=5121, count=4)),
                         "ACCESSOR_BOUNDS")

    def test_accessor_alignment_follows_the_component_size_including_draft_types(self):
        def code(view, accessor, length=48):
            document = {"asset": {"version": "2.1"},
                        "buffers": [{"byteLength": length, "chunk": 1}],
                        "bufferViews": [dict(buffer=0, **view)],
                        "accessors": [dict(bufferView=0, type="SCALAR", **accessor)]}
            return code_of(with_document(document, (vectors.BIN_CHUNK, bytes(length))))

        double = {"componentType": 5130, "count": 2}  # float64 from the 2.1 draft
        self.assertEqual(code({"byteLength": 48}, double), "ACCEPTED")
        self.assertEqual(code({"byteLength": 48, "byteStride": 16}, double), "ACCEPTED")
        # Twelve is a multiple of four but not of the eight-byte component.
        self.assertEqual(code({"byteLength": 48, "byteStride": 12}, double),
                         "ACCESSOR_ALIGNMENT")
        self.assertEqual(code({"byteLength": 40, "byteOffset": 4}, double),
                         "ACCESSOR_ALIGNMENT")
        self.assertEqual(code({"byteLength": 40, "byteOffset": 8}, double), "ACCEPTED")
        self.assertEqual(code({"byteLength": 48}, dict(double, byteOffset=4)),
                         "ACCESSOR_ALIGNMENT")
        short = {"componentType": 5123, "count": 2}
        self.assertEqual(code({"byteLength": 5, "byteOffset": 1}, short),
                         "ACCESSOR_ALIGNMENT")
        self.assertEqual(code({"byteLength": 5, "byteOffset": 1},
                              {"componentType": 5121, "count": 5}), "ACCEPTED")

        def without_view(**accessor):
            document = {"asset": {"version": "2.1"},
                        "accessors": [dict(componentType=5126, count=3, type="VEC3",
                                           **accessor)]}
            return code_of(with_document(document))

        self.assertEqual(without_view(), "ACCEPTED")
        for offset in (0, 4, "x", None):
            self.assertEqual(without_view(byteOffset=offset), "ACCESSOR_BOUNDS", offset)

    def test_integers_written_as_decimals_or_exponents_are_the_same_value(self):
        text = (b'{"asset":{"version":"2.1"},"buffers":[{"byteLength":4.2e1,"chunk":1.0}],'
                b'"bufferViews":[{"buffer":0.0,"byteOffset":0e0,"byteLength":36.000,'
                b'"byteStride":1.2E1},{"buffer":-0.0,"byteOffset":3.6e1,"byteLength":6}],'
                b'"accessors":[{"bufferView":0,"componentType":5126.0,"count":3.0,'
                b'"type":"VEC3"},{"bufferView":1.0,"componentType":5.123e3,"count":3,'
                b'"type":"SCALAR"}]}')
        data = vectors.encode_glb3([(vectors.JSON_CHUNK, text),
                                    (vectors.BIN_CHUNK, vectors.TRIANGLE_BIN)])
        receipt = inspect_glb3_sandbox(data, contract=CONTRACT)
        self.assertEqual(receipt["gltf"]["buffers"],
                         [{"source": "glb_chunk", "chunk": 1, "byte_length": 42}])
        self.assertIs(type(receipt["gltf"]["buffers"][0]["byte_length"]), int)
        self.assertEqual(receipt["gltf"]["accessors_checked"], 2)
        json.dumps(receipt, allow_nan=False)
        for fractional in (b"41.5", b"4.25e1", b"42.0000001", b"1e-1", b"9.1e15", b"1e300"):
            broken = text.replace(b"4.2e1", fractional)
            self.assertEqual(code_of(vectors.encode_glb3(
                [(vectors.JSON_CHUNK, broken), (vectors.BIN_CHUNK, vectors.TRIANGLE_BIN)])),
                "BUFFER_LENGTH", fractional)

    def test_buffer_to_chunk_binding_rules(self):
        triangle = (vectors.BIN_CHUNK, vectors.TRIANGLE_BIN)

        def code(buffer, *chunks, version="2.1"):
            document = vectors.triangle_document(version)
            document["buffers"] = [buffer]
            return code_of(with_document(document, *chunks))

        self.assertEqual(code({"byteLength": 42}, triangle), "ACCEPTED")
        self.assertEqual(code({"byteLength": 42}), "BUFFER_IMPLICIT_BIN_MISSING")
        self.assertEqual(code({"byteLength": 42}, (vectors.CUSTOM_CHUNK, bytes(42))),
                         "BUFFER_IMPLICIT_BIN_MISSING")
        self.assertEqual(code({"byteLength": 42, "chunk": 1},
                              (vectors.CUSTOM_CHUNK, bytes(42))), "ACCEPTED")
        self.assertEqual(code({"byteLength": 43, "chunk": 1}, triangle),
                         "BUFFER_CHUNK_BOUNDS")
        self.assertEqual(code({"byteLength": 43}, triangle), "BUFFER_CHUNK_BOUNDS")
        self.assertEqual(code({"byteLength": 42, "chunk": 2}, triangle),
                         "BUFFER_CHUNK_MISSING")
        for wrong in (-1, 1.5, True, "1", None):
            self.assertEqual(code({"byteLength": 42, "chunk": wrong}, triangle),
                             "BUFFER_CHUNK_MISSING", wrong)
        self.assertEqual(code({"byteLength": 42, "chunk": 1, "uri": "a.bin"}, triangle),
                         "BUFFER_SOURCE_AMBIGUOUS")
        for wrong in (0, -1, 42.5, True, None, "42", 2 ** 53 + 1):
            self.assertEqual(code({"byteLength": wrong, "chunk": 1}, triangle),
                             "BUFFER_LENGTH", wrong)
        prefix = vectors.encode_glb3([
            (vectors.CUSTOM_CHUNK, b"producer"),
            (vectors.JSON_CHUNK, vectors.compact(vectors.triangle_document())), triangle])
        self.assertEqual(code_of(prefix), "BUFFER_IMPLICIT_BIN_MISSING")

    def test_draft_only_properties_are_reported_but_never_resolved(self):
        receipt = inspect_glb3_sandbox(accepted("multi-chunk-files-external-assets"),
                                       contract=CONTRACT)
        self.assertEqual(receipt["draft_features_observed"], [
            "accessor_component_types_2_1", "asset_thumbnail", "asset_version_2_1",
            "buffer_chunk_reference", "external_assets", "files", "glb_container_v3",
            "multiple_binary_chunks", "multiple_json_chunks", "shapes"])
        gltf = receipt["gltf"]
        self.assertEqual((gltf["files"], gltf["file_aliases"], gltf["external_assets"]),
                         (3, 1, 2))
        self.assertEqual(gltf["external_asset_cycles"], "not_evaluated")
        self.assertEqual([b["source"] for b in gltf["buffers"]],
                         ["glb_chunk", "glb_chunk", "glb_chunk", "external_unresolved"])
        self.assertEqual(gltf["extensions"], [
            {"name": "KHR_mesh_quantization", "payload": "not_decoded",
             "promoted_in_2_1_draft": True,
             "registry_status": "ratified_khronos_registry_2_0", "required": True},
            {"name": "KHR_node_visibility", "payload": "not_decoded",
             "promoted_in_2_1_draft": True,
             "registry_status": "ratified_khronos_registry_2_0", "required": False},
            {"name": "VENDOR_unverified_demo", "payload": "not_decoded",
             "promoted_in_2_1_draft": False, "registry_status": "unverified",
             "required": False}])
        roles = [chunk["role"] for chunk in receipt["container"]["chunks"]]
        self.assertEqual(roles, ["main_json", "binary_buffer", "binary_buffer",
                                 "additional_json"])
        custom = inspect_glb3_sandbox(accepted("custom-chunk-before-json-explicit-bin"),
                                      contract=CONTRACT)
        self.assertEqual(custom["container"]["main_json_chunk"], 1)
        self.assertEqual(custom["container"]["nonzero_padding_bytes"], 7)
        self.assertEqual(custom["container"]["chunks"][0]["role"], "unknown_type_ignored")
        self.assertIn("chunk_before_main_json", custom["draft_features_observed"])
        self.assertIn("unknown_chunk_types", custom["draft_features_observed"])

    def test_files_external_assets_and_extension_lists_fail_closed(self):
        def code(**changes):
            document = vectors.complex_document()
            document.update(changes)
            return code_of(vectors.encode_glb3(
                [(vectors.JSON_CHUNK, vectors.compact(document))]
                + vectors.complex_chunks()[1:]))

        files = vectors.complex_document()["files"]
        self.assertEqual(code(), "ACCEPTED")
        self.assertEqual(code(files=[{"uri": "a.glb"}]), "FILE_MIMETYPE")
        self.assertEqual(code(files=[{"mimeType": "model/gltf-binary"}]),
                         "FILE_SOURCE_MISSING")
        self.assertEqual(code(files=[{"mimeType": "x/y", "uri": "a", "bufferView": 0}]),
                         "FILE_SOURCE_AMBIGUOUS")
        self.assertEqual(code(files=[{"mimeType": "x/y", "bufferView": 9}]),
                         "FILE_BUFFERVIEW")
        self.assertEqual(code(files=files[:2]), "FILE_ALIASES")
        self.assertEqual(code(files="a.glb"), "FILES")
        self.assertEqual(code(externalAssets=[{"file": 3}]), "EXTERNAL_ASSET_FILE")
        self.assertEqual(code(externalAssets=[{"file": 2}]), "EXTERNAL_ASSET_MEDIA_TYPE")
        self.assertEqual(code(externalAssets=[{}]), "EXTERNAL_ASSET_FILE")
        self.assertEqual(code(externalAssets={"file": 0}), "EXTERNAL_ASSETS")
        self.assertEqual(code(extensionsRequired=["KHR_texture_basisu"]),
                         "EXTENSIONS_REQUIRED_NOT_USED")
        self.assertEqual(code(extensionsUsed=["A", "A"], extensionsRequired=[]),
                         "EXTENSIONS")
        self.assertEqual(code(extensionsUsed="KHR_mesh_quantization"), "EXTENSIONS")
        self.assertEqual(code(extensionsUsed=[1], extensionsRequired=[]), "EXTENSIONS")
        self.assertEqual(code(images=[{"uri": "a.png", "bufferView": 0}]),
                         "IMAGE_SOURCE_AMBIGUOUS")
        self.assertEqual(code(images=[{"bufferView": 99}]), "IMAGE_BUFFERVIEW")
        self.assertEqual(code(images=[{}]), "IMAGE_SOURCE_MISSING")
        self.assertEqual(code(images=[{"mimeType": "image/png"}]), "IMAGE_SOURCE_MISSING")
        self.assertEqual(code(images=[{"uri": 7}]), "URI_TYPE")
        self.assertEqual(code(shapes={"type": "box"}), "ARRAYS")


class DecompressionBombTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bomb = vectors.gzip_bomb(32)  # about 32 KiB that inflate to 32 MiB

    def peak_bytes(self, call):
        tracemalloc.start()
        try:
            result = call()
            return result, tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    def test_gzip_wrapped_input_is_refused_and_never_inflated(self):
        self.assertLess(len(self.bomb), 64 * 1024)
        self.assertEqual(self.bomb[:2], b"\x1f\x8b")
        code, peak = self.peak_bytes(lambda: code_of(self.bomb))
        self.assertEqual(code, "COMPRESSED_INPUT_REFUSED")
        self.assertLess(peak, 256 * 1024)
        import gzip
        wrapped = gzip.compress(accepted("implicit-bin-triangle-gltf20"))
        self.assertEqual(code_of(wrapped), "COMPRESSED_INPUT_REFUSED")
        for signature in (b"\x28\xb5\x2f\xfd", b"\xfd7zXZ\x00", b"BZh9", b"PK\x03\x04"):
            self.assertEqual(code_of(signature + bytes(64)), "COMPRESSED_INPUT_REFUSED")

    def test_bomb_inside_a_plain_bin_chunk_stays_opaque(self):
        document = {"asset": {"version": "2.1"},
                    "buffers": [{"byteLength": len(self.bomb), "chunk": 1}]}
        data = with_document(document, (vectors.BIN_CHUNK, self.bomb))
        receipt, peak = self.peak_bytes(
            lambda: inspect_glb3_sandbox(data, contract=CONTRACT))
        chunk = receipt["container"]["chunks"][1]
        self.assertEqual(chunk["content"], "opaque_not_decoded")
        self.assertEqual(chunk["length"], len(self.bomb))
        self.assertEqual(chunk["sha256"], hashlib.sha256(self.bomb).hexdigest())
        self.assertEqual(receipt["decoding"], {
            "chunk_encoding": "plain_only", "decompression": "not_executed",
            "images": "not_decoded", "extension_payloads": "not_decoded"})
        self.assertLess(peak, 1024 * 1024)  # the bomb would need 32 MiB

    def test_any_nonzero_chunk_encoding_is_refused_before_touching_the_payload(self):
        for encoding in (1, 2, 0x70697A67, 0xFFFFFFFF):
            for kind in (vectors.BIN_CHUNK, vectors.CUSTOM_CHUNK, vectors.JSON_CHUNK):
                data = vectors.encode_glb3([(vectors.JSON_CHUNK, MINIMAL),
                                            (kind, self.bomb, encoding)])
                code, peak = self.peak_bytes(lambda: code_of(data))
                self.assertEqual(code, "CHUNK_ENCODING_REFUSED")
                self.assertLess(peak, 256 * 1024)
        main = vectors.encode_glb3([(vectors.JSON_CHUNK, self.bomb, 1)])
        self.assertEqual(code_of(main), "CHUNK_ENCODING_REFUSED")

    def test_bomb_in_a_data_uri_or_compression_extension_is_not_decoded(self):
        uri = "data:application/gzip;base64," + base64.b64encode(self.bomb).decode()
        document = {"asset": {"version": "2.1"},
                    "extensionsUsed": ["EXT_meshopt_compression",
                                       "KHR_draco_mesh_compression"],
                    "buffers": [{"byteLength": len(self.bomb), "uri": uri}],
                    "images": [{"uri": uri}]}
        receipt, peak = self.peak_bytes(
            lambda: inspect_glb3_sandbox(with_document(document), contract=CONTRACT))
        self.assertEqual(receipt["gltf"]["buffers"][0]["source"],
                         "embedded_data_uri_not_decoded")
        self.assertEqual(receipt["gltf"]["images"]["embedded_data_uri_not_decoded"], 1)
        self.assertEqual(receipt["external_resolution"]["data_uri_chars_not_decoded"],
                         2 * len(uri))
        self.assertTrue(all(extension["payload"] == "not_decoded"
                            for extension in receipt["gltf"]["extensions"]))
        self.assertLess(peak, 2 * 1024 * 1024)
        over = {"asset": {"version": "2.1"},
                "images": [{"uri": "data:;base64," + "A" * sandbox.MAX_DATA_URI_CHARS}]}
        self.assertEqual(code_of(with_document(over)), "DATA_URI_BUDGET")

    def test_json_structure_bombs_are_refused_by_budget_not_by_crash(self):
        def code(extras):
            return code_of(vectors.encode_glb3(
                [(vectors.JSON_CHUNK, b'{"asset":{"version":"2.1"},"extras":' + extras
                  + b"}")]))

        limit = sandbox.MAX_JSON_DEPTH
        self.assertEqual(code(b"[" * (limit - 1) + b"]" * (limit - 1)), "ACCEPTED")
        self.assertEqual(code(b"[" * limit + b"]" * limit), "JSON_DEPTH")
        self.assertEqual(code(b"[" * 200_000 + b"]" * 200_000), "JSON_DEPTH")
        self.assertEqual(code(b'{"a":' * 100_000 + b"1" + b"}" * 100_000), "JSON_DEPTH")
        self.assertEqual(code(b"[" * 200_000), "JSON_DEPTH")
        # Brackets hidden in strings neither raise nor lower the measured depth.
        self.assertEqual(code(b'"' + b"[" * 5000 + b'"'), "ACCEPTED")
        self.assertEqual(code(b'["]]]]]]]]",' + b"[" * limit + b"]" * limit + b"]"),
                         "JSON_DEPTH")
        self.assertEqual(code(b"[" + b"[]," * 600_000 + b"[]]"), "JSON_VALUE_BUDGET")
        self.assertEqual(code(b"[" + b"0," * 600_000 + b"0]"), "JSON_VALUE_BUDGET")
        self.assertEqual(code(b'"' * (sandbox.MAX_JSON_QUOTES + 1)),
                         "JSON_VALUE_BUDGET")
        # The budget counts structural characters, also inside one string.
        self.assertEqual(code(b'"' + b"," * sandbox.MAX_JSON_VALUES + b'"'),
                         "JSON_VALUE_BUDGET")
        self.assertEqual(code(b'"' + b"," * (sandbox.MAX_JSON_VALUES - 4) + b'"'),
                         "ACCEPTED")
        # A hostile unterminated string is scanned once (linear), then refused.
        self.assertEqual(code(b'"' + b'\\"' * 1_000_000), "JSON_SYNTAX")

    def test_one_huge_json_string_costs_no_scanner_memory(self):
        size = sandbox.MAX_JSON_BYTES - 64
        for body in (b"a" * size, b"\\n" * (size // 2)):
            data = vectors.encode_glb3([(vectors.JSON_CHUNK,
                                         b'{"asset":{"version":"2.1"},"extras":"'
                                         + body + b'"}')])
            code, peak = self.peak_bytes(lambda: code_of(data))
            self.assertEqual(code, "ACCEPTED")
            # Input copy, decoded text and parsed string only; the first draft of
            # the scanner needed hundreds of megabytes here.
            self.assertLess(peak, 32 * 1024 * 1024)


class ExternalResourceTests(unittest.TestCase):
    def test_no_file_network_or_process_is_touched_while_inspecting(self):
        data = accepted("multi-chunk-files-external-assets")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "external.bin").write_bytes(b"secret")
            previous = os.getcwd()
            os.chdir(folder)
            try:
                inspect_glb3_sandbox(data, contract=CONTRACT)  # warm caches unarmed
                _AUDIT["events"].clear()
                _AUDIT["armed"] = True
                try:
                    receipt = inspect_glb3_sandbox(data, contract=CONTRACT)
                    frame_verdict(data, contract=CONTRACT)
                    code_of(vectors.rejected_vectors()[0][2])
                finally:
                    _AUDIT["armed"] = False
                self.assertEqual(_AUDIT["events"], [])
                # Positive control: the hook does observe a real file access.
                _AUDIT["armed"] = True
                try:
                    Path("external.bin").read_bytes()
                finally:
                    _AUDIT["armed"] = False
                self.assertTrue(any(event == "open" for event, _ in _AUDIT["events"]))
            finally:
                _AUDIT["events"].clear()
                os.chdir(previous)
        self.assertEqual(receipt["external_resolution"], {
            "policy": "never", "resolved": 0, "external_references": 6,
            "absolute_or_scheme_references": 1, "parent_traversal_references": 1,
            "data_uri_chars_not_decoded": 0})

    def test_hostile_uris_are_only_counted(self):
        uris = ["../../../../etc/passwd", "/etc/shadow", "file:///etc/hosts",
                "\\\\server\\share\\a.bin", "C:\\Windows\\win.ini",
                "http://169.254.169.254/latest/meta-data", "..\\..\\secret.bin",
                "a/../../b.png", "ok/texture.png", "%2e%2e/encoded.png"]
        document = {"asset": {"version": "2.1"},
                    "images": [{"uri": uri} for uri in uris]}
        resolution = inspect_glb3_sandbox(with_document(document),
                                          contract=CONTRACT)["external_resolution"]
        self.assertEqual(resolution, {
            "policy": "never", "resolved": 0, "external_references": 10,
            "absolute_or_scheme_references": 5, "parent_traversal_references": 4,
            "data_uri_chars_not_decoded": 0})

    def test_uris_are_classified_as_a_loader_would_resolve_them(self):
        def resolution(*uris):
            document = {"asset": {"version": "2.1"},
                        "images": [{"uri": uri} for uri in uris]}
            return inspect_glb3_sandbox(with_document(document),
                                        contract=CONTRACT)["external_resolution"]

        # The draft recommends that loaders strip edge whitespace and control
        # characters and every TAB/LF/CR before resolving a reference.
        hidden = resolution(" ../secret.bin", "..\t/..\t/x", "\t/etc/shadow",
                            " https://169.254.169.254/latest/meta-data",
                            "fi\nle:///etc/hosts", "\x00\x1f//server/share",
                            "%2e%2E%2fsecret.bin", "%2F%2Fserver/share", "%5cshare")
        self.assertEqual((hidden["external_references"],
                          hidden["parent_traversal_references"],
                          hidden["absolute_or_scheme_references"]), (9, 3, 6))
        plain = resolution("textures/a.png", "a..b/c.png", "x%2egif", "..a/b", "a/..b")
        self.assertEqual((plain["external_references"],
                          plain["parent_traversal_references"],
                          plain["absolute_or_scheme_references"]), (5, 0, 0))
        # A data URL behind edge whitespace is still data, not an external reference.
        data = resolution(" data:,x", "\tDATA:,y\n", "data:" + "A" * 3000)
        self.assertEqual((data["external_references"], data["data_uri_chars_not_decoded"]),
                         (0, 8 + 9 + 3005))

    def test_reference_and_uri_budgets(self):
        def images(count, length=5):
            return with_document({"asset": {"version": "2.1"}, "images": [
                {"uri": "x" * length} for _ in range(count)]})

        limit = sandbox.MAX_EXTERNAL_REFERENCES
        self.assertEqual(code_of(images(limit)), "ACCEPTED")
        self.assertEqual(code_of(images(limit + 1)), "EXTERNAL_REFERENCE_BUDGET")
        self.assertEqual(code_of(images(1, sandbox.MAX_URI_CHARS)), "ACCEPTED")
        self.assertEqual(code_of(images(1, sandbox.MAX_URI_CHARS + 1)), "URI_BUDGET")
        mixed = {"asset": {"version": "2.1"},
                 "buffers": [{"byteLength": 1, "uri": "b%d.bin" % i} for i in range(200)],
                 "images": [{"uri": "i%d.png" % i} for i in range(57)]}
        self.assertEqual(code_of(with_document(mixed)), "EXTERNAL_REFERENCE_BUDGET")
        files = {"asset": {"version": "2.1"},
                 "files": [{"uri": "a.glb", "mimeType": "model/gltf-binary"}],
                 "externalAssets": [{"file": 0}] * limit}
        self.assertEqual(code_of(with_document(files)), "EXTERNAL_REFERENCE_BUDGET")


class ReceiptEvidenceTests(unittest.TestCase):
    def test_pinned_decode_receipts_match_a_full_recomputation(self):
        pinned = json.loads(vectors.EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(pinned["sha256"], vectors.evidence_digest(pinned))
        self.assertEqual(pinned, vectors.build_evidence())
        self.assertEqual(pinned["specification"], sandbox.SPEC_BASIS)
        names = [vector["name"] for vector in pinned["vectors"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual({v["name"]: v["code"] for v in pinned["vectors"]
                          if v["verdict"] == "rejected"}, EXPECTED_REJECTIONS)
        self.assertEqual(sum(v["verdict"] == "accepted" for v in pinned["vectors"]), 9)

    def test_receipt_binds_source_and_every_chunk_payload_by_sha256(self):
        data = accepted("implicit-bin-triangle-gltf20")
        receipt = inspect_glb3_sandbox(data, contract=CONTRACT)
        self.assertEqual(receipt["source"],
                         {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        for chunk in receipt["container"]["chunks"]:
            payload = data[chunk["offset"]:chunk["offset"] + chunk["length"]]
            self.assertEqual(chunk["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(receipt["container"]["chunks"][1]["sha256"],
                         hashlib.sha256(vectors.TRIANGLE_BIN).hexdigest())
        self.assertEqual(receipt_digest(receipt),
                         receipt_digest(inspect_glb3_sandbox(data, contract=CONTRACT)))
        flipped = bytearray(data)
        flipped[-1] ^= 1
        other = inspect_glb3_sandbox(bytes(flipped), contract=CONTRACT)
        self.assertNotEqual(receipt_digest(other), receipt_digest(receipt))
        self.assertEqual(other["container"]["framing"], receipt["container"]["framing"])
        json.dumps(receipt, allow_nan=False)
        self.assertEqual(receipt["limits"], sandbox.LIMITS)
        self.assertEqual({key: receipt["limits"][key] for key in (
            "extension_name_chars", "media_type_chars", "integer_value",
            "json_structural_characters", "json_quote_characters", "integer_digits")},
            {"extension_name_chars": 128, "media_type_chars": 255,
             "integer_value": 2 ** 53, "json_structural_characters": 524288,
             "json_quote_characters": 2097152, "integer_digits": 20})

    def test_declared_limits_are_the_enforced_ones(self):
        def code(**document):
            return code_of(with_document(dict({"asset": {"version": "2.1"}}, **document)))

        name = "VENDOR_" + "x" * (sandbox.MAX_EXTENSION_NAME_CHARS - 7)
        self.assertEqual(code(extensionsUsed=[name]), "ACCEPTED")
        self.assertEqual(code(extensionsUsed=[name + "x"]), "EXTENSIONS")
        media = "model/gltf+json; p=" + "y" * (sandbox.MAX_MEDIA_TYPE_CHARS - 19)
        self.assertEqual(code(files=[{"uri": "a.gltf", "mimeType": media}]), "ACCEPTED")
        self.assertEqual(code(files=[{"uri": "a.gltf", "mimeType": media + "y"}]),
                         "FILE_MIMETYPE")
        limit = sandbox.MAX_SAFE_INTEGER
        self.assertEqual(code(buffers=[{"uri": "huge.bin", "byteLength": limit}]),
                         "ACCEPTED")
        self.assertEqual(code(buffers=[{"uri": "huge.bin", "byteLength": limit + 1}]),
                         "BUFFER_LENGTH")
        self.assertEqual(code(extensionsUsed=["E%d" % i for i in range(
            sandbox.MAX_EXTENSION_NAMES)]), "ACCEPTED")
        self.assertEqual(code(extensionsUsed=["E%d" % i for i in range(
            sandbox.MAX_EXTENSION_NAMES + 1)]), "EXTENSIONS")

    def test_independent_layouts_agree_only_where_the_draft_alignment_allows(self):
        table = inspect_glb3_sandbox(
            accepted("khronos-issue-2594-custom-before-json-layout"), contract=CONTRACT)
        chunks = table["container"]["chunks"]
        self.assertEqual(table["source"]["bytes"], 96)
        self.assertEqual([(int(c["type"], 16), c["encoding"], c["length"]) for c in chunks],
                         [(123, 0, 16), (vectors.JSON_CHUNK, 0, 32)])
        self.assertEqual(table["gltf"]["asset_version"], "2.1")
        aligned = accepted("loaders-gl-a4faaba-lengths-multiple-of-8")
        self.assertEqual(code_of(aligned), "ACCEPTED")
        divergent = next(data for name, _origin, data in vectors.rejected_vectors()
                         if name.startswith("loaders-gl"))
        # The independent writer starts its BIN chunk on a 4-byte boundary only.
        json_length = struct.unpack_from("<Q", divergent, 24)[0]
        self.assertEqual(json_length % 8, 4)
        self.assertEqual(struct.unpack_from("<I", divergent, 32 + json_length)[0],
                         vectors.BIN_CHUNK)
        self.assertEqual(code_of(divergent), "CHUNK_LENGTH_OVERFLOW")
        # The layouts differ only where another chunk follows: the same writer's
        # files whose LAST chunk has a length of 4 mod 8 are byte-valid in both.
        for binary in (bytes(4), bytes(12), bytes(20)):
            last = vectors.loaders_gl_style_glb3(vectors._loaders_document(0), [binary])
            self.assertEqual(struct.unpack_from("<Q", last, 24)[0] % 8, 0)
            self.assertEqual(len(binary) % 8, 4)
            self.assertEqual(frame_verdict(last, contract=CONTRACT)[:2], "A ")
        only_json = vectors.loaders_gl_style_glb3(vectors._loaders_document(4))
        self.assertEqual(struct.unpack_from("<Q", only_json, 24)[0] % 8, 4)
        self.assertEqual(frame_verdict(only_json, contract=CONTRACT)[:2], "A ")


if __name__ == "__main__":
    unittest.main()
