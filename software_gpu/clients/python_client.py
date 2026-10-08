"""
Python Client Adapter for SoftwareGPU Remote Endpoints.
Supports both HTTP REST/JSON-RPC and High-Performance Binary TCP connections.
"""

import json
import os
import socket
import urllib.request
import numpy as np
from typing import Dict, Any, Optional

from ..network.protocol import (
    pack_message, unpack_header, encode_tensor_base64, decode_tensor_base64,
    MsgType, HEADER_SIZE
)


class SoftwareGPUClient:
    """Client for connecting to a local or remote SoftwareGPU server."""
    def __init__(self, host: str = "127.0.0.1", http_port: int = 8088, tcp_port: int = 8089, use_tcp: bool = False, token: str = None):
        self.host = host
        self.http_port = http_port
        self.tcp_port = tcp_port
        self.use_tcp = use_tcp
        self.token = token if token is not None else os.environ.get('SOFTWAREGPU_AUTH_TOKEN', '')
        self._sock = None

    def get_device_info(self) -> Dict[str, Any]:
        """Queries GPU hardware specifications and telemetry."""
        url = f"http://{self.host}:{self.http_port}/health"
        req = urllib.request.Request(url, method="GET", headers={"Authorization": "Bearer " + self.token})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["gpu"]

    def compute_gemm(self, A: np.ndarray, B: np.ndarray) -> np.ndarray:
        """Offloads General Matrix Multiplication (A @ B) to SoftwareGPU."""
        payload = {
            "a": encode_tensor_base64(A),
            "b": encode_tensor_base64(B)
        }
        res = self._post("/api/v1/compute/gemm", "gemm", payload)
        return decode_tensor_base64(res["result"])

    def compute_activation(self, X: np.ndarray, act_type: str = "relu") -> np.ndarray:
        """Offloads tensor activation (ReLU/GELU) to SoftwareGPU."""
        payload = {
            "x": encode_tensor_base64(X),
            "type": act_type
        }
        res = self._post("/api/v1/compute/activation", "activation", payload)
        return decode_tensor_base64(res["result"])

    def render_mesh(self, vertices: list, indices: list, camera: dict, width: int = 256, height: int = 256) -> bytes:
        """Offloads 3D mesh rasterization and returns BMP bytes."""
        import base64
        payload = {
            "vertices": vertices,
            "indices": indices,
            "camera": camera,
            "width": width,
            "height": height
        }
        res = self._post("/api/v1/graphics/render", "render_mesh", payload)
        return base64.b64decode(res["image_b64"])

    def _post(self, path: str, method: str, params: dict) -> dict:
        if self.use_tcp:
            return self._tcp_rpc(method, params)
        else:
            return self._http_post(path, params)

    def _http_post(self, path: str, params: dict) -> dict:
        url = f"http://{self.host}:{self.http_port}{path}"
        body = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token}, method="POST")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("success", False):
                raise RuntimeError(data.get("error", "Unknown error"))
            return data["data"]

    def _tcp_rpc(self, method: str, params: dict) -> dict:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(15)
        sock.connect((self.host, self.tcp_port))
        with sock:
            req_msg = {"method": method, "params": params, "id": 1, "token": self.token}
            sock.sendall(pack_message(MsgType.JSON_REQUEST, req_msg))

            header_bytes = self._recv_all(sock, HEADER_SIZE)
            msg_type, flags, payload_len = unpack_header(header_bytes)
            payload_bytes = self._recv_all(sock, payload_len)
            resp = json.loads(payload_bytes.decode("utf-8"))

            if "error" in resp:
                raise RuntimeError(resp["error"])
            return resp["result"]

    def _recv_all(self, sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(min(length - len(data), 65536))
            if not chunk:
                raise ConnectionError("Socket closed prematurely")
            data.extend(chunk)
        return bytes(data)
