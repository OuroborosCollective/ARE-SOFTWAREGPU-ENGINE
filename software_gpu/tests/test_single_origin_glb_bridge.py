"""End-to-end: SHA-admitted indexed GLB -> native model raster -> single-source timed pulse.

The fixture is a real 28,800-triangle glTF2 binary, not an image stub.
The experimental bridge accepts precisely one model; depth-derived ownership
would be unsound for scenes containing multiple independently owned meshes.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from software_gpu.research.model_probe import load_asset, write_scene
from software_gpu.research.native_symbolic import FLAGS, compiler
from software_gpu.tests.test_single_origin_glb_stress import make_grid_glb

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "native/symbolic/model_pulse_main.cpp"


def build_bridge(root):
    exe = root / ("glb_pulse.exe" if sys.platform == "win32" else "glb_pulse")
    run = subprocess.run(
        [compiler(), *FLAGS, "-pthread", str(SOURCE), "-o", str(exe)],
        capture_output=True, text=True, timeout=180,
    )
    if run.returncode:
        raise AssertionError("GLB_PULSE_BUILD_FAILED: " + run.stderr[-7000:])
    return exe


def execute(exe, request, workers, directory):
    directory.mkdir()
    run = subprocess.run(
        [str(exe), str(request), str(workers), str(directory)],
        capture_output=True, text=True, timeout=240,
    )
    if run.returncode:
        raise AssertionError("GLB_PULSE_RUNTIME_FAILED: " + run.stderr[-7000:])
    frames = []
    benches = []
    for line in run.stdout.splitlines():
        if line.startswith("GLB_PULSE_FRAME "):
            frames.append(json.loads(line[len("GLB_PULSE_FRAME "):]))
        if line.startswith("GLB_PULSE_BENCH "):
            benches.append(json.loads(line[len("GLB_PULSE_BENCH "):]))
    return frames, benches, run.stdout


class TestSingleOriginGlbBridge(unittest.TestCase):
    def test_real_glb_native_raster_wave_sequence_and_15_paired_draws(self):
        with tempfile.TemporaryDirectory(prefix="are-glb-wave-bridge-") as directory:
            root = Path(directory)
            source = root / "grid-28800.glb"
            identity = make_grid_glb(source)
            asset = load_asset(source, identity)
            self.assertEqual(len(asset["faces"]), 28800)
            request = root / "scene.aremdl"
            write_scene(request, [{"asset": asset, "clip": None}], list(range(8)),
                        pixels=128, tile=32, render_profile="diagnostic")
            exe = build_bridge(root)
            one, b1, text = execute(exe, request, 1, root / "one")
            four, b4, _ = execute(exe, request, 4, root / "four")
            self.assertIn("GLB_PULSE_NATIVE_PASS", text)
            self.assertEqual([f["tick"] for f in one], list(range(8)))
            self.assertEqual([f["area_completions"] for f in one],
                             [1, 196, 600, 996, 1416, 1816, 2188, 0])
            self.assertEqual(sum(f["area_completions"] for f in one), 7213)
            self.assertEqual(one, four)
            self.assertGreater(sum(f["tinted_pixels"] for f in one), 0)
            self.assertTrue(all(f["triangles"] == 28800 and f["raster_writes"] > 0
                                and f["alpha_equal"] and f["depth_equal"]
                                and f["replay_equal"] and f["background_preserved"]
                                and f["reemissions"] == 0 and f["queue_pushes"] == 0
                                for f in one))
            self.assertEqual(one[0]["baseline_fnv64"], one[0]["wave_fnv64"])
            self.assertEqual(one[7]["baseline_fnv64"], one[7]["wave_fnv64"])
            self.assertTrue(any(f["wave_fnv64"] != f["baseline_fnv64"] for f in one[1:7]))
            for tick in range(8):
                for prefix in ("base", "wave"):
                    name = f"{prefix}-{tick}.ppm"
                    raw = (root / "one" / name).read_bytes()
                    self.assertEqual(len(raw), len(b"P6\n128 128\n255\n") + 128*128*3)
                    self.assertTrue(raw.startswith(b"P6\n128 128\n255\n"))
                    self.assertEqual(hashlib.sha256(raw).hexdigest(),
                                     hashlib.sha256((root / "four" / name).read_bytes()).hexdigest())
            self.assertEqual(len(b1), 1)
            self.assertEqual(len(b4), 1)
            for bench, workers in ((b1[0], 1), (b4[0], 4)):
                self.assertEqual(bench["workers"], workers)
                self.assertEqual(bench["triangles"], 28800)
                self.assertEqual(bench["pairs"], 15)
                for mode in ("baseline", "wave"):
                    samples = bench["raw_" + mode + "_ms"]
                    self.assertEqual(len(samples), 15)
                    self.assertTrue(all(v > 0 for v in samples))
                    self.assertGreater(bench["median_" + mode + "_ms"], 0)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), identity["sha256"])

    def test_multiple_models_are_rejected_without_projected_ownership(self):
        with tempfile.TemporaryDirectory(prefix="are-glb-wave-owner-") as directory:
            root = Path(directory)
            source = root / "grid.glb"
            asset = load_asset(source, make_grid_glb(source, segments=8))
            request = root / "two.aremdl"
            write_scene(request, [{"asset": asset, "clip": None},
                                  {"asset": asset, "clip": None}], [0.0],
                        pixels=128, tile=32, render_profile="diagnostic")
            exe = build_bridge(root)
            out = root / "never_written"
            out.mkdir()
            run = subprocess.run([str(exe), str(request), "1", str(out)],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 2)
            self.assertIn("GLB_PULSE_SINGLE_OWNER_REQUIRED", run.stderr)
            self.assertFalse(list(out.iterdir()))


if __name__ == "__main__":
    unittest.main()
