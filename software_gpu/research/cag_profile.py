"""Prepare one fixed shader table on the credential-owning host (standard library only)."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import time
from uuid import UUID


ENDPOINT = "services.wolfram.com"
ROUTE = "/api/cag/v1/WolframLanguageCompute"
EXPRESSION = "Table[Floor[255 (3 (i/255)^2 - 2 (i/255)^3)], {i, 0, 255}]"
REQUEST = {"code": EXPRESSION, "maxChars": 4096, "timeConstraint": 10}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parse_response(body):
    if (body["success"] is not True or body["code"] != 200 or
            str(UUID(body["uuid"])) != body["uuid"]):
        raise ValueError("CAG response rejected")
    match = re.fullmatch(r"\s*Out\[1\]\s*=\s*\{\s*(\d{1,3}(?:\s*,\s*\d{1,3}){255})\s*\}\s*", body["result"])
    if not match:
        raise ValueError("Expected exactly one 256-entry numeric Wolfram list")
    table = bytes(int(i) for i in match[1].split(","))
    if any(x != i*i*(765-2*i)//65025 for i, x in enumerate(table)):
        raise ValueError("CAG table differs from the exact integer reference")
    return table


def prepare():
    start = time.perf_counter_ns()
    key_file = os.environ.get("WOLFRAM_CAG_API_KEY_FILE")
    key = Path(key_file).read_text().strip() if key_file else os.environ["WOLFRAM_CAG_API_KEY"]
    if not key:
        raise ValueError("CAG credential missing")
    payload = canonical(REQUEST)
    # One fixed TLS origin. No redirects, retries, or arbitrary expressions.
    conn = http.client.HTTPSConnection(ENDPOINT, timeout=15)
    try:
        sent = time.perf_counter_ns()
        conn.request("POST", ROUTE, payload, {"Content-Type": "application/json", "Authorization": key})
        response = conn.getresponse()
        raw = response.read(16385)
        elapsed = time.perf_counter_ns() - sent
        if response.status != 200 or len(raw) > 16384:
            raise ValueError(f"CAG rejected HTTP {response.status} or oversized response")
    finally:
        conn.close()
    body = json.loads(raw)
    if isinstance(body, str):  # Some upstream versions wrap the JSON object.
        body = json.loads(body)
    table = parse_response(body)
    fields = {k: body[k] for k in ("uuid", "code", "success", "result")}
    return {"schema": "are.cag-smoothstep.v1", "endpoint": f"https://{ENDPOINT}{ROUTE}",
            "request": REQUEST, "request_sha256": digest(payload), "response": fields,
            "response_sha256": digest(canonical(fields)), "table_sha256": digest(table),
            "request_bytes": len(payload), "response_bytes": len(raw), "http_status": response.status,
            "http_calls": 1, "http_elapsed_ns": elapsed,
            "preparation_ns": time.perf_counter_ns() - start}


def replay(receipt):
    table = parse_response(receipt["response"])
    if (receipt["schema"] != "are.cag-smoothstep.v1" or receipt["request"] != REQUEST or
            receipt["endpoint"] != f"https://{ENDPOINT}{ROUTE}" or
            receipt["request_sha256"] != digest(canonical(REQUEST)) or
            receipt["response_sha256"] != digest(canonical(receipt["response"])) or
            receipt["table_sha256"] != digest(table) or receipt["http_status"] != 200 or
            receipt["http_calls"] != 1 or not 0 < receipt["http_elapsed_ns"] <= receipt["preparation_ns"]):
        raise ValueError("CAG receipt mismatch")
    return table


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
