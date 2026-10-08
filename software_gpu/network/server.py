"""Experimental authenticated LOOPBACK ONLY HTTP and TCP service.

No public bind, no wildcard CORS and no unrestricted in-process compute.
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from .protocol import unpack_header, pack_message, MsgType, HEADER_SIZE
from .security import (RequestRejected, SecurityLimits, authorized, get_token,
                       ensure_loopback, validate_request, bounded_json)
from .isolated_worker import IsolatedExecutor

PATHS = {
    "/api/v1/compute/gemm": "gemm",
    "/api/v1/compute/activation": "activation",
    "/api/v1/compute/vector_add": "vector_add",
    "/api/v1/graphics/render": "render_mesh",
    "/api/v1/game/physics": "physics_step",
    "/api/v1/game/boids": "boids_swarm",
}


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, policy):
        self.policy = policy
        super().__init__(addr, handler)

    def process_request(self, request, client_address):
        if not self.policy.connections.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.policy.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.policy.connections.release()


class ServicePolicy:
    def __init__(self, token, limits):
        self.token = get_token(token)
        self.limits = limits
        self.connections = threading.BoundedSemaphore(limits.max_clients)
        self.jobs = threading.BoundedSemaphore(limits.max_jobs)
        self.executor = IsolatedExecutor(limits)

    def dispatch(self, method, params):
        validate_request(method, params, self.limits)
        if method == "device_info":
            # Device metrics are reported through the same isolated worker.
            pass
        if not self.jobs.acquire(blocking=False):
            raise RequestRejected("CAPACITY_EXHAUSTED", 429)
        try:
            result = self.executor.execute(method, params)
            # Enforce response byte cap before handing to either protocol.
            if len(json.dumps(result, allow_nan=False).encode("utf-8")) > self.limits.max_response_bytes:
                raise RequestRejected("RESPONSE_TOO_LARGE", 413)
            return result
        finally:
            self.jobs.release()


class GPUHTTPRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format, *args):
        pass

    def _reply(self, status, doc):
        payload = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _guard(self):
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer ") or not authorized(self.server.policy.token, value[7:]):
            self._reply(401, {"error": "UNAUTHORIZED"})
            return False
        return True

    def do_OPTIONS(self):
        self._reply(405, {"error": "CORS_DISABLED"})

    def do_GET(self):
        if not self._guard():
            return
        if self.path not in ("/health", "/status", "/api/v1/status"):
            self._reply(404, {"error": "NOT_FOUND"})
            return
        try:
            info = self.server.policy.dispatch("device_info", {})
            self._reply(200, {"status": "healthy", "gpu": info})
        except RequestRejected as exc:
            self._reply(exc.status, {"error": exc.code})

    def do_POST(self):
        if not self._guard():
            return
        raw = self.headers.get("Content-Length")
        try:
            if raw is None or not raw.isascii() or not raw.isdecimal():
                raise RequestRejected("CONTENT_LENGTH_REQUIRED", 411)
            length = int(raw)
            if length < 1 or length > self.server.policy.limits.max_request_bytes:
                raise RequestRejected("REQUEST_SIZE_LIMIT", 413)
            payload = self.rfile.read(length)
            if len(payload) != length:
                raise RequestRejected("REQUEST_INCOMPLETE")
            doc = json.loads(payload.decode("utf-8"),
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            bounded_json(doc)
            if not isinstance(doc, dict):
                raise RequestRejected("REQUEST_OBJECT_REQUIRED")
            if self.path.rstrip("/") == "/rpc":
                if doc.get("jsonrpc") != "2.0":
                    raise RequestRejected("JSONRPC_VERSION_INVALID")
                method, params = doc.get("method"), doc.get("params", {})
                result = self.server.policy.dispatch(method, params)
                self._reply(200, {"jsonrpc": "2.0", "result": result, "id": doc.get("id")})
            else:
                method = PATHS.get(self.path.rstrip("/"))
                if method is None:
                    raise RequestRejected("NOT_FOUND", 404)
                result = self.server.policy.dispatch(method, doc)
                self._reply(200, {"success": True, "data": result})
        except RequestRejected as exc:
            self._reply(exc.status, {"error": exc.code})
        except (ValueError, UnicodeError, TypeError):
            self._reply(400, {"error": "MALFORMED_REQUEST"})
        except BaseException:
            self._reply(500, {"error": "INTERNAL_ERROR"})


class BinaryTCPServer(threading.Thread):
    def __init__(self, host, port, policy):
        super().__init__(daemon=True, name="SoftGPU_TCPServer")
        self.host, self.port, self.policy = host, port, policy
        self._running = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self.port = self._sock.getsockname()[1]
        self._sock.settimeout(.2)

    def run(self):
        self._sock.listen(self.policy.limits.max_clients)
        self._running.set()
        while self._running.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.policy.connections.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, client):
        try:
            with client:
                client.settimeout(self.policy.limits.io_timeout_seconds)
                # One request per connection prevents indefinite idle sessions.
                header = self._read(client, HEADER_SIZE)
                if len(header) != HEADER_SIZE:
                    return
                kind, flags, length = unpack_header(header)
                if kind != MsgType.JSON_REQUEST or flags != 0 or length < 1 or length > self.policy.limits.max_request_bytes:
                    return
                payload = self._read(client, length)
                if len(payload) != length:
                    return
                doc = json.loads(payload.decode("utf-8"))
                bounded_json(doc)
                if not isinstance(doc, dict) or not authorized(self.policy.token, doc.get("token", "")):
                    response = {"error": "UNAUTHORIZED"}
                    response_kind = MsgType.ERROR
                else:
                    try:
                        result = self.policy.dispatch(doc.get("method"), doc.get("params", {}))
                        response, response_kind = {"result": result, "id": doc.get("id")}, MsgType.JSON_RESPONSE
                    except RequestRejected as exc:
                        response, response_kind = {"error": exc.code}, MsgType.ERROR
                if len(json.dumps(response).encode("utf-8")) <= self.policy.limits.max_response_bytes:
                    client.sendall(pack_message(response_kind, response))
        except (OSError, ValueError, UnicodeError, TimeoutError):
            pass
        finally:
            self.policy.connections.release()

    @staticmethod
    def _read(conn, count):
        out = bytearray()
        while len(out) < count:
            chunk = conn.recv(min(count - len(out), 65536))
            if not chunk:
                break
            out.extend(chunk)
        return bytes(out)

    def stop(self):
        self._running.clear()
        self._sock.close()
        if self.is_alive():
            self.join(timeout=2)


class SoftwareGPUServer:
    def __init__(self, http_port=8088, tcp_port=8089, host="127.0.0.1",
                 auth_token=None, limits=None):
        ensure_loopback(host)
        self.policy = ServicePolicy(auth_token, limits or SecurityLimits())
        self.http_server = ThreadedHTTPServer((host, http_port), GPUHTTPRequestHandler, self.policy)
        self.tcp_server = BinaryTCPServer(host, tcp_port, self.policy)
        self.http_port = self.http_server.server_address[1]
        self.tcp_port = self.tcp_server.port
        self._http_thread = None

    def start(self):
        self._http_thread = threading.Thread(target=self.http_server.serve_forever,
                                              daemon=True, name="SoftGPU_HTTPServer")
        self._http_thread.start()
        self.tcp_server.start()

    def stop(self):
        self.http_server.shutdown() if self._http_thread is not None else None
        self.http_server.server_close()
        self.tcp_server.stop()
        if self._http_thread is not None:
            self._http_thread.join(timeout=2)
