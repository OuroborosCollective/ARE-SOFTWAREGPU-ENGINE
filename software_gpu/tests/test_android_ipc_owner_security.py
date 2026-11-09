"""Real AF_UNIX security regressions for #235, independent of the Android device gate."""
import os
import socket
import stat
import tempfile
import time
import unittest
from pathlib import Path

from software_gpu.mobile.android_server import AndroidIPCServer
from software_gpu.network.protocol import HEADER_SIZE, MsgType, pack_message, unpack_header


@unittest.skipUnless(os.name == "posix" and hasattr(socket, "SO_PEERCRED"),
                     "Linux peer credentials required; Android device proof is separate")
class AndroidOwnerBoundIpcTest(unittest.TestCase):
    def _wait_ready(self, server):
        for _ in range(100):
            if server.startup_error is not None:
                self.fail("IPC startup rejected: " + str(server.startup_error))
            if server.ready.is_set():
                return
            time.sleep(0.01)
        self.fail("IPC listener did not become ready")

    def _request(self, path):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(str(path))
            s.sendall(pack_message(MsgType.JSON_REQUEST, {
                "method": "device_info", "params": {}, "id": 17,
            }))
            head = bytearray()
            while len(head) < HEADER_SIZE:
                part = s.recv(HEADER_SIZE - len(head))
                self.assertTrue(part)
                head.extend(part)
            kind, _, size = unpack_header(bytes(head))
            payload = bytearray()
            while len(payload) < size:
                part = s.recv(size - len(payload))
                self.assertTrue(part)
                payload.extend(part)
            return kind, bytes(payload)

    def test_same_uid_secure_socket_and_clean_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ipc.sock"
            server = AndroidIPCServer(socket_path=str(path), abstract_name=None)
            try:
                server.start()
                self._wait_ready(server)
                self.assertEqual(stat.S_IMODE(os.lstat(path).st_mode), 0o600)
                self.assertEqual(os.lstat(path).st_uid, os.geteuid())
                kind, payload = self._request(path)
                self.assertEqual(kind, MsgType.JSON_RESPONSE)
                self.assertIn(b'"id": 17', payload)
            finally:
                server.stop()
                server.join(timeout=2)
            self.assertFalse(path.exists())

    def test_world_writable_parent_fails_closed_without_removing_foreign_file(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o777)
            path = Path(directory) / "ipc.sock"
            path.write_bytes(b"original")
            server = AndroidIPCServer(socket_path=str(path), abstract_name=None)
            server.start()
            server.join(timeout=2)
            self.assertIsNotNone(server.startup_error)
            self.assertEqual(path.read_bytes(), b"original")
            server.stop()

    def test_symlink_parent_and_existing_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            private.mkdir(mode=0o700)
            (Path(directory) / "alias").symlink_to(private, target_is_directory=True)
            for path in (Path(directory) / "alias" / "ipc.sock",
                         private / "ipc.sock"):
                if path.parent == private:
                    path.symlink_to(private / "other")
                server = AndroidIPCServer(socket_path=str(path), abstract_name=None)
                server.start()
                server.join(timeout=2)
                self.assertIsNotNone(server.startup_error)
                server.stop()
            self.assertTrue((private / "ipc.sock").is_symlink())

    def test_dotdot_path_cannot_bypass_private_parent_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            private.mkdir(mode=0o700)
            noncanonical = str(private / ".." / "ipc.sock")
            server = AndroidIPCServer(socket_path=noncanonical, abstract_name=None)
            server.start()
            server.join(timeout=2)
            self.assertIsNotNone(server.startup_error)
            self.assertFalse((Path(directory) / "ipc.sock").exists())
            server.stop()

    def test_rejects_different_expected_uid_before_request_dispatch(self):
        a, b = socket.socketpair(socket.AF_UNIX)
        server = AndroidIPCServer(abstract_name=None, owner_uid=os.geteuid() + 1)
        try:
            server._running = True
            server._handle_client(a)
            b.settimeout(1)
            self.assertEqual(b.recv(1), b"")
        finally:
            server._running = False
            b.close()

    def test_default_listener_is_disabled_until_private_path_is_supplied(self):
        server = AndroidIPCServer()
        server.start()
        server.join(timeout=2)
        self.assertIsNotNone(server.startup_error)
        self.assertEqual(server._sockets, [])
        server.stop()


if __name__ == "__main__":
    unittest.main()
