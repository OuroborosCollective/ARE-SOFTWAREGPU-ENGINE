// Synthetic unit inputs verify the byte gate; they are not browser runtime evidence.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { readbackEvidence, acceptedCase } from "../../clients/firefox-addon/readback.mjs";

function triangle(origin = "bottom-left") {
  const bytes = new Uint8Array(64 * 64 * 4);
  for (let row = 0; row < 64; row++) {
    const y = origin === "bottom-left" ? row + 0.5 : 63.5 - row;
    const halfWidth = (56 - y) / 2;
    for (let x = 0; x < 64; x++) {
      const inside = y > 8 && y < 56 && Math.abs(x + 0.5 - 32) < halfWidth;
      bytes.set(inside ? [255, 0, 0, 255] : [0, 0, 255, 255], (row * 64 + x) * 4);
    }
  }
  return bytes;
}

test("full triangle bytes pass in both declared row origins and hash actual bytes", async () => {
  for (const origin of ["bottom-left", "top-left"]) {
    const bytes = triangle(origin);
    const before = bytes.slice();
    const report = await readbackEvidence(bytes, origin);
    assert.equal(report.matches, true);
    assert.equal(report.mismatchedPixels, 0);
    assert.deepEqual(report.counts, { red: 1152, blue: 2944, other: 0 });
    assert.equal(report.sha256, createHash("sha256").update(bytes).digest("hex"));
    assert.deepEqual(Buffer.from(report.payloadBase64, "base64"), Buffer.from(bytes));
    assert.deepEqual(bytes, before);
  }
});

test("clear-only buffer and incomplete triangle cannot pass", async () => {
  const blue = new Uint8Array(16384);
  for (let i = 0; i < blue.length; i += 4) blue.set([0, 0, 255, 255], i);
  assert.equal((await readbackEvidence(blue, "bottom-left")).matches, false);
  const bytes = triangle();
  bytes.set([0, 0, 255, 255], (10 * 64 + 32) * 4);
  assert.equal((await readbackEvidence(bytes, "bottom-left")).matches, false);
});

test("moving one red pixel preserves counts but is still rejected", async () => {
  const bytes = triangle();
  bytes.set([0, 0, 255, 255], (10 * 64 + 32) * 4);
  bytes.set([255, 0, 0, 255], (1 * 64 + 32) * 4);
  const report = await readbackEvidence(bytes, "bottom-left");
  assert.deepEqual(report.counts, { red: 1152, blue: 2944, other: 0 });
  assert.equal(report.matches, false);
  assert.equal(report.mismatchedPixels, 2);
});

test("row origin, alpha, format and byte length are enforced", async () => {
  const bytes = triangle();
  assert.equal((await readbackEvidence(bytes, "top-left")).matches, false);
  bytes[3] = 0;
  assert.equal((await readbackEvidence(bytes, "bottom-left")).matches, false);
  await assert.rejects(readbackEvidence(bytes.subarray(1), "bottom-left"), /length/);
  await assert.rejects(readbackEvidence(new Float32Array(4096), "bottom-left"), /Uint8Array/);
  await assert.rejects(readbackEvidence(bytes, "unknown"), /origin/);
});

test("unavailable, timeout, API errors or missing readback never become success", async () => {
  const readback = await readbackEvidence(triangle(), "bottom-left");
  assert.equal(acceptedCase({ status: "pass", readback }), true);
  for (const status of ["unavailable", "timeout", "error", "running", "not_started"]) {
    assert.equal(acceptedCase({ status, readback }), false);
  }
  assert.equal(acceptedCase({ status: "pass" }), false);
  assert.equal(acceptedCase({ status: "pass", readback, errors: [{ code: 1282 }] }), false);
  assert.equal(acceptedCase({ status: "pass", readback, deviceLost: [{ reason: "unknown" }] }), false);
  assert.equal(acceptedCase({ status: "pass", readback, cleanupErrors: [{ name: "Error" }] }), false);
  assert.equal(acceptedCase({ status: "pass", readback, shaderMessages: [{ type: "error" }] }), false);
});
