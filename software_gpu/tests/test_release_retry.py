"""Registry transport doubles are control-flow tests, not PyPI runtime evidence."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import pypi_index_readback, release_gate
from software_gpu.tests.test_public_package_release import make_wheel, make_sdist


class RegistryResponse(io.BytesIO):
    status = 200


class ReleaseRetryTests(unittest.TestCase):
    def execute(self, root, response):
        output = root / "github-output.txt"
        args = ["readback", "--version", "1.2.0", "--dist", str(root / "dist"),
                "--probe-existing", "--github-output", str(output)]
        transport = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
        with patch.object(sys, "argv", args), patch.dict(sys.modules, {"release_gate": release_gate}), \
                patch.object(pypi_index_readback, "urlopen", **transport), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            code = pypi_index_readback.main()
        return code, output.read_text() if output.exists() else None

    def make_dist(self, root):
        target = root / "dist"; target.mkdir()
        files = [make_wheel(target), make_sdist(target)]
        return {"info": {"name": pypi_index_readback.PROJECT, "version": "1.2.0"},
                "urls": [{"filename": path.name, "digests": {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}} for path in files]}

    def test_http404_explicitly_allows_first_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); self.make_dist(root)
            code, output = self.execute(root, HTTPError("https://pypi.org", 404, "missing", {}, None))
            self.assertEqual((0, "exists=false\n"), (code, output))

    def test_already_uploaded_identical_bytes_skip_duplicate_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); data = self.make_dist(root)
            code, output = self.execute(root, RegistryResponse(json.dumps(data).encode()))
            self.assertEqual((0, "exists=true\n"), (code, output))

    def test_unauthorized_transport_error_and_changed_bytes_never_authorize_upload(self):
        for mode in ("unauthorized", "network", "digest"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); data = self.make_dist(root)
                if mode == "unauthorized":
                    response = HTTPError("https://pypi.org", 401, "unauthorized", {}, None)
                elif mode == "network":
                    response = TimeoutError("synthetic transport failure")
                else:
                    data["urls"][0]["digests"]["sha256"] = "0" * 64
                    response = RegistryResponse(json.dumps(data).encode())
                self.assertEqual((1, None), self.execute(root, response))


if __name__ == "__main__":
    unittest.main()
