"""Real Unix socket regression for Android IPC wire validation (no mock dispatcher)."""
import json
import os
import socket
import struct
import threading
import unittest

from software_gpu.mobile.android_server import AndroidIPCServer
from software_gpu.network.protocol import (
    HEADER_SIZE, MAGIC_HEADER, MsgType, pack_message, unpack_header,
)
from software_gpu.network.security import SecurityLimits


@unittest.skipUnless(os.name == "posix" and hasattr(socket, "AF_UNIX"), "Unix IPC")
class AndroidIpcValidationTest(unittest.TestCase):
    def setUp(self):
        self.server = AndroidIPCServer(abstract_name=None)
        self.server._running = True
        self.server_socket, self.client = socket.socketpair(socket.AF_UNIX)
        self.client.settimeout(2)
        self.thread = threading.Thread(target=self.server._handle_client, args=(self.server_socket,), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server._running = False
        self.client.close()
        self.thread.join(timeout=2)

    def receive_exact(self, size):
        buf = bytearray()
        while len(buf) < size:
            data = self.client.recv(size - len(buf))
            self.assertNotEqual(data, b"", "Unexpected socket EOF")
            buf.extend(data)
        return bytes(buf)

    def response(self):
        msg_type, flags, size = unpack_header(self.receive_exact(HEADER_SIZE))
        payload = json.loads(self.receive_exact(size).decode("utf-8"))
        return msg_type, payload

    def test_real_valid_request(self):
        self.client.sendall(pack_message(MsgType.JSON_REQUEST, {"method": "device_info", "params": {}, "id": 9}))
        kind, body = self.response()
        self.assertEqual(kind, MsgType.JSON_RESPONSE)
        self.assertEqual(body["id"], 9)
        self.assertIn("name", body["result"])

    def test_predecode_rejects_oversized_payload_length_without_body(self):
        # 262145 is below the generic 1MiB frame cap but exceeds the stricter UDS request cap.
        size = SecurityLimits().max_request_bytes + 1
        self.client.sendall(struct.pack("!4sIIQ", MAGIC_HEADER, MsgType.JSON_REQUEST, 0, size))
        kind, body = self.response()  # must not wait for the undeclared body
        self.assertEqual(kind, MsgType.ERROR)
        self.assertEqual(body["error"], "REQUEST_SIZE_LIMIT")
        self.assertEqual(self.client.recv(1), b"", "Rejected unread frame must close UDS")

    def test_json_list_is_rejected_not_crashed(self):
        self.client.sendall(pack_message(MsgType.JSON_REQUEST, [1, 2]))
        kind, body = self.response()
        self.assertEqual(kind, MsgType.ERROR)
        self.assertEqual(body["error"], "REQUEST_INVALID")

    def test_invalid_json_does_not_crash_socket_loop(self):
        payload = b'{"method":'
        self.client.sendall(struct.pack("!4sIIQ", MAGIC_HEADER, MsgType.JSON_REQUEST, 0, len(payload)) + payload)
        kind, body = self.response()
        self.assertEqual(kind, MsgType.ERROR)
        self.assertEqual(body["error"], "REQUEST_INVALID")
        # The body was fully consumed, so this connection may safely be reused.
        self.client.sendall(pack_message(MsgType.JSON_REQUEST, {
            "method": "device_info", "params": {}, "id": 17,
        }))
        kind, valid = self.response()
        self.assertEqual(kind, MsgType.JSON_RESPONSE)
        self.assertEqual(valid["id"], 17)

    def test_nonfinite_json_rejected_before_dispatch(self):
        payload = b'{"method":"device_info","params":{"x":NaN}}'
        self.client.sendall(struct.pack("!4sIIQ", MAGIC_HEADER, MsgType.JSON_REQUEST, 0, len(payload)) + payload)
        kind, body = self.response()
        self.assertEqual(kind, MsgType.ERROR)
        self.assertEqual(body["error"], "REQUEST_INVALID")

    def test_wrong_message_type_rejected(self):
        self.client.sendall(pack_message(MsgType.JSON_RESPONSE, {"method": "device_info", "params": {}}))
        kind, body = self.response()
        self.assertEqual(kind, MsgType.ERROR)
        self.assertEqual(body["error"], "MESSAGE_TYPE_NOT_ALLOWED")
        # A peer with unread request bytes may observe either an orderly EOF
        # or ECONNRESET when the server closes its Unix stream socket.
        try:
            trailing = self.client.recv(1)
        except ConnectionResetError:
            trailing = b""
        self.assertEqual(trailing, b"", "Rejected wrong-type frame must close UDS")

    def test_overflowing_exponent_id_rejected_before_dispatch(self):
        payload = b'{"method":"device_info","params":{},"id":1e999}'
        self.client.sendall(struct.pack("!4sIIQ", MAGIC_HEADER, MsgType.JSON_REQUEST, 0, len(payload)) + payload)
        kind, body = self.response()
        self.assertEqual(kind, MsgType.ERROR)
        self.assertEqual(body["error"], "NONFINITE_NUMBER")
        self.client.sendall(pack_message(MsgType.JSON_REQUEST, {"method": "device_info", "params": {}, "id": 23}))
        kind, body = self.response()
        self.assertEqual(kind, MsgType.JSON_RESPONSE)
        self.assertEqual(body["id"], 23)

    def test_invalid_utf8_and_extra_json_are_generic_errors(self):
        for payload in (b'\xff', b'{"method":"device_info"} trailing'):
            self.client.sendall(struct.pack("!4sIIQ", MAGIC_HEADER, MsgType.JSON_REQUEST, 0, len(payload)) + payload)
            kind, body = self.response()
            self.assertEqual(kind, MsgType.ERROR)
            self.assertEqual(body["error"], "REQUEST_INVALID")

    def test_idle_socket_timeout_closes_without_unsolicited_response(self):
        # Real I/O timeout; a server-generated unsolicited ERROR would return data.
        self.client.settimeout(5)
        self.assertEqual(self.client.recv(1), b"", "idle timeout must close without a response")

    def test_rejected_nonfinite_param_keeps_safe_request_id(self):
        payload = b'{"method":"device_info","params":{"x":1e999},"id":7}'
        self.client.sendall(struct.pack("!4sIIQ", MAGIC_HEADER, MsgType.JSON_REQUEST, 0, len(payload)) + payload)
        kind, body = self.response()
        self.assertEqual(kind, MsgType.ERROR)
        self.assertEqual(body["error"], "NONFINITE_NUMBER")
        self.assertEqual(body["id"], 7)

    def test_invalid_request_ids_are_not_echoed_or_dispatched(self):
        for invalid in (b'1e999', b'{"nested":7}', b'true'):
            payload = b'{"method":"device_info","params":{},"id":' + invalid + b'}'
            self.client.sendall(struct.pack("!4sIIQ", MAGIC_HEADER, MsgType.JSON_REQUEST, 0, len(payload)) + payload)
            kind, body = self.response()
            self.assertEqual(kind, MsgType.ERROR)
            self.assertIsNone(body["id"])
        self.client.sendall(pack_message(MsgType.JSON_REQUEST, {"method": "device_info", "params": {}, "id": 31}))
        kind, body = self.response()
        self.assertEqual(kind, MsgType.JSON_RESPONSE)
        self.assertEqual(body["id"], 31)


if __name__ == "__main__":
    unittest.main()
