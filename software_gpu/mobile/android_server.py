"""
Android & Mobile Low-Latency GPU Server Subsystem.
Implements Unix Domain Sockets (UDS) and Linux Abstract Namespace Sockets (`\0software_gpu`)
to provide zero-permission, ultra-fast IPC for native Android NDK apps and Android services.
"""

import os
import socket
import threading
import json
from typing import Optional

from ..network.dispatcher import GPUCommandDispatcher
from ..network.protocol import unpack_header, pack_message, MsgType, HEADER_SIZE
from ..network.security import validate_request, SecurityLimits, bounded_json


def _reject_nonfinite(_value):
    raise ValueError("REQUEST_INVALID")


class AndroidIPCServer(threading.Thread):
    """Unix Domain Socket server tailored for Android's LocalSocket IPC."""
    def __init__(
        self,
        socket_path: str = "/tmp/software_gpu.sock",
        abstract_name: Optional[str] = "software_gpu",
        dispatcher: Optional[GPUCommandDispatcher] = None
    ):
        super().__init__(daemon=True, name="Android_SoftGPU_IPC")
        self.socket_path = socket_path
        self.abstract_name = abstract_name
        self.dispatcher = dispatcher or GPUCommandDispatcher()
        self._running = False
        self._sockets = []

    def run(self):
        self._running = True
        # 1. Setup Abstract Namespace Socket (Standard Android LocalSocket with leading null byte)
        if self.abstract_name:
            try:
                # Leading '\0' indicates Linux/Android abstract namespace
                abstract_addr = f"\0{self.abstract_name}"
                abs_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                abs_sock.bind(abstract_addr)
                abs_sock.listen(64)
                self._sockets.append(abs_sock)
                threading.Thread(target=self._listen_loop, args=(abs_sock,), daemon=True).start()
            except Exception:
                pass

        # 2. Setup Filesystem Unix Domain Socket
        try:
            if os.path.exists(self.socket_path):
                os.remove(self.socket_path)
            fs_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            fs_sock.bind(self.socket_path)
            fs_sock.listen(64)
            self._sockets.append(fs_sock)
            threading.Thread(target=self._listen_loop, args=(fs_sock,), daemon=True).start()
        except Exception:
            pass

    def _listen_loop(self, s: socket.socket):
        while self._running:
            try:
                client_sock, _ = s.accept()
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except Exception:
                break

    def _handle_client(self, client_sock: socket.socket):
        limits = SecurityLimits()
        with client_sock:
            client_sock.settimeout(limits.io_timeout_seconds)
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
                    bounded_json(req)
                    req_id = req.get("id")
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
        for s in self._sockets:
            try:
                s.close()
            except Exception:
                pass
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except Exception:
                pass
