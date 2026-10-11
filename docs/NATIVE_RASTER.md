# Opt-in C++ raster and VertexColor slice

`native-cpp` moves triangle coverage, barycentric interpolation, strict depth
testing and the built-in VertexColor fragment shader into one synchronous
C++17 call per draw. There is no Python pixel loop or fragment callback in
this path. Vertex processing, clipping, preparation and packing remain in
Python/NumPy and are included in the full-draw benchmark. This is a CPU
backend; it does not implement Vulkan or an Android GPU driver.

## Use from a source checkout

Build once outside the render loop, with GCC or Clang available:

```python
from software_gpu.graphics.native_raster import build_raster_kernel, NativeRasterKernel
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.batch_shader import VertexColorShader

binary, build = build_raster_kernel("build/native-raster")
kernel = NativeRasterKernel(binary, build["binary_sha256"])
renderer = SoftwareRasterizer(framebuffer, backend="native-cpp", native_kernel=kernel)
try:
    renderer.draw_mesh(vertices, faces, VertexColorShader())
    print(renderer.last_native_receipt)
finally:
    renderer.executor.shutdown()
```

The builder requires the repository's `native/` source directory, which the
current Python wheel does not ship. The loaded library must be trusted;
the SHA256 binds it to its build receipt, not to a security sandbox. There
is no implicit compilation, backend switching or fallback in `draw_mesh`.

## Numeric and ownership contract

- One worker, exact built-in VertexColor implementation only. Custom shader
  types or replaced vertex/fragment methods are rejected before callbacks.
- Submission order, top-left edge coverage and strictly smaller depth are
  preserved. Equal depth retains the first submitted fragment.
- Edge, barycentric and depth operations preserve the existing Float32
  order. FMA contraction and fast-math are disabled; incompatible floating
  point environments are rejected. Incremental edge updates are not used.
- Clipping can produce different color dtypes at the three vertices. The
  record carries three dtype bits so C++ reproduces each Float32/Float64
  multiplication and promotion at its original operation boundary.
- RGBA8 and Float32 depth arrays must be contiguous, aligned, writable and
  disjoint. The caller owns them exclusively until the synchronous draw
  returns; `ctypes.CDLL` releases the GIL during the native call.
- The low-level C ABI additionally assumes correctly allocated, aligned,
  disjoint buffers of the declared lengths. It is an in-process trusted
  interface, not an untrusted pointer-validation boundary.
- All packed records and work limits are validated before any framebuffer
  or counter writes. Limits: 200,000 prepared triangles, 4,194,304 pixels,
  either dimension at most 4,096 and 64 million candidate samples per draw.
  Nonfinite/out-of-domain packed records fail explicitly.

Native status codes are 1 (buffer/length), 2 (dimensions/triangle budget),
3 (floating point environment), 4 (record domain), and 5 (sample budget).
These are surfaced as `NATIVE_RASTER_REJECTED:<code>`; Python boundary
validation uses descriptive `NATIVE_RASTER_*` exceptions.

Counters count triangle/sample work, including overdraw: `candidate_samples`
is bbox work, `covered_samples` passes coverage, and `shaded_samples` passes
depth. They are not counts of final distinct visible pixels. The receipt is
separate from the SurfacePlan protocol.

## Reproduce the evidence

```sh
python -m unittest software_gpu.tests.test_native_raster -v
python -m software_gpu.benchmarks.compare_native_raster --output-dir evidence-local/native-raster --pixels 128 256 512 --repeats 15
```

The benchmark uses the real renderer, one worker, rotated mode order, one
warmup per mode and at least 15 recorded repetitions. Each draw checks
both color and depth bytes. It records separate/combined hashes, raw
timings, median/IQR/unscaled MAD, paired speedup ratios, source and binary
hashes, compiler flags, environment and scene seeds. Timing includes the
whole `draw_mesh` call, excluding framebuffer clear, build and byte checks.

Scenes include the five established fixtures and a static, procedural
13,312-triangle mesh. This is a stand-in until the user's animated GLB is
available; it does not measure skinning, animation, textures or materials.
CPU comparisons do not establish gaming-GPU parity or application FPS.

## Measured full-draw results

The recorded Linux x86-64 run used Intel Xeon Platinum 8573C, GCC 13.3,
Python 3.12.14 and NumPy 2.3.5. Fifteen repetitions for each of six scenes
at 128, 256 and 512 pixels produced 864 byte-identical draws including
warmups. These are same-host observations, not cross-machine guarantees.

At 256 × 256 pixels, times in milliseconds:

| Scene | Tiles median | Batch-first median | C++ median | C++ IQR | Paired gain vs batch |
|---|---:|---:|---:|---:|---:|
| Tiny | 0.507 | 0.560 | 0.212 | 0.057 | 2.60× |
| Small triangles | 98.616 | 37.207 | 5.370 | 1.149 | 6.96× |
| Large surfaces | 489.268 | 38.918 | 3.768 | 0.655 | 10.84× |
| Procedural 400 | 174.423 | 74.848 | 7.955 | 1.405 | 9.00× |
| Procedural 5,120 | 846.859 | 678.966 | 88.207 | 14.267 | 7.70× |
| Procedural 13,312 | 1,829.176 | 1,626.176 | 243.272 | 37.333 | 7.00× |

The 13,312-triangle scene takes 222.856 ms at 128 px and 251.907 ms at
512 px in the C++ backend; paired gains versus batch-first are 4.57× and
9.61× respectively. Paired gains are medians of repeat-wise ratios, so
they need not equal a ratio of the timing medians. In particular, tiny
submillisecond cases have substantial relative noise.

Raw observations: [native-raster-v1.json](../evidence/native-raster-v1.json).
Validation, host limitations and source binding:
[native-raster-validation-v1.json](../evidence/native-raster-validation-v1.json).
ARM/Android execution and a Vulkan backend are outside this experiment.
