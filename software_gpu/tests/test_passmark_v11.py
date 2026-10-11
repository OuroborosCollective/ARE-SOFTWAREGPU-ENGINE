"""PassMark V11 integrity and negative controls."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

script = Path(__file__).resolve().parents[2] / "tools" / "passmark_v11.py"
spec = importlib.util.spec_from_file_location("passmark_v11",script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class TestPassMarkV11(unittest.TestCase):
    def test_architecture_pins(self):
        self.assertEqual(set(mod.ARCHIVES),{"x86_64","aarch64","armv7l"})
        self.assertEqual(len({v[1] for v in mod.ARCHIVES.values()}),3)
        self.assertEqual({v[3] for v in mod.ARCHIVES.values()},{40,62,183})
        for v in mod.ARCHIVES.values():
            self.assertEqual(len(v[1]),64)
            self.assertEqual(len(v[2]),64)
    def test_missing_archive_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,"PINNED_ARCHIVE_SHA256_MISMATCH"):
                mod.audit(Path(d)/"no.zip","x86_64")
    def test_corrupt_archive_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.zip"
            p.write_bytes(b"invalid")
            with self.assertRaisesRegex(ValueError,"PINNED_ARCHIVE_SHA256_MISMATCH"):
                mod.audit(p,"x86_64")
    def test_modified_archive_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"modified.zip"
            with ZipFile(p,"w") as z:
                z.writestr("PerformanceTest/PerformanceTest_Linux_x86-64",b"\x7fELFbad")
            with self.assertRaisesRegex(ValueError,"PINNED_ARCHIVE_SHA256_MISMATCH"):
                mod.audit(p,"x86_64")
    def test_gpu_profile_forbidden(self):
        with self.assertRaises(SystemExit) as err:
            mod.main(["run","--archive","none.zip","--output-dir","out","--profile","gpu"])
        self.assertEqual(err.exception.code,2)
    def test_result_contract_valid_and_invalid(self):
        result = ("BaselineInfo:\n  WebDBID: -1\nVersion:\n  Major: 11\n"
                  "  Minor: 0\n  Build: 1004\nResults:\n  Results Complete: true\n"
                  "  NumTestProcesses: 2\n  SUMM_CPU: 2645.3\n  SUMM_ME: 1809.6\n"
                  "Checksum: PARSER_TEST_ONLY\n")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "results_all.yml"
            output.write_text(result)
            parsed = mod.validate_result(output, "all", 2)
            self.assertEqual(parsed["cpu_mark"], 2645.3)
            self.assertEqual(parsed["memory_mark"], 1809.6)
            with self.assertRaisesRegex(ValueError, "PASSMARK_PROCESS_COUNT_MISMATCH"):
                mod.validate_result(output, "all", 3)
            for altered, diagnostic in (
                (result.replace("Results Complete: true", "Results Complete: false"),
                 "PASSMARK_VERSION_OR_COMPLETENESS_MISMATCH"),
                (result.replace("Build: 1004", "Build: 1005"),
                 "PASSMARK_VERSION_OR_COMPLETENESS_MISMATCH"),
                (result.replace("SUMM_CPU: 2645.3", "SUMM_CPU: NaN"),
                 "PASSMARK_SCORE_NOT_NUMERIC"),
                (result.replace("SUMM_ME: 1809.6", "SUMM_ME: 0"),
                 "PASSMARK_SCORE_NOT_POSITIVE"),
                (result.replace("  SUMM_CPU: 2645.3\n", ""),
                 "PASSMARK_MISSING_FIELD:SUMM_CPU"),
            ):
                output.write_text(altered)
                with self.subTest(diagnostic=diagnostic), self.assertRaisesRegex(ValueError, diagnostic):
                    mod.validate_result(output, "all", 2)

    def test_zero_exit_without_report_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "results_cpu.yml"
            with self.assertRaisesRegex(ValueError, "PASSMARK_RESULT_MISSING_OR_UNSAFE"):
                mod.validate_result(missing, "cpu", 1)

if __name__=="__main__":
    unittest.main()
