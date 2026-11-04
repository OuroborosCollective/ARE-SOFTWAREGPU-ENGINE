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


if __name__ == "__main__":
    unittest.main()
