// Explicit WebGPU test doubles exercise asynchronous control flow only.
// The supplied pixels are synthetic; this file is never browser/GPU runtime evidence.
import assert from "node:assert/strict";
import test from "node:test";
import { runDiagnostics } from "../../clients/firefox-addon/diagnostics.mjs";

function syntheticTriangle() {
  const bytes = new Uint8Array(64 * 64 * 4);
  for (let row = 0; row < 64; row++) {
    const y = 63.5 - row;
    for (let x = 0; x < 64; x++) {
      const inside = y > 8 && y < 56 && Math.abs(x + 0.5 - 32) < (56 - y) / 2;
      bytes.set(inside ? [255, 0, 0, 255] : [0, 0, 255, 255], (row * 64 + x) * 4);
    }
  }
  return bytes;
}

async function probeWithTestDouble(t, lossMode) {
  let settleLost;
  let lossDelivered = false;
  const device = {
    lost: new Promise(resolve => { settleLost = resolve; }),
    addEventListener() {}, removeEventListener() {}, pushErrorScope() {},
    async popErrorScope() { return null; },
    createShaderModule() { return { async getCompilationInfo() { return { messages: [] }; } }; },
    async createRenderPipelineAsync() { return {}; },
    createTexture() { return { createView() { return {}; }, destroy() {} }; },
    createBuffer() {
      return { async mapAsync() {}, getMappedRange() { return syntheticTriangle().buffer; }, unmap() {}, destroy() {} };
    },
    createCommandEncoder() {
      return {
        beginRenderPass() { return { setPipeline() {}, draw() {}, end() {} }; },
        copyTextureToBuffer() {}, finish() { return {}; },
      };
    },
    queue: { submit() {}, async onSubmittedWorkDone() {} },
    destroy() {
      if (lossMode === "never") return;
      setTimeout(() => {
        lossDelivered = true;
        settleLost({ reason: lossMode, message: "explicit unit-test loss" });
      }, 5);
    },
  };
  const adapter = { features: new Set(), limits: {}, async requestDevice() { return device; } };
  const replacements = {
    navigator: { gpu: { async requestAdapter(options) { return options.forceFallbackAdapter ? null : adapter; } } },
    GPUTextureUsage: { RENDER_ATTACHMENT: 16, COPY_SRC: 1 },
    GPUBufferUsage: { COPY_DST: 8, MAP_READ: 1 },
    GPUMapMode: { READ: 1 },
  };
  for (const [key, value] of Object.entries(replacements)) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { value, configurable: true });
    t.after(() => {
      if (original) Object.defineProperty(globalThis, key, original);
      else delete globalThis[key];
    });
  }
  const canvas = { addEventListener() {}, removeEventListener() {}, getContext() { return null; } };
  const result = await runDiagnostics({ webgl: canvas });
  return { result, lossDelivered };
}

test("a loss delivered after error scopes and destroy invalidates the finished report", async t => {
  const { result } = await probeWithTestDouble(t, "unknown");
  assert.equal(result.complete, true);
  assert.equal(result.webgpu.default.readback.matches, true);
  assert.equal(result.webgpu.default.acceptedPass, false);
  assert.equal(result.webgpu.default.status, "fail");
  assert.deepEqual(result.webgpu.default.deviceLost, [{ reason: "unknown", message: "explicit unit-test loss" }]);
});

test("own destruction is accepted only after its loss notification has settled", async t => {
  const { result, lossDelivered } = await probeWithTestDouble(t, "destroyed");
  assert.equal(lossDelivered, true);
  assert.equal(result.webgpu.default.acceptedPass, true);
  assert.deepEqual(result.webgpu.default.deviceLost, []);
});

test("a device that never reports completion of destruction cannot pass", async t => {
  const { result } = await probeWithTestDouble(t, "never");
  assert.equal(result.webgpu.default.readback.matches, true);
  assert.equal(result.webgpu.default.acceptedPass, false);
  assert.equal(result.webgpu.default.status, "error");
  assert.ok(result.webgpu.default.cleanupErrors.some(error => error.name === "ProbeTimeout"));
});
