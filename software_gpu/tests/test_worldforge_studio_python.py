"""Exercise the same external interpreter path the Blender studio uses on Linux."""
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
import venv


@unittest.skipUnless(os.name == "posix", "Linux VPS launcher")
class StudioPythonTests(unittest.TestCase):
    def test_external_alias_retains_release_venv(self):
        update = runpy.run_path(str(Path(__file__).resolve().parents[2] / "ops/worldforge/update.py"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release = root / "release with spaces"
            env = release / "venv"
            venv.EnvBuilder(with_pip=False, symlinks=True).create(env)
            launcher = release / "studio-python"
            update["studio_launcher"](launcher, env / "bin/python")
            alias = root / "are-softwaregpu-python"
            alias.symlink_to(launcher)
            prefix = subprocess.check_output([str(alias), "-c", "import sys;print(sys.prefix)"], text=True)
            self.assertEqual(Path(prefix.strip()), env)
