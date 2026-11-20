#!/usr/bin/env python3
"""Install a real built Python wheel outside checkout; works on Linux/Windows."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

from release_gate import verify_wheel, verify_sdist, wheel_version


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
        forge = cli.with_name("are-worldforge.exe" if sys.platform == "win32" else "are-worldforge")
        installed = subprocess.check_output([str(forge), "--version"], cwd=root, text=True).strip()
        if installed != wheel_version(tag):
            raise ValueError("Installed World Forge CLI version differs from the verified tag")
    print("REAL_WHEEL_INSTALL_API_CLI_OK: " + sys.platform)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--tag", default=None)
    args = parser.parse_args()
    paths = list(args.dist.resolve(strict=True).glob("*.whl"))
    if len(paths) != 1:
        raise ValueError("EXPECTED_ONE_BUILT_WHEEL")
    version = paths[0].name.removeprefix("ouroboroscollective_softwaregpu-").split("-", 1)[0]
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?", version)
    if match is None:
        raise ValueError("WHEEL_PEP440_VERSION_INVALID")
    suffix = "" if match[2] is None else "-{}.{}".format(
        {"a": "alpha", "b": "beta", "rc": "rc"}[match[2]], match[3])
    derived_tag = "v" + match[1] + suffix
    if args.tag is not None and args.tag != derived_tag:
        raise ValueError("EXPLICIT_TAG_WHEEL_MISMATCH")
    if wheel_version(derived_tag) != version:
        raise ValueError("WHEEL_TAG_VERSION_MISMATCH")
    verify_install(args.dist.resolve(strict=True), derived_tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
