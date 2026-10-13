"""Real Gradio UI/runtime smoke tests for the optional authenticated CPU panel.

The test is skipped in the lean install and run by the dedicated Gradio CI job.
No public endpoint or real secrets are used.
"""
import importlib.util
import os
import socket
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from plugins.gradio_arena.app import create_demo, execute, main

HAS_GRADIO = importlib.util.find_spec("gradio") is not None


@unittest.skipUnless(HAS_GRADIO, "optional gradio-arena extra not installed")
class TestPrivateGradioRuntime(unittest.TestCase):
    def test_single_real_render_callback_has_bounded_concurrency(self):
        demo = create_demo()
        funcs = [f for f in demo.fns.values() if f.fn is execute]
        self.assertEqual(len(funcs), 1)
        self.assertEqual(funcs[0].concurrency_limit, 1)
        self.assertEqual(funcs[0].concurrency_id, "are-softwaregpu-cpu")
        config = demo.get_config_file()
        labels = {c.get("props", {}).get("label") for c in config["components"]}
        self.assertIn("Deterministic mesh seed", labels)
        self.assertIn("Actual CPU framebuffer", labels)
        self.assertIn("Worker receipt / hashes / CPU timings", labels)

    def test_main_keeps_authentication_and_loopback(self):
        with mock.patch.dict(os.environ, {"ARE_GRADIO_USER": "owner",
                                          "ARE_GRADIO_PASSWORD": "local-ci-demo-password-123"},
                             clear=True):
            with mock.patch("gradio.blocks.Blocks.launch") as launch:
                main()
        options = launch.call_args.kwargs
        self.assertEqual(options["server_name"], "127.0.0.1")
        self.assertFalse(options["share"])
        self.assertEqual(options["auth"], ("owner", "local-ci-demo-password-123"))
        self.assertEqual(options["allowed_paths"], [])

    def test_real_http_listener_rejects_unauthenticated_compute(self):
        demo = create_demo().queue(max_size=3, default_concurrency_limit=1)
        # A real loopback port, freed immediately before launch.
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        try:
            _, url, shared = demo.launch(
                server_name="127.0.0.1", server_port=port, share=False,
                auth=("owner", "local-ci-demo-password-123"),
                prevent_thread_lock=True, quiet=True, show_error=False,
                allowed_paths=[])
            self.assertFalse(shared)
            self.assertIn("127.0.0.1", url)
            with urlopen(url, timeout=15) as response:
                self.assertEqual(response.status, 200)
            for endpoint, method, payload in [
                ("/config", "GET", None),
                ("/gradio_api/run/execute", "POST", b'{"data":[686,64,"tiles"]}')]:
                with self.subTest(endpoint=endpoint):
                    request = Request(url.rstrip("/") + endpoint,
                                      method=method, data=payload)
                    if payload is not None:
                        request.add_header("Content-Type", "application/json")
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(request, timeout=15)
                    self.assertEqual(caught.exception.code, 401)
        finally:
            demo.close()


if __name__ == "__main__":
    unittest.main()
