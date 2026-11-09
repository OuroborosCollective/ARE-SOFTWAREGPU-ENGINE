"""
Android & Mobile Low-Latency GPU Server Subsystem.
Implements Unix Domain Sockets (UDS) and Linux Abstract Namespace Sockets (`\0software_gpu`)
to provide zero-permission, ultra-fast IPC for native Android NDK apps and Android services.
"""

import os
import socket
import stat
import struct
import threading
import json
from typing import Optional

from ..network.dispatcher import GPUCommandDispatcher
from ..network.protocol import unpack_header, pack_message, MsgType, HEADER_SIZE
from ..network.security import validate_request, SecurityLimits, bounded_json


def _reject_nonfinite(_value):
    raise ValueError("REQUEST_INVALID")


def _correlatable_id(value):
    """Echo only bounded JSON-RPC IDs, never arbitrary client objects."""
    if type(value) is str and len(value) <= 128:
        return value
    if type(value) is int and value.bit_length() <= 64:
        return value
    return None


class AndroidIPCServer(threading.Thread):
    """Owner-bound Linux/Android UDS worker; never an anonymous shared /tmp service."""

    def __init__(
        self,
        socket_path: Optional[str] = None,
        abstract_name: Optional[str] = None,
        dispatcher: Optional[GPUCommandDispatcher] = None,
        owner_uid: Optional[int] = None,
    ):
        super().__init__(daemon=True, name="Android_SoftGPU_IPC")
        self.socket_path = socket_path
        self.abstract_name = abstract_name
        self.owner_uid = os.geteuid() if owner_uid is None else owner_uid
        self.dispatcher = dispatcher or GPUCommandDispatcher()
        self._running = False
        self._sockets = []
        self._active_clients = threading.BoundedSemaphore(SecurityLimits().max_clients)
        self._owned_fs_socket = None
        self.ready = threading.Event()
        self.startup_error = None

    def _private_socket_path(self):
        """Reject shared/symlinked paths before bind; never unlink a preexisting object."""
        path = self.socket_path
        if not isinstance(path, str) or not os.path.isabs(path) or "\0" in path:
            raise ValueError("UDS_PRIVATE_ABSOLUTE_PATH_REQUIRED")
        if len(os.fsencode(path)) >= 104:
            raise ValueError("UDS_PATH_TOO_LONG")
        current = os.path.abspath(os.path.dirname(path))
        if not os.path.basename(path) or os.path.basename(path) in (".", ".."):
            raise ValueError("UDS_INVALID_NAME")
        # Every component is walked with lstat, so a symlinked private parent
        # cannot bypass the final parent owner/mode check.
        ancestor = current
        while True:
            info = os.lstat(ancestor)
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("UDS_PARENT_NOT_DIRECTORY")
            if os.path.islink(ancestor):
                raise ValueError("UDS_PARENT_SYMLINK")
            next_ancestor = os.path.dirname(ancestor)
            if ancestor == next_ancestor:
                break
            ancestor = next_ancestor
        info = os.lstat(current)
        if info.st_uid != self.owner_uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("UDS_PARENT_NOT_PRIVATE")
        # exists() is insufficient: it follows links and misses dangling symlinks.
        try:
            os.lstat(path)
        except FileNotFoundError:
            return path
        raise ValueError("UDS_PATH_ALREADY_EXISTS")

    def _verify_peer(self, sock):
        """Require kernel-attested Linux peer UID before reading framed bytes."""
        if not hasattr(socket, "SO_PEERCRED"):
            raise ValueError("UDS_PEERCRED_UNSUPPORTED")
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                              struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", raw)
        if uid != self.owner_uid:
            raise ValueError("UDS_PEER_UID_DENIED")

    def run(self):
        self.startup_error = None
        self.ready.clear()
        try:
            if os.name != "posix" or not hasattr(socket, "SO_PEERCRED"):
                raise ValueError("UDS_PEERCRED_UNSUPPORTED")
            if type(self.owner_uid) is not int or self.owner_uid != os.geteuid():
                raise ValueError("UDS_OWNER_UID_INVALID")
            if self.socket_path is None and self.abstract_name is None:
                raise ValueError("UDS_EXPLICIT_BIND_REQUIRED")
            if self.abstract_name is not None:
                name = self.abstract_name
                if (not isinstance(name, str) or not 1 <= len(name) <= 64
                        or not all(c.isascii() and (c.isalnum() or c in "_-")
                                   for c in name)):
                    raise ValueError("UDS_ABSTRACT_NAME_INVALID")
            path = self._private_socket_path() if self.socket_path is not None else None
            # The kernel peer check applies to abstract and filesystem sockets.
            if self.abstract_name is not None:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.bind("\0" + self.abstract_name)
                    sock.listen(SecurityLimits().max_clients)
                    sock.settimeout(0.2)
                    self._sockets.append(sock)
                except Exception:
                    sock.close()
                    raise
            if path is not None:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.bind(path)
                    # Record the kernel socket identity immediately after bind:
                    # even chmod/listen failure must clean only our own socket.
                    info = os.lstat(path)
                    self._owned_fs_socket = (info.st_dev, info.st_ino)
                    os.chmod(path, 0o600)
                    info = os.lstat(path)
                    if (not stat.S_ISSOCK(info.st_mode)
                            or info.st_uid != self.owner_uid
                            or stat.S_IMODE(info.st_mode) != 0o600):
                        raise ValueError("UDS_SOCKET_OWNERSHIP_INVALID")
                    self._owned_fs_socket = (info.st_dev, info.st_ino)
                    sock.listen(SecurityLimits().max_clients)
                    sock.settimeout(0.2)
                    self._sockets.append(sock)
                except Exception:
                    sock.close()
                    self._remove_owned_socket()
                    raise
            self._running = True
            for sock in self._sockets:
                threading.Thread(target=self._listen_loop, args=(sock,),
                                 daemon=True).start()
            self.ready.set()
        except Exception as exc:
            self.startup_error = str(exc) if isinstance(exc, ValueError) else "UDS_BIND_FAILED"
            self.stop()

    def _remove_owned_socket(self):
        if self.socket_path is None or self._owned_fs_socket is None:
            return
        try:
            info = os.lstat(self.socket_path)
            if (stat.S_ISSOCK(info.st_mode) and info.st_uid == self.owner_uid
                    and (info.st_dev, info.st_ino) == self._owned_fs_socket):
                os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        finally:
            self._owned_fs_socket = None

    def _listen_loop(self, sock):
        while self._running:
            try:
                client, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self._active_clients.acquire(blocking=False):
                client.close()
                continue

            def handle_and_release(connection):
                try:
                    self._handle_client(connection)
                finally:
                    self._active_clients.release()

            threading.Thread(target=handle_and_release, args=(client,),
                             daemon=True).start()

    def _handle_client(self, client_sock: socket.socket):
        limits = SecurityLimits()
        with client_sock:
            client_sock.settimeout(limits.io_timeout_seconds)
            try:
                self._verify_peer(client_sock)
            except (OSError, ValueError):
                return
            while self._running:
                req_id = None
                # Fail closed while any framed bytes remain unread. An invalid
                # header/type/length cannot be safely resynchronized.
                close_after_response = True
                try:
                    header_bytes = self._recv_all(client_sock, HEADER_SIZE)
                    if not header_bytes:
                        break
                    msg_type, flags, payload_len = unpack_header(header_bytes)
                    # The generic binary frame permits 1 MiB; UDS RPC has a
                    # stricter 262 KiB request policy, enforced BEFORE reading
                    # the body, JSON decoding, or allocating a tensor.
                    if payload_len > limits.max_request_bytes:
                        raise ValueError("REQUEST_SIZE_LIMIT")
                    if msg_type != MsgType.JSON_REQUEST or flags != 0:
                        raise ValueError("MESSAGE_TYPE_NOT_ALLOWED")
                    payload_bytes = self._recv_all(client_sock, payload_len)
                    if len(payload_bytes) != payload_len:
                        raise ValueError("REQUEST_INVALID")
                    # A fully consumed body can yield a JSON/schema error and
                    # still leave the next framed request at a valid boundary.
                    close_after_response = False
                    req = json.loads(payload_bytes.decode("utf-8"),
                                     parse_constant=_reject_nonfinite)
                    if type(req) is not dict:
                        raise ValueError("REQUEST_INVALID")
                    # Validate the entire document, including request ID, before
                    # constructing a response or invoking the dispatcher.
                    candidate_id = req.get("id")
                    req_id = _correlatable_id(candidate_id)
                    bounded_json(req)
                    if candidate_id is not None and req_id is None:
                        raise ValueError("REQUEST_INVALID")
                    method = req.get("method", "")
                    params = req.get("params", {})
                    validate_request(method, params, limits)
                    res_data = self.dispatcher.handle_request(method, params)
                    resp_bytes = pack_message(MsgType.JSON_RESPONSE, {"result": res_data, "id": req_id})
                except socket.timeout:
                    # An idle/incomplete read has no valid response correlation.
                    # Close rather than emitting an unsolicited error frame.
                    break
                except (json.JSONDecodeError, UnicodeError):
                    resp_bytes = pack_message(MsgType.ERROR, {"error": "REQUEST_INVALID", "id": req_id})
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    code = str(exc)
                    if not code or code.startswith("Expecting") or code.startswith("Invalid"):
                        code = "REQUEST_INVALID"
                    resp_bytes = pack_message(MsgType.ERROR, {"error": code, "id": req_id})
                except Exception:
                    # Unexpected dispatcher failure must not leak stack traces.
                    resp_bytes = pack_message(MsgType.ERROR, {"error": "REQUEST_FAILED", "id": req_id})
                try:
                    client_sock.sendall(resp_bytes)
                except OSError:
                    break
                if close_after_response:
                    break

    def _recv_all(self, sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(min(length - len(data), 65536))
            if not chunk:
                return b""
            data.extend(chunk)
        return bytes(data)

    def stop(self):
        self._running = False
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                pass
        self._sockets.clear()
        self._remove_owned_socket()
