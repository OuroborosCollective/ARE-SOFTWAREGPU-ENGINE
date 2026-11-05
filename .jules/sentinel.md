## 2026-10-18 - Missing Authentication Hardening
**Vulnerability:** Found a lack of bounded execution validation for loopback testing.
**Learning:** `base64.b64decode` has a `validate=True` flag in python 3.1+ that validates the base64 string doesn't contain characters outside the base64 alphabet, which is used in `software_gpu/network/security.py` in `tensor_shape`. However, in `software_gpu/network/protocol.py`, `decode_tensor_base64` does not use `validate=True`, making it vulnerable to parsing malicious Base64 payloads and circumventing validation.
**Prevention:** Always use `validate=True` in `base64.b64decode` when deserializing user payloads.
