"""
Network Communication Protocols for SoftwareGPU.
Supports JSON-RPC 2.0 framing and High-Performance Binary Socket Framing.
Based on PoCL-Remote, Cricket, and GPUrpc research designs.
"""

import struct
import json
from typing import Dict, Any, Tuple, Optional
import numpy as np

MAGIC_HEADER = b"SGPU"
HEADER_FORMAT = "!4sIIQ"  # Magic (4B), MsgType (4B), Flags (4B), PayloadLength (8B) = 20 Bytes
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_FRAME_BYTES = 1_048_576

class MsgType:
    JSON_REQUEST = 1
    JSON_RESPONSE = 2
    RAW_TENSOR = 3
    ERROR = 4
    HEARTBEAT = 5


def pack_message(msg_type: int, payload_dict: Dict[str, Any], flags: int = 0) -> bytes:
    """Serializes a JSON payload into length-prefixed binary frame."""
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    length = len(payload_bytes)
    if length > MAX_FRAME_BYTES:
        raise ValueError('FRAME_TOO_LARGE')
    header = struct.pack(HEADER_FORMAT, MAGIC_HEADER, msg_type, flags, length)
    return header + payload_bytes


def unpack_header(header_bytes: bytes) -> Tuple[int, int, int]:
    """Unpacks frame header and returns (msg_type, flags, payload_length)."""
    if len(header_bytes) != HEADER_SIZE:
        raise ValueError(f"Invalid header size: expected {HEADER_SIZE}, got {len(header_bytes)}")
    magic, msg_type, flags, length = struct.unpack(HEADER_FORMAT, header_bytes)
    if length > MAX_FRAME_BYTES:
        raise ValueError("FRAME_TOO_LARGE")
    if magic != MAGIC_HEADER:
        raise ValueError(f"Invalid protocol magic: {magic}")
    return msg_type, flags, length


def encode_tensor_base64(arr: np.ndarray) -> Dict[str, Any]:
    """Serializes a NumPy array to JSON-friendly dict."""
    import base64
    arr_c = np.ascontiguousarray(arr)
    return {
        "__tensor__": True,
        "shape": list(arr_c.shape),
        "dtype": str(arr_c.dtype),
        "data_b64": base64.b64encode(arr_c.tobytes()).decode("ascii")
    }


def decode_tensor_base64(d: Dict[str, Any]) -> np.ndarray:
    """Deserializes a tensor dict back to a NumPy array."""
    import base64
    from .security import SecurityLimits, tensor_shape
    tensor_shape(d, SecurityLimits())
    raw_bytes = base64.b64decode(d["data_b64"], validate=True)
    arr = np.frombuffer(raw_bytes, dtype=np.dtype(d["dtype"]))
    if not np.isfinite(arr).all():
        raise ValueError("NONFINITE_TENSOR_CONTENT")
    return arr.reshape(d["shape"])
