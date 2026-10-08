"""
Multi-Protocol Network Server for SoftwareGPU.
Exposes both HTTP REST/JSON-RPC 2.0 and High-Speed TCP Binary Socket endpoints.
Enables cross-process, cross-language, and networked GPU compute offloading.
"""

import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional, Tuple

from .dispatcher import GPUCommandDispatcher
from .protocol import unpack_header, pack_message, MsgType, HEADER_SIZE


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class GPUHTTPRequestHandler(BaseHTTPRequestHandler):
    dispatcher: GPUCommandDispatcher = None

    def log_message(self, format, *args):
        # Silent logging to prevent console pollution
        pass

    def _send_json(self, status_code: int, data: dict):
        response_bytes = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self):
        self._send_json(200, {"status": "ok"})

    def do_GET(self):
        if self.path in ("/health", "/status", "/api/v1/status"):
            info = self.dispatcher.op_device_info({})
            self._send_json(200, {"status": "healthy", "gpu": info})
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            req = json.loads(post_data.decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON payload: {str(e)}"})
            return

        # Handle JSON-RPC 2.0 format
        if "jsonrpc" in req and "method" in req:
            req_id = req.get("id", None)
            method = req["method"]
            params = req.get("params", {})
            try:
                result = self.dispatcher.handle_request(method, params)
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id
                })
            except Exception as e:
                self._send_json(500, {
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": str(e)},
                    "id": req_id
                })
            return

        # Handle REST paths
        path = self.path.rstrip("/")
        method_map = {
            "/api/v1/compute/gemm": "gemm",
            "/api/v1/compute/activation": "activation",
            "/api/v1/compute/vector_add": "vector_add",
            "/api/v1/graphics/render": "render_mesh",
            "/api/v1/game/physics": "physics_step",
            "/api/v1/game/boids": "boids_swarm",
        }

        if path in method_map:
            try:
                result = self.dispatcher.handle_request(method_map[path], req)
                self._send_json(200, {"success": True, "data": result})
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        else:
            self._send_json(404, {"error": f"Unknown path: {path}"})


class BinaryTCPServer(threading.Thread):
    """High-throughput binary socket server for direct tensor streaming."""
    def __init__(self, host: str, port: int, dispatcher: GPUCommandDispatcher):
        super().__init__(daemon=True, name="SoftGPU_TCPServer")
        self.host = host
        self.port = port
        self.dispatcher = dispatcher
        self._running = False
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def run(self):
        self._sock.bind((self.host, self.port))
        self._sock.listen(128)
        self._running = True
        while self._running:
            try:
                client_sock, addr = self._sock.accept()
                threading.Thread(
                    target=self._handle_client,
                    args=(client_sock,),
                    daemon=True
                ).start()
            except Exception:
                break

    def _handle_client(self, client_sock: socket.socket):
        try:
            with client_sock:
                while self._running:
                    # Read 20-byte header
                    header_bytes = self._recv_all(client_sock, HEADER_SIZE)
                    if not header_bytes:
                        break
                    msg_type, flags, payload_len = unpack_header(header_bytes)
                    payload_bytes = self._recv_all(client_sock, payload_len)

                    req = json.loads(payload_bytes.decode("utf-8"))
                    method = req.get("method", "")
                    params = req.get("params", {})
                    req_id = req.get("id")

                    try:
                        res_data = self.dispatcher.handle_request(method, params)
                        resp_payload = {"result": res_data, "id": req_id}
                        resp_bytes = pack_message(MsgType.JSON_RESPONSE, resp_payload)
                    except Exception as e:
                        resp_payload = {"error": str(e), "id": req_id}
                        resp_bytes = pack_message(MsgType.ERROR, resp_payload)

                    client_sock.sendall(resp_bytes)
        except Exception:
            pass

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
        try:
            self._sock.close()
        except Exception:
            pass


class SoftwareGPUServer:
    """Manages lifecycle of both HTTP and TCP SoftwareGPU remote endpoints."""
    def __init__(self, http_port: int = 8088, tcp_port: int = 8089, host: str = "127.0.0.1"):
        self.http_port = http_port
        self.tcp_port = tcp_port
        self.host = host
        self.dispatcher = GPUCommandDispatcher()

        GPUHTTPRequestHandler.dispatcher = self.dispatcher
        self.http_server = ThreadedHTTPServer((self.host, self.http_port), GPUHTTPRequestHandler)
        self.tcp_server = BinaryTCPServer(self.host, self.tcp_port, self.dispatcher)

        self._http_thread = None

    def start(self):
        """Starts HTTP and TCP server listeners in background threads."""
        self._http_thread = threading.Thread(
            target=self.http_server.serve_forever,
            daemon=True,
            name="SoftGPU_HTTPServer"
        )
        self._http_thread.start()
        self.tcp_server.start()

    def stop(self):
        """Stops listeners and releases sockets."""
        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()
        if self.tcp_server:
            self.tcp_server.stop()
