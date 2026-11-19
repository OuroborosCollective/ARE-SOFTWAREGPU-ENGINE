"""Public PyPI distribution contract tests; fixture archives are not release evidence."""
import ast
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from zipfile import ZipFile

from tools import release_gate
from tools import pypi_index_readback


ROOT = Path(__file__).resolve().parents[2]
DIST = "ouroboroscollective_softwaregpu"
PROJECT = "ouroboroscollective-softwaregpu"
VERSION = "1.2.0"


def make_wheel(folder, *, name=DIST, version=VERSION, include_notice=True):
    target = Path(folder) / f"{name}-{version}-py3-none-any.whl"
    with ZipFile(target, "w") as archive:
        meta = f"{name}-{version}.dist-info"
        archive.writestr(f"{meta}/METADATA",
                         f"Metadata-Version: 2.3\nName: {PROJECT}\nVersion: {version}\n")
        archive.writestr(f"{meta}/licenses/LICENSE.md", "PolyForm Noncommercial 1.0.0")
        if include_notice:
            archive.writestr(f"{meta}/licenses/NOTICE",
                             "Required Notice: Copyright (c) 2026 OuroborosCollective")
        archive.writestr(f"{meta}/entry_points.txt", "[console_scripts]\nsoftware-gpu = main:main\n")
        archive.writestr("software_gpu/__init__.py", "__version__ = '1.2.0'")
        archive.writestr("main.py", "def main(): pass\n")
    return target


def make_sdist(folder, *, version=VERSION, include_notice=True):
    base = f"{DIST}-{version}"
    target = Path(folder) / f"{base}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        paths = {
            "setup.py": b"from setuptools import setup\nsetup()\n",
            "LICENSE.md": b"PolyForm Noncommercial",
            "docs/PYPI_PACKAGE.md": b"# ARE SoftwareGPU",
            "software_gpu/__init__.py": b"__version__ = '1.2.0'",
            "main.py": b"def main(): pass\n",
            "PKG-INFO": f"Metadata-Version: 2.3\nName: {PROJECT}\nVersion: {version}\n".encode(),
        }
        if include_notice:
            paths["NOTICE"] = b"Required Notice: Copyright (c) 2026 OuroborosCollective"
        for name, data in paths.items():
            item = tarfile.TarInfo(f"{base}/{name}")
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    return target


class PublicPackageContractTests(unittest.TestCase):
    def test_public_name_and_license_are_branded_not_generic(self):
        doc = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn('name="ouroboroscollective-softwaregpu"', doc)
        self.assertIn("PolyForm-Noncommercial-1.0.0", doc)
        self.assertIn("https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE", doc)
        self.assertIn("project_urls", doc)
        self.assertIn("license_files", doc)

    def test_wheel_requires_correct_package_and_reproducible_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            good = make_wheel(folder)
            release_gate.verify_wheel(good, "v1.2.0")
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_wheel(good, "v1.2.1")
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_wheel(make_wheel(folder, include_notice=False), "v1.2.0")
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_wheel(make_wheel(folder, name="untrusted_other"), "v1.2.0")

    def test_sdist_requires_notice_version_source_and_safe_members(self):
        with tempfile.TemporaryDirectory() as folder:
            good = make_sdist(folder)
            release_gate.verify_sdist(good, "v1.2.0")
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_sdist(good, "v1.2.1")
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_sdist(make_sdist(folder, include_notice=False), "v1.2.0")
            unsafe = Path(folder) / f"{DIST}-1.2.0.tar.gz"
            with tarfile.open(unsafe, "w:gz") as archive:
                item = tarfile.TarInfo(f"{DIST}-1.2.0/../../pwned")
                item.size = 1
                archive.addfile(item, io.BytesIO(b"!"))
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_sdist(unsafe, "v1.2.0")

    def test_pypi_readback_matches_both_local_distribution_digests(self):
        with tempfile.TemporaryDirectory() as folder:
            wheel = make_wheel(folder)
            sdist = make_sdist(folder)
            urls = [
                {"filename": f.name, "digests": {"sha256": hashlib.sha256(f.read_bytes()).hexdigest()}}
                for f in (wheel, sdist)
            ]
            payload = {"info": {"name": PROJECT, "version": VERSION}, "urls": urls}
            pypi_index_readback.validate_registry_payload(payload, (wheel, sdist), VERSION)
            payload["urls"][0]["digests"]["sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                pypi_index_readback.validate_registry_payload(payload, (wheel, sdist), VERSION)

    def test_release_workflow_has_exact_sha_ci_gate_then_oidc_publishing(self):
        content = (ROOT / ".github/workflows/goreleaser.yml").read_text(encoding="utf-8")
        self.assertIn("publish-pypi:", content)
        self.assertIn("needs: publish", content)
        self.assertIn("environment: pypi", content)
        self.assertIn("id-token: write", content)
        self.assertIn("pypa/gh-action-pypi-publish@release/v1", content)
        self.assertIn("tools/pypi_index_readback.py", content)
        self.assertIn("git merge-base --is-ancestor", content)
        self.assertNotIn("skip-existing: true", content)

    def test_source_package_will_not_claim_native_cpp_is_embedded(self):
        page = (ROOT / "docs/PYPI_PACKAGE.md").read_text(encoding="utf-8")
        self.assertIn("C++17", page)
        self.assertIn("not included", page)
        self.assertIn("Noncommercial", page)
        self.assertIn("pip install ouroboroscollective-softwaregpu", page)


if __name__ == "__main__":
    unittest.main()
