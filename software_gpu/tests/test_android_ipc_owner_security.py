"""Real AF_UNIX security regressions for #235, independent of the Android device gate."""
import os
import socket
import subprocess
import sys
import stat
import tempfile
import time
import unittest
from pathlib import Path

from software_gpu.mobile.android_server import AndroidIPCServer
from software_gpu.network.protocol import HEADER_SIZE, MsgType, pack_message, unpack_header
from software_gpu.network.security import SecurityLimits


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

    def test_real_concurrent_client_quota_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ipc.sock"
            server = AndroidIPCServer(socket_path=str(path))
            clients = []
            request = pack_message(MsgType.JSON_REQUEST, {
                "method": "device_info", "params": {}, "id": 17,
            })

            def connect():
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    client.settimeout(2)
                    client.connect(str(path))
                    return client
                except BaseException:
                    client.close()
                    raise

            def receive_exact(client, size):
                result = bytearray()
                while len(result) < size:
                    part = client.recv(size - len(result))
                    self.assertTrue(part, "unexpected EOF from admitted client")
                    result.extend(part)
                return bytes(result)

            try:
                server.start()
                self._wait_ready(server)
                # A successful reply proves each real socket has acquired a
                # listener slot; keep it open while the other clients arrive.
                for _ in range(SecurityLimits().max_clients):
                    client = connect()
                    clients.append(client)
                    client.sendall(request)
                    kind, _, size = unpack_header(receive_exact(client, HEADER_SIZE))
                    self.assertEqual(kind, MsgType.JSON_RESPONSE)
                    self.assertIn(b'"id": 17', receive_exact(client, size))
                with connect() as extra:
                    try:
                        extra.sendall(request)
                        reply = extra.recv(1)
                    except (ConnectionResetError, BrokenPipeError):
                        reply = b""
                    self.assertEqual(reply, b"", "excess real client received data")
                clients.pop().close()
                # Do not rely on listener scheduling or fake semaphore counts.
                deadline = time.monotonic() + 1
                while True:
                    try:
                        kind, payload = self._request(path)
                    except (AssertionError, ConnectionResetError, BrokenPipeError):
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.01)
                        continue
                    self.assertEqual(kind, MsgType.JSON_RESPONSE)
                    self.assertIn(b'"id": 17', payload)
                    break
            finally:
                for client in clients:
                    client.close()
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

    def test_writable_ancestor_rejected_even_with_private_final_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            ancestor = Path(directory) / "shared"
            ancestor.mkdir(mode=0o777)
            ancestor.chmod(0o777)
            private = ancestor / "private"
            private.mkdir(mode=0o700)
            path = private / "ipc.sock"
            server = AndroidIPCServer(socket_path=str(path))
            try:
                server.start()
                server.join(timeout=2)
                self.assertEqual(server.startup_error, "UDS_ANCESTOR_NOT_TRUSTED")
                self.assertFalse(path.exists())
            finally:
                server.stop()

    @unittest.skipUnless(getattr(os, "geteuid", lambda: -1)() == 0,
                         "requires root only to drop child UID on an isolated Linux runner")
    def test_real_distinct_uid_filesystem_and_abstract_socket(self):
        foreign_uid = 65534
        self.assertNotEqual(os.geteuid(), foreign_uid)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ipc.sock"
            name = "are-uid-" + Path(directory).name
            server = AndroidIPCServer(socket_path=str(path), abstract_name=name)
            request = pack_message(MsgType.JSON_REQUEST, {
                "method": "device_info", "params": {}, "id": 17,
            })
            child = """
import os, socket, sys
uid, transport, address, request = sys.argv[1:]
uid = int(uid)
assert os.getuid() == os.geteuid() == uid
assert os.getgid() == os.getegid() == uid
assert not os.getgroups()
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.settimeout(3)
    if transport == 'filesystem':
        try:
            sock.connect(address)
        except PermissionError:
            print('filesystem-denied')
        else:
            raise AssertionError('foreign UID reached private filesystem socket')
    else:
        sock.connect(bytes.fromhex(address))
        try:
            sock.sendall(bytes.fromhex(request))
            reply = sock.recv(1)
        except (ConnectionResetError, BrokenPipeError):
            reply = b''
        assert reply == b'', 'foreign UID received a response'
        print('abstract-peer-denied')
"""
            try:
                server.start()
                self._wait_ready(server)
                for address in (str(path), "\0" + name):
                    kind, payload = self._request(address)
                    self.assertEqual(kind, MsgType.JSON_RESPONSE)
                    self.assertIn(b'"id": 17', payload)
                for transport, address, expected in (
                    ("filesystem", str(path), "filesystem-denied"),
                    ("abstract", ("\0" + name).encode().hex(), "abstract-peer-denied"),
                ):
                    result = subprocess.run(
                        [sys.executable, "-I", "-c", child, str(foreign_uid),
                         transport, address, request.hex()],
                        user=foreign_uid, group=foreign_uid, extra_groups=[],
                        cwd="/", env={"PATH": os.defpath}, capture_output=True,
                        text=True, timeout=8, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)
                kind, payload = self._request(str(path))
                self.assertEqual(kind, MsgType.JSON_RESPONSE)
                self.assertIn(b'"id": 17', payload)
            finally:
                server.stop()
                server.join(timeout=2)
            self.assertFalse(path.exists())
            # A second bind must eventually succeed on the exact abstract name.
            # Listener shutdown can take one accept timeout to release it.
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as check:
                for _ in range(50):
                    try:
                        check.bind("\0" + name)
                        break
                    except OSError as exc:
                        import errno
                        if exc.errno != errno.EADDRINUSE:
                            raise
                        time.sleep(.02)
                else:
                    self.fail("abstract socket not released")

    @unittest.skipUnless(getattr(os, "geteuid", lambda: -1)() == 0,
                         "requires root to create an isolated foreign-owned fixture")
    def test_foreign_owned_ancestor_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ancestor = Path(directory) / "foreign"
            ancestor.mkdir(mode=0o755)
            os.chown(ancestor, 65534, 65534)
            private = ancestor / "private"
            private.mkdir(mode=0o700)
            path = private / "ipc.sock"
            server = AndroidIPCServer(socket_path=str(path))
            try:
                server.start()
                server.join(timeout=2)
                self.assertEqual(server.startup_error, "UDS_ANCESTOR_NOT_TRUSTED")
                self.assertFalse(path.exists())
            finally:
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
