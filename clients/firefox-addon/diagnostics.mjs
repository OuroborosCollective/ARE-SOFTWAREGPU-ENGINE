import { SIZE, readbackEvidence, acceptedCase } from "./readback.mjs";

export async function runDiagnostics(canvases, onUpdate = () => {}) {
  const CASE_MS = 25000;
  const STEP_MS = 15000;
  const result = {
    schema: "are.firefox-addon-diagnostics.v1",
    complete: false,
    context: { secureContext: globalThis.isSecureContext === true },
    contract: {
      width: SIZE, height: SIZE, format: "RGBA8", sampleCount: 1,
      caseDeadlineMs: CASE_MS, stepDeadlineMs: STEP_MS,
      successMeaning: "actual shader rendering and byte readback; not driver attribution or API conformance",
      driverAttribution: "not-established",
      dataTransmission: "none",
    },
    webgl: { status: "not_started" },
    webgpu: { default: { status: "not_started" }, forceFallback: { status: "not_started" } },
  };
  const describe = error => ({ name: error?.name || "Error", message: String(error?.message ?? error) });
  const publish = () => onUpdate(result);
  class ProbeTimeout extends Error {
    constructor(stage, limit) {
      super(`${stage} did not complete within ${Math.ceil(limit)} ms`);
      this.name = "ProbeTimeout";
    }
  }
  function bounded(promise, stage, milliseconds) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new ProbeTimeout(stage, milliseconds)), Math.max(0, milliseconds));
      Promise.resolve(promise).then(
        value => { clearTimeout(timer); resolve(value); },
        error => { clearTimeout(timer); reject(error); },
      );
    });
  }
  function stageRunner(record) {
    const deadline = performance.now() + CASE_MS;
    return async (stage, operation) => {
      record.stage = stage;
      const remaining = Math.min(STEP_MS, deadline - performance.now());
      if (remaining <= 0) throw new ProbeTimeout(stage, 0);
      return bounded(Promise.resolve().then(operation), stage, remaining);
    };
  }
  function failure(record, error) {
    record.status = error?.name === "ProbeTimeout" ? "timeout" : "error";
    record.error = describe(error);
  }

  async function webglProbe() {
    const record = { status: "running", stage: "context", errors: [], contextLoss: [], creationErrors: [] };
    result.webgl = record;
    publish();
    const step = stageRunner(record);
    const canvas = canvases.webgl;
    const onCreation = event => record.creationErrors.push(String(event.statusMessage));
    const onLoss = () => record.contextLoss.push("webglcontextlost");
    canvas.addEventListener("webglcontextcreationerror", onCreation);
    canvas.addEventListener("webglcontextlost", onLoss);
    let gl, program, buffer;
    const shaders = [];
    try {
      gl = canvas.getContext("webgl", { alpha: false, antialias: false, depth: false, stencil: false, preserveDrawingBuffer: true, premultipliedAlpha: false });
      if (!gl) { record.status = "unavailable"; record.reason = "getContext(webgl) returned null"; return record; }
      record.contextType = "webgl";
      record.contextAttributes = gl.getContextAttributes();
      record.drawingBufferSize = [gl.drawingBufferWidth, gl.drawingBufferHeight];
      record.info = {
        vendor: gl.getParameter(gl.VENDOR), renderer: gl.getParameter(gl.RENDERER),
        version: gl.getParameter(gl.VERSION), shadingLanguageVersion: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
      };
      const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
      record.info.unmasked = debugInfo ? {
        vendor: gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL),
        renderer: gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL),
      } : null;
      record.stage = "shader-and-pipeline";
      record.shaderLogs = [];
      const shader = (type, source) => {
        const object = gl.createShader(type);
        if (!object) throw new Error("createShader returned null");
        shaders.push(object);
        gl.shaderSource(object, source);
        gl.compileShader(object);
        record.shaderLogs.push({ type, log: gl.getShaderInfoLog(object), compiled: gl.getShaderParameter(object, gl.COMPILE_STATUS) });
        if (!gl.getShaderParameter(object, gl.COMPILE_STATUS)) throw new Error("WebGL shader compilation failed");
        return object;
      };
      const vertex = shader(gl.VERTEX_SHADER, "attribute vec2 position; void main(){ gl_Position=vec4(position,0.0,1.0); }");
      const fragment = shader(gl.FRAGMENT_SHADER, "precision mediump float; void main(){ gl_FragColor=vec4(1.0,0.0,0.0,1.0); }");
      program = gl.createProgram();
      if (!program) throw new Error("createProgram returned null");
      gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program);
      record.programLog = gl.getProgramInfoLog(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("WebGL program link failed");
      gl.useProgram(program);
      buffer = gl.createBuffer();
      if (!buffer) throw new Error("createBuffer returned null");
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-0.75, -0.75, 0.75, -0.75, 0, 0.75]), gl.STATIC_DRAW);
      const attribute = gl.getAttribLocation(program, "position");
      if (attribute < 0) throw new Error("Vertex attribute position unavailable");
      gl.enableVertexAttribArray(attribute); gl.vertexAttribPointer(attribute, 2, gl.FLOAT, false, 0, 0);
      gl.disable(gl.BLEND); gl.disable(gl.DITHER); gl.disable(gl.DEPTH_TEST); gl.disable(gl.SCISSOR_TEST); gl.disable(gl.CULL_FACE);
      gl.viewport(0, 0, SIZE, SIZE); gl.clearColor(0, 0, 1, 1); gl.clear(gl.COLOR_BUFFER_BIT);
      record.stage = "draw-and-readPixels";
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      const rgba = new Uint8Array(SIZE * SIZE * 4);
      gl.readPixels(0, 0, SIZE, SIZE, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
      for (let i = 0; i < 16; i++) {
        const code = gl.getError();
        if (code === gl.NO_ERROR) break;
        record.errors.push({ api: "getError", code });
      }
      if (gl.isContextLost()) record.contextLoss.push("isContextLost returned true");
      record.readback = await step("readback-hash", () => readbackEvidence(rgba, "bottom-left"));
      record.status = record.readback.matches && record.errors.length === 0 && record.contextLoss.length === 0 ? "pass" : "fail";
      record.stage = "complete";
    } catch (error) { failure(record, error); }
    finally {
      if (gl) {
        if (buffer) gl.deleteBuffer(buffer);
        if (program) gl.deleteProgram(program);
        for (const object of shaders) gl.deleteShader(object);
      }
      canvas.removeEventListener("webglcontextcreationerror", onCreation);
      canvas.removeEventListener("webglcontextlost", onLoss);
    }
    return record;
  }

  async function webgpuProbe(forceFallbackAdapter) {
    const key = forceFallbackAdapter ? "forceFallback" : "default";
    const record = {
      status: "running", stage: "api", request: { forceFallbackAdapter },
      errors: [], deviceLost: [], shaderMessages: [], cleanupErrors: [],
    };
    result.webgpu[key] = record;
    publish();
    const step = stageRunner(record);
    if (!navigator.gpu) { record.status = "unavailable"; record.reason = "navigator.gpu unavailable"; return record; }
    let device, texture, readbackBuffer, closed = false, cleanupStarted = false, scopeCount = 0;
    const onError = event => { if (!closed) record.errors.push({ source: "uncapturederror", ...describe(event.error) }); };
    try {
      const adapter = await step("requestAdapter", () => navigator.gpu.requestAdapter({ forceFallbackAdapter }));
      if (!adapter) { record.status = "unavailable"; record.reason = "requestAdapter returned null"; return record; }
      record.stage = "adapter-info";
      record.adapterInfo = {};
      for (const field of ["vendor", "architecture", "device", "description", "subgroupMinSize", "subgroupMaxSize", "isFallbackAdapter"]) {
        if (adapter.info && field in adapter.info) record.adapterInfo[field] = adapter.info[field];
      }
      record.features = Array.from(adapter.features).sort();
      record.limits = {};
      for (const field in adapter.limits) if (typeof adapter.limits[field] === "number") record.limits[field] = adapter.limits[field];
      device = await step("requestDevice", () => {
        const pending = adapter.requestDevice();
        // A late device after a timeout is cleaned up; it is never counted as a successful case.
        pending.then(value => { if (closed) value.destroy(); }, () => {}).catch(() => {});
        return pending;
      });
      device.addEventListener("uncapturederror", onError);
      device.lost.then(info => {
        if (!closed && !cleanupStarted) record.deviceLost.push({ reason: info.reason, message: info.message });
      });
      for (const filter of ["out-of-memory", "internal", "validation"]) { device.pushErrorScope(filter); scopeCount++; }
      const module = device.createShaderModule({ label: "actual-red-triangle", code: `
        @vertex fn vertex_main(@builtin(vertex_index) index: u32) -> @builtin(position) vec4f {
          let positions = array<vec2f, 3>(vec2f(-0.75, -0.75), vec2f(0.75, -0.75), vec2f(0.0, 0.75));
          return vec4f(positions[index], 0.0, 1.0);
        }
        @fragment fn fragment_main() -> @location(0) vec4f { return vec4f(1.0, 0.0, 0.0, 1.0); }
      ` });
      const compilation = await step("shader-compilation-info", () => module.getCompilationInfo());
      record.shaderMessages = Array.from(compilation.messages, message => ({ type: message.type, message: message.message, lineNum: message.lineNum, linePos: message.linePos }));
      const pipeline = await step("createRenderPipelineAsync", () => device.createRenderPipelineAsync({
        label: "triangle-pipeline", layout: "auto",
        vertex: { module, entryPoint: "vertex_main" },
        fragment: { module, entryPoint: "fragment_main", targets: [{ format: "rgba8unorm" }] },
        primitive: { topology: "triangle-list", cullMode: "none" }, multisample: { count: 1 },
      }));
      texture = device.createTexture({ label: "readback-target", size: [SIZE, SIZE, 1], format: "rgba8unorm", usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC });
      readbackBuffer = device.createBuffer({ label: "actual-pixel-readback", size: SIZE * SIZE * 4, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
      record.stage = "render-copy-submit";
      const encoder = device.createCommandEncoder();
      const pass = encoder.beginRenderPass({ colorAttachments: [{ view: texture.createView(), clearValue: { r: 0, g: 0, b: 1, a: 1 }, loadOp: "clear", storeOp: "store" }] });
      pass.setPipeline(pipeline); pass.draw(3); pass.end();
      // 64 RGBA8 pixels make exactly one required 256-byte copy row.
      encoder.copyTextureToBuffer({ texture }, { buffer: readbackBuffer, bytesPerRow: SIZE * 4, rowsPerImage: SIZE }, [SIZE, SIZE, 1]);
      device.queue.submit([encoder.finish()]);
      await step("submitted-work-done", () => device.queue.onSubmittedWorkDone());
      await step("mapAsync", () => readbackBuffer.mapAsync(GPUMapMode.READ));
      const rgba = new Uint8Array(readbackBuffer.getMappedRange()).slice();
      readbackBuffer.unmap();
      record.readback = await step("readback-hash", () => readbackEvidence(rgba, "top-left"));
      record.status = record.readback.matches ? "pass" : "fail";
      const canvas = canvases[forceFallbackAdapter ? "forceFallback" : "default"];
      const preview = canvas?.getContext("2d");
      if (preview) preview.putImageData(new ImageData(new Uint8ClampedArray(rgba), SIZE, SIZE), 0, 0);
      record.stage = "complete";
    } catch (error) { failure(record, error); }
    finally {
      if (device) {
        while (scopeCount-- > 0) {
          try {
            const error = await bounded(device.popErrorScope(), "popErrorScope", 1000);
            if (error) record.errors.push({ source: "error-scope", ...describe(error) });
          } catch (error) { record.cleanupErrors.push(describe(error)); }
        }
        if (record.status === "pass" && (record.errors.length || record.deviceLost.length || record.shaderMessages.some(message => message.type === "error"))) record.status = "fail";
        cleanupStarted = true;
        for (const resource of [readbackBuffer, texture, device]) {
          if (resource) {
            try { resource.destroy(); }
            catch (error) { record.cleanupErrors.push(describe(error)); }
          }
        }
        try { device.removeEventListener("uncapturederror", onError); }
        catch (error) { record.cleanupErrors.push(describe(error)); }
        if (record.status === "pass" && record.cleanupErrors.length) record.status = "error";
      }
      closed = true;
    }
    return record;
  }

  try {
    await webglProbe();
    publish();
    await webgpuProbe(false);
    publish();
    await webgpuProbe(true);
  } catch (error) { result.fatalError = describe(error); }
  for (const record of [result.webgl, result.webgpu.default, result.webgpu.forceFallback]) {
    record.acceptedPass = !result.fatalError && acceptedCase(record);
  }
  result.complete = true;
  // Late device-lost/error callbacks must not change the exported report.
  const finished = JSON.parse(JSON.stringify(result));
  onUpdate(finished);
  return finished;
}
