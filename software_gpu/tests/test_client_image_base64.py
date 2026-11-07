"""Real loopback HTTP response test for strict Python client image Base64 admission."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from software_gpu.clients.python_client import SoftwareGPUClient


class TestClientImageBase64(unittest.TestCase):
    def test_render_mesh_rejects_invalid_base64_without_silent_byte_loss(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                body = json.dumps({"success": True, "data": {"image_b64": "YQ==!"}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            client = SoftwareGPUClient(http_port=server.server_port, token="local-test-token")
            with self.assertRaises((ValueError, base64.binascii.Error)):
                client.render_mesh([], [], {}, width=32, height=32)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
