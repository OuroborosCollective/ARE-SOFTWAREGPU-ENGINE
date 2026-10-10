"""CLI contract tests for main.py.

The CI previously smoke-tested only `python main.py --help` as a subprocess.
These tests cover the real command dispatch: telemetry, a render command with
file output, argparse failure behaviour and the fail-closed server path
(no auth token -> ValueError before any socket is bound).

Heavy demo paths (--all, --gaming, --mmorpg, --benchmark) stay out of unit
scope by design; they are documented in docs/CI_COVERAGE_GATES.md.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as cli


def run_cli(argv):
    """Run cli.main() with patched argv; capture stdout and SystemExit code."""
    old_argv = sys.argv
    sys.argv = ["main.py"] + argv
    out = io.StringIO()
    exit_code = None
    try:
        with contextlib.redirect_stdout(out):
            cli.main()
    except SystemExit as exc:
        exit_code = exc.code
    finally:
        sys.argv = old_argv
    return exit_code, out.getvalue()


class TestCLIContract(unittest.TestCase):
    def test_help_exits_zero_and_lists_every_command(self):
        code, out = run_cli(["--help"])
        self.assertEqual(code, 0)
        for flag in ("--all", "--info", "--cuda", "--directx", "--gaming",
                     "--mmorpg", "--blender", "--filters", "--benchmark",
                     "--server", "--http-port", "--tcp-port"):
            self.assertIn(flag, out)

    def test_unknown_flag_exits_with_argparse_code_two(self):
        old_argv = sys.argv
        sys.argv = ["main.py", "--no-such-flag"]
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("usage:", err.getvalue())

    def test_info_prints_real_device_and_governor_telemetry(self):
        code, out = run_cli(["--info"])
        self.assertIsNone(code)
        self.assertIn("Device Name:", out)
        self.assertIn("Streaming Multiprocessors:", out)
        self.assertIn("Virtual VRAM:", out)

    def test_blender_command_writes_valid_bmp_file(self):
        with tempfile.TemporaryDirectory() as d:
            saved = os.environ.get("ARE_SOFTWAREGPU_OUTPUT_DIR")
            os.environ["ARE_SOFTWAREGPU_OUTPUT_DIR"] = d
            try:
                code, _out = run_cli(["--blender"])
            finally:
                if saved is None:
                    os.environ.pop("ARE_SOFTWAREGPU_OUTPUT_DIR", None)
                else:
                    os.environ["ARE_SOFTWAREGPU_OUTPUT_DIR"] = saved
            self.assertIsNone(code)
            bmp = Path(d) / "blender_software_gpu_render.bmp"
            self.assertTrue(bmp.is_file())
            raw = bmp.read_bytes()
            self.assertEqual(raw[:2], b"BM")
            self.assertGreater(len(raw), 54)

    def test_server_fails_closed_without_auth_token_before_binding(self):
        saved = os.environ.pop("SOFTWAREGPU_AUTH_TOKEN", None)
        try:
            with self.assertRaises(ValueError) as cm:
                run_cli(["--server"])
        finally:
            if saved is not None:
                os.environ["SOFTWAREGPU_AUTH_TOKEN"] = saved
        self.assertIn("AUTH_TOKEN_REQUIRED", str(cm.exception))

    def test_server_rejects_non_loopback_host_before_token_check(self):
        from software_gpu.network.server import SoftwareGPUServer
        with self.assertRaises(ValueError) as cm:
            SoftwareGPUServer(host="0.0.0.0", auth_token="x" * 40)
        self.assertIn("REMOTE_BIND_FORBIDDEN", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
