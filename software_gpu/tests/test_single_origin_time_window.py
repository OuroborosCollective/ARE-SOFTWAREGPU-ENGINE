"""Real C++17 native raster and deterministic time-window single-origin pulse."""
import subprocess
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from software_gpu.research.native_symbolic import FLAGS, compiler

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"native/raster/single_origin_time_window_test.cpp"

class TestSingleOriginTimeWindow(unittest.TestCase):
    def test_animated_pulse_native_cpp_wolfram_parity_and_15_pairs(self):
        with tempfile.TemporaryDirectory(prefix="are-time-wave-") as directory:
            exe=Path(directory)/("time_wave.exe" if sys.platform=="win32" else "time_wave")
            build=subprocess.run([compiler(),*FLAGS,str(SOURCE),"-o",str(exe)],
                                 capture_output=True,text=True,timeout=120)
            self.assertEqual(build.returncode,0,build.stderr[-7000:])
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=180)
            self.assertEqual(run.returncode,0,run.stderr[-8000:]+run.stdout[-3500:])
            self.assertIn("SINGLE_ORIGIN_TIME_NATIVE_PASS",run.stdout)
            self.assertEqual(run.stdout.count("SINGLE_ORIGIN_TIME_RECEIPT"),4)
            self.assertIn("SINGLE_ORIGIN_SEQUENCE_PASS frames=8 unique_areas=7213 repeated_areas=0",run.stdout)
            self.assertEqual(run.stdout.count("SINGLE_ORIGIN_SEQUENCE_FRAME"),8)
            print(run.stdout,flush=True)

    def test_visual_frames_are_reproducible_ppm_from_real_native_raster(self):
        with tempfile.TemporaryDirectory(prefix="are-wave-frames-") as directory:
            root=Path(directory)
            exe=root/("wave.exe" if sys.platform=="win32" else "wave")
            build=subprocess.run([compiler(),*FLAGS,str(SOURCE),"-o",str(exe)],
                                 capture_output=True,text=True,timeout=120)
            self.assertEqual(build.returncode,0,build.stderr[-5000:])
            frames=root/"frames"
            frames.mkdir()
            def snapshot():
                run=subprocess.run([str(exe),"--frames-dir",str(frames)],
                                   capture_output=True,text=True,timeout=180)
                self.assertEqual(run.returncode,0,run.stderr[-6000:])
                return [hashlib.sha256((frames/f"wave-{i}.ppm").read_bytes()).hexdigest()
                        for i in range(8)]
            first=snapshot()
            self.assertEqual(first,snapshot())
            self.assertEqual(len(set(first)),7)
            self.assertEqual(first[0],first[7])
            for i in range(8):
                raw=(frames/f"wave-{i}.ppm").read_bytes()
                self.assertTrue(raw.startswith(b"P6\n128 128\n255\n"))
                self.assertEqual(len(raw),len(b"P6\n128 128\n255\n")+128*128*3)

if __name__=="__main__":
    unittest.main()
