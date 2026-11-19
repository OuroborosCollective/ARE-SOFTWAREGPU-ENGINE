#!/usr/bin/env python3
"""Install a real built Python wheel outside checkout; works on Linux/Windows."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

from release_gate import verify_wheel, verify_sdist


def run(*argv: str, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, timeout=300)


def verify_install(dist: Path, tag: str) -> None:
    artifacts = list(dist.iterdir())
    if len(artifacts) != 2 or not all(path.is_file() for path in artifacts):
        raise ValueError("DIST_MUST_CONTAIN_WHEEL_AND_SDIST_ONLY")
    wheel, = [p for p in artifacts if p.suffix == ".whl"]
    sdist, = [p for p in artifacts if p.name.endswith(".tar.gz")]
    verify_wheel(wheel, tag)
    verify_sdist(sdist, tag)
    with tempfile.TemporaryDirectory(prefix="are-real-wheel-install-") as tmp:
        root = Path(tmp).resolve()
        environment = root / "venv"
        venv.create(environment, with_pip=True)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32"
                                else "bin/python")
        cli = environment / ("Scripts/software-gpu.exe" if sys.platform == "win32"
                             else "bin/software-gpu")
        run(str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-cache-dir", str(wheel.resolve()), cwd=root)
        run(str(python), "-I", "-c",
            "import software_gpu; from software_gpu import SoftwareRasterizer; "
            "import importlib.metadata as m; "
            "assert m.version('ouroboroscollective-softwaregpu') == software_gpu.__version__",
            cwd=root)
        run(str(cli), "--help", cwd=root)
    print("REAL_WHEEL_INSTALL_API_CLI_OK: " + sys.platform)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--tag", default="v1.2.0")
    args = parser.parse_args()
    verify_install(args.dist.resolve(strict=True), args.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
