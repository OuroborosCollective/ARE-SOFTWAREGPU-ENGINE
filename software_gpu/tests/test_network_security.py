"""Real loopback security regressions: socket, HTTP, worker and payload boundaries."""
import http.client
import json
import secrets
import socket
import struct
import threading
import time
import unittest

from software_gpu.network.server import SoftwareGPUServer
from software_gpu.network.protocol import pack_message, unpack_header, HEADER_SIZE, MsgType
from software_gpu.network.security import SecurityLimits, RequestRejected, validate_request


class TestSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret = secrets.token_urlsafe(40)
        cls.server = SoftwareGPUServer(http_port=0, tcp_port=0, auth_token=cls.secret)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def http(self, path="/health", method="GET", body=None, token=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.http_port, timeout=20)
        hdr = {} if headers is None else dict(headers)
        if token is not None:
            hdr["Authorization"] = "Bearer " + token
        if body is not None:
            hdr["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=body, headers=hdr)
            resp = conn.getresponse()
            return resp.status, resp.getheaders(), json.loads(resp.read())
        finally:
            conn.close()

    def test_missing_wrong_token_and_no_cors(self):
        for token in (None, "invalid", self.secret + "x"):
            status, headers, payload = self.http(token=token)
            self.assertEqual(status, 401)
            self.assertEqual(payload["error"], "UNAUTHORIZED")
            self.assertFalse(any(k.lower() == "access-control-allow-origin" for k, _ in headers))
        self.assertEqual(self.http(method="OPTIONS")[0], 405)

    def test_real_authenticated_health_and_gemm(self):
        status, _, data = self.http(token=self.secret)
        self.assertEqual(status, 200)
        self.assertIn("gpu", data)
        body = json.dumps({"a": [[1, 2], [3, 4]], "b": [[5, 6], [7, 8]]})
        status, _, data = self.http("/api/v1/compute/gemm", "POST", body, self.secret)
        self.assertEqual(status, 200, data)
        self.assertTrue(data["success"])

    def test_reject_oversize_json_and_integer(self):
        body = " " * (SecurityLimits().max_request_bytes + 1)
        status, _, data = self.http("/rpc", "POST", body, self.secret)
        self.assertEqual(status, 413)
        self.assertEqual(data["error"], "REQUEST_SIZE_LIMIT")
        status, _, data = self.http("/rpc", "POST", '{"jsonrpc":"2.0","method":"activation","params":{"x":[NaN]}}', self.secret)
        self.assertEqual(status, 400)
        self.assertNotIn("NaN", json.dumps(data))

    def test_dimension_rejection_before_numpy_allocation(self):
        policy = SecurityLimits()
        with self.assertRaises(RequestRejected):
            validate_request("gemm", {"a": [[1,2]], "b": [[1],[2],[3]]}, policy)
        with self.assertRaises(RequestRejected):
            validate_request("render_mesh", {"width": 10000000, "height": 10000000}, policy)
        with self.assertRaises(RequestRejected):
            validate_request("activation", {"x": {"__tensor__":True, "shape":[10**9],
                "dtype":"float32", "data_b64":""}}, policy)

    def test_nonloopback_and_missing_key_refused(self):
        with self.assertRaisesRegex(ValueError, "REMOTE_BIND_FORBIDDEN"):
            SoftwareGPUServer(host="0.0.0.0", auth_token=self.secret)
        with self.assertRaises(ValueError):
            SoftwareGPUServer(auth_token="short")

    def test_tcp_unauthorized_and_authenticated(self):
        def send(doc):
            with socket.create_connection(("127.0.0.1", self.server.tcp_port), timeout=4) as client:
                client.settimeout(15)
                client.sendall(pack_message(MsgType.JSON_REQUEST, doc))
                header = client.recv(HEADER_SIZE)
                self.assertEqual(len(header), HEADER_SIZE)
                kind, flags, length = unpack_header(header)
                payload = b""
                while len(payload) < length:
                    payload += client.recv(length - len(payload))
                return kind, json.loads(payload)
        kind, result = send({"method": "device_info", "params": {}})
        self.assertEqual(kind, MsgType.ERROR)
        self.assertEqual(result["error"], "UNAUTHORIZED")
        kind, result = send({"method": "device_info", "params": {}, "token": self.secret})
        self.assertEqual(kind, MsgType.JSON_RESPONSE)
        self.assertIn("result", result)

    def test_tcp_large_unsigned_length_cannot_allocate(self):
        with socket.create_connection(("127.0.0.1", self.server.tcp_port), timeout=4) as client:
            client.settimeout(4)
            client.sendall(struct.pack("!4sIIQ", b"SGPU", 1, 0, 2**64-1))
            self.assertEqual(client.recv(1), b"")

    def test_deadline_kills_spawned_worker(self):
        from software_gpu.network.isolated_worker import IsolatedExecutor
        tiny = SecurityLimits(worker_timeout_seconds=.01)
        with self.assertRaisesRegex(RequestRejected, "WORKER_DEADLINE_EXCEEDED"):
            IsolatedExecutor(tiny).execute("device_info", {})

    def test_reject_nonfinite_encoded_tensor(self):
        import numpy as np
        from software_gpu.network.protocol import encode_tensor_base64, decode_tensor_base64
        encoded = encode_tensor_base64(np.array([float("nan")], dtype=np.float32))
        with self.assertRaisesRegex(ValueError, "NONFINITE_TENSOR"):
            decode_tensor_base64(encoded)

    def test_job_capacity_guard(self):
        self.assertTrue(self.server.policy.jobs.acquire(False))
        self.assertTrue(self.server.policy.jobs.acquire(False))
        try:
            status, _, data = self.http(token=self.secret)
            self.assertEqual(status, 429)
            self.assertEqual(data["error"], "CAPACITY_EXHAUSTED")
        finally:
            self.server.policy.jobs.release()
            self.server.policy.jobs.release()


if __name__ == "__main__":
    unittest.main()
