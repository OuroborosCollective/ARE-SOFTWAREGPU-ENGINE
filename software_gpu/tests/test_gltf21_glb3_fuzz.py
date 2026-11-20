"""Seeded Python and native C++17 fuzz-negative tests for the GLB v3 DRAFT sandbox.

Two independently written framing implementations (Python and C++17) must give
the same verdict for every mutated input on Linux and Windows. The corpus comes
from an explicit PRNG, so its SHA-256 and the verdict digest are pinned. This is
robustness evidence for an unratified draft, not conformance or performance.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from software_gpu.research.native_symbolic import FLAGS, compiler
from software_gpu.tests.fixtures import glb3_draft_vectors as vectors
from tools.gltf21_glb3_sandbox import (
    CONTRACT,
    SandboxRejection,
    frame_verdict,
    inspect_glb3_sandbox,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "native/gltf/glb3_container_probe.cpp"
SANITIZE = ("-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g")
UTF8_EDGES = (b"\xc3\xa4", b"\xf0\x9f\x98\x80", b"\xf4\x8f\xbf\xbf", b"\xed\x9f\xbf",
              b"\xc0\xaf", b"\xc1\xbf", b"\xe0\x80\xaf", b"\xe0\x9f\xbf", b"\xed\xa0\x80",
              b"\xf0\x80\x80\xaf", b"\xf0\x8f\xbf\xbf", b"\xf4\x90\x80\x80",
              b"\xf5\x80\x80\x80", b"\x80", b"\xbf", b"\xe2\x82", b"\xf0\x9f\x98",
              b"\xff", b"\xfe", b"\xc3", b"\xef\xbb\xbf", b"\x00")


def pinned():
    return json.loads(vectors.EVIDENCE.read_text(encoding="utf-8"))["fuzz"]


def summary(lines):
    codes = {}
    for line in lines:
        if line.startswith("R "):
            codes[line[2:]] = codes.get(line[2:], 0) + 1
    return {"cases": len(lines), "accepted": sum(line.startswith("A ") for line in lines),
            "rejected": sum(codes.values()), "codes": dict(sorted(codes.items())),
            "verdicts_sha256": hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()}


def exhaustive_single_byte_cases():
    """Every value at every offset of the 59-byte minimal file (15104 inputs)."""
    base = vectors.accepted_vectors()[0][2]
    cases = []
    for offset in range(len(base)):
        for value in range(256):
            cases.append(base[:offset] + bytes([value]) + base[offset + 1:])
    return cases


def directed_cases():
    minimal = b'{"asset":{"version":"2.1"}}'
    cases = [data for _name, _origin, data in
             vectors.accepted_vectors() + vectors.rejected_vectors()]
    cases += [vectors.encode_glb3([(vectors.JSON_CHUNK,
                                    b'{"asset":{"version":"2.1","generator":"'
                                    + edge + b'"}}')]) for edge in UTF8_EDGES]
    cases += [b"", b"g", b"glT", b"glTF", b"glTF\x03", b"glTF\x03\x00\x00\x00",
              b"glTF\x03\x00\x00\x00" + bytes(7), b"\x1f", b"\x1f\x8b", b"BZ", b"BZh",
              b"PK\x03", b"PK\x03\x04", b"\xfd7zXZ", b"\xfd7zXZ\x00",
              b"\x28\xb5\x2f", b"\x28\xb5\x2f\xfd"]
    empty = (vectors.CUSTOM_CHUNK, b"")
    cases.append(vectors.encode_glb3([(vectors.JSON_CHUNK, minimal)] + [empty] * 63))
    cases.append(vectors.encode_glb3([(vectors.JSON_CHUNK, minimal)] + [empty] * 64))
    cases.append(vectors.encode_glb3([empty] * 64 + [(vectors.JSON_CHUNK, minimal)]))
    return cases


class PythonFuzzTests(unittest.TestCase):
    def test_framing_fuzz_only_ever_refuses_cleanly_and_matches_the_pinned_digest(self):
        corpus = vectors.framing_corpus()
        self.assertEqual(hashlib.sha256(vectors.bundle(corpus)).hexdigest(),
                         pinned()["framing"]["corpus_sha256"])
        lines = [frame_verdict(case, contract=CONTRACT) for case in corpus]
        found = summary(lines)
        expected = {key: pinned()["framing"][key] for key in found}
        self.assertEqual(found, expected)
        self.assertGreater(found["accepted"], 500)
        self.assertGreater(found["rejected"], 2000)
        self.assertGreaterEqual(len(found["codes"]), 12)

    def test_accepted_mutants_keep_every_chunk_inside_the_file(self):
        accepted = 0
        for case in vectors.framing_corpus():
            verdict = frame_verdict(case, contract=CONTRACT)
            if not verdict.startswith("A "):
                continue
            accepted += 1
            fields = verdict[2:].split(";")
            self.assertEqual(fields[0], "glb3")
            count = int(fields[1].split("=")[1])
            chunks = [tuple(int(part, 16 if index == 0 else 10)
                            for index, part in enumerate(field.split(":")))
                      for field in fields[5:]]
            self.assertEqual(len(chunks), count)
            previous_end = 16
            for _kind, encoding, offset, length in chunks:
                self.assertEqual(encoding, 0)
                self.assertEqual(offset % 8, 0)
                self.assertGreaterEqual(offset, previous_end + 16)
                self.assertLessEqual(offset + length, len(case))
                previous_end = offset + length
            # The complete inspection may still refuse, but only with a stated code.
            try:
                receipt = inspect_glb3_sandbox(case, contract=CONTRACT)
            except SandboxRejection as rejection:
                self.assertRegex(rejection.code, r"\A[A-Z0-9_]+\Z")
            else:
                self.assertEqual(receipt["container"]["framing"], verdict[2:])
        self.assertGreater(accepted, 500)

    def test_json_stage_fuzz_matches_the_pinned_digest(self):
        corpus = vectors.json_corpus()
        self.assertEqual(hashlib.sha256(vectors.bundle(corpus)).hexdigest(),
                         pinned()["json"]["corpus_sha256"])
        found = summary([vectors.full_verdict(case) for case in corpus])
        expected = {key: pinned()["json"][key] for key in found}
        self.assertEqual(found, expected)
        self.assertGreater(found["accepted"], 100)
        self.assertGreaterEqual(len(found["codes"]), 25)

    def test_exhaustive_single_byte_changes_never_raise_anything_else(self):
        accepted = 0
        for case in exhaustive_single_byte_cases():
            try:
                inspect_glb3_sandbox(case, contract=CONTRACT)
                accepted += 1
            except SandboxRejection:
                pass
        # Offsets 0-31 are header fields: only the identity value survives there.
        self.assertGreater(accepted, 59)
        self.assertLess(accepted, 59 * 256 // 4)


class NativeDifferentialFuzzTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="are-glb3-probe-")
        cls.exe = Path(cls.folder.name) / (
            "glb3_probe.exe" if sys.platform == "win32" else "glb3_probe")
        flags = list(FLAGS)
        cls.sanitized = (os.environ.get("ARE_GLB3_NATIVE_SANITIZE") == "1"
                         and sys.platform.startswith("linux"))
        if cls.sanitized:
            flags += SANITIZE
        cls.build = subprocess.run(
            [compiler(), *flags, str(SOURCE), "-o", str(cls.exe)],
            text=True, capture_output=True, timeout=300)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_probe(self, cases):
        self.assertEqual(self.build.returncode, 0, self.build.stderr[-9000:])
        path = Path(self.folder.name) / "corpus.bundle"
        path.write_bytes(vectors.bundle(cases))
        result = subprocess.run([str(self.exe), str(path)], capture_output=True,
                                text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "GLB3_PROBE_BEGIN %d" % len(cases))
        self.assertEqual(lines[-1], "GLB3_PROBE_END")
        self.assertEqual(len(lines), len(cases) + 2)
        return lines[1:-1]

    def assert_same_verdicts(self, cases):
        native = self.run_probe(cases)
        for index, (line, case) in enumerate(zip(native, cases)):
            expected = frame_verdict(case, contract=CONTRACT)
            if line != expected:
                self.fail("case %d (%d bytes, sha256 %s): native %r != python %r" % (
                    index, len(case), hashlib.sha256(case).hexdigest(), line, expected))
        return native

    def test_native_and_python_agree_on_the_pinned_framing_corpus(self):
        native = self.assert_same_verdicts(vectors.framing_corpus())
        self.assertEqual(summary(native)["verdicts_sha256"],
                         pinned()["framing"]["verdicts_sha256"])
        print("GLB3_NATIVE_DIFFERENTIAL cases=%d sanitized=%s verdicts_sha256=%s" % (
            len(native), self.sanitized, summary(native)["verdicts_sha256"]), flush=True)

    def test_native_and_python_agree_on_json_stage_and_directed_cases(self):
        self.assert_same_verdicts(vectors.json_corpus())
        native = self.assert_same_verdicts(directed_cases())
        self.assertIn("R BIG_ENDIAN_REFUSED", native)
        self.assertIn("R CHUNK_BUDGET", native)
        self.assertIn("R COMPRESSED_INPUT_REFUSED", native)
        self.assertIn("R JSON_BOM", native)
        self.assertIn("R JSON_UTF8", native)
        self.assertIn("R CHUNK_LENGTH_MSB", native)

    def test_native_and_python_agree_on_every_single_byte_change(self):
        native = self.assert_same_verdicts(exhaustive_single_byte_cases())
        self.assertEqual(len(native), 59 * 256)

    def test_native_and_python_agree_on_64_bit_and_budget_boundaries(self):
        valid = vectors.accepted_vectors()[1][2]
        cases = []
        for offset in (8, 24):
            for value in (0, 1, len(valid) - 1, len(valid), len(valid) + 1,
                          (1 << 32) - 1, 1 << 32, (1 << 32) + len(valid),
                          (1 << 63) - 1, 1 << 63, (1 << 63) + len(valid),
                          vectors.MASK64 - 31, vectors.MASK64 - 15, vectors.MASK64):
                data = bytearray(valid)
                struct.pack_into("<Q", data, offset, value)
                cases.append(bytes(data))
        minimal = b'{"asset":{"version":"2.1"}}'
        limit = 4 * 1024 * 1024
        cases.append(vectors.encode_glb3(
            [(vectors.JSON_CHUNK, minimal + b" " * (limit - len(minimal)))]))
        cases.append(vectors.encode_glb3(
            [(vectors.JSON_CHUNK, minimal + b" " * (limit + 1 - len(minimal)))]))
        native = self.assert_same_verdicts(cases)
        self.assertEqual(native[-1], "R JSON_BUDGET")
        self.assertTrue(native[-2].startswith("A glb3;chunks=1;"))
        self.assertIn("R LENGTH_MSB", native)
        self.assertIn("R CHUNK_LENGTH_OVERFLOW", native)

    def test_probe_refuses_malformed_bundles_instead_of_reporting_success(self):
        self.assertEqual(self.build.returncode, 0, self.build.stderr[-9000:])
        good = vectors.bundle([b"glTF"])
        folder = Path(self.folder.name)
        for name, data in (("magic", b"NOTABUND" + good[8:]),
                           ("truncated", good[:-1]),
                           ("trailing", good + b"\x00"),
                           ("count", good[:8] + struct.pack("<I", 2) + good[12:]),
                           ("short", good[:6])):
            path = folder / (name + ".bundle")
            path.write_bytes(data)
            result = subprocess.run([str(self.exe), str(path)], capture_output=True,
                                    text=True, timeout=60)
            self.assertEqual(result.returncode, 3, name)
            self.assertNotIn("GLB3_PROBE_END", result.stdout)
        missing = subprocess.run([str(self.exe), str(folder / "absent.bundle")],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(missing.returncode, 3)
        usage = subprocess.run([str(self.exe)], capture_output=True, text=True, timeout=60)
        self.assertEqual(usage.returncode, 2)


if __name__ == "__main__":
    unittest.main()
