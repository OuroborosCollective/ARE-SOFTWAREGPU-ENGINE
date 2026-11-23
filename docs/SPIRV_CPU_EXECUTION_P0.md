# Issue #313: Real SPIR-V straight-line shader execution on ARE CPU tiles

**Dependency state (2026-11-23):** Genuine SPIR-V input preflight PR #316
was merged to `main` as commit
`021aa90ffb1ddcedba65a980374e0dd0163484af`. This follow-up
PR #317 now targets `main` and must independently pass its full exact-head
CI, reviews and output parity before any merge. A focused green shader test
does not authorize promotion.

**Experimental opt-in only.** The genuinely compiled/validated
`shader_probe.vert` / `shader_probe.frag` SPIR-V modules now run through
`RestrictedSpirvProgram` on the existing ARE Python `SoftwareRasterizer`
`backend=tiles`. This is a restricted bytecode interpreter, **not** a
Vulkan driver, Mesa/NIR integration, arbitrary shader support, native C++
shader compiler or Unity renderer.

## Execution boundary

```text
glslangValidator --target-env vulkan1.2 [REAL external compiler]
             -> .spv bytes
spirv-val --target-env vulkan1.2 [REAL validator]
             -> exact validated bytes + SHA256
RestrictedSpirvProgram [EXACT admitted straight-line instructions]
             -> vertex: clip position and location-0 color
             -> fragment: RGBA Float32
ARE Python CPU tile rasterizer [REAL]
             -> RGBA8 / Float32 depth framebuffer
             -> compare bytes against ARE VertexColorShader reference
```

Only a single vertex or fragment `main` entry, one function and a
straight-line subset are supported. Explicitly handled:
`OpConstant`, `OpVariable`, `OpLoad`, `OpStore`, `OpAccessChain`,
`OpCompositeConstruct`, `OpCompositeExtract`, `OpReturn`, plus the
needed type/decorate/function metadata. Float32/Int32 are admitted;
buffer/image/texture, samplers, descriptors, compute, branches, loops,
atomics, barriers, ext-inst execution, raytracing and other opcodes
**raise UnsupportedSpirv**. Unknown inputs, outputs, access chains and
non-owned storage also fail closed.

`SoftwareRasterizer(backend=tiles)` invokes actual compiled SPIR-V
vertex code for each input vertex and actual compiled fragment code
for each sampled fragment. The acceptance test checks nonempty raster
output, actual interpreter call counts, full RGBA8 and depth-byte
parity against the existing ARE VertexColorShader and fresh-program
replay equality. Receipt includes exact source SHA and both shader
binary hashes; no hardware GPU comparison or FPS is claimed.

## Boundaries and future work

- The original C++17 `native/raster/core.hpp`, native Driver ABI v1,
  Float32 depth, Top-Left coverage, learn-weight, public rankings and
  any 100-ms gameplay tick are untouched.
- `supports_spirv` in the **native** driver capability remains false:
  Python interpreted shaders do not make the C++ driver SPIR-V-capable.
- No Khronos Loader interface, CPU `VkPhysicalDevice`, VkBuffers/
  VkImages, descriptors, queues, synchronization or WSI is added.
- For a Vulkan ICD, choose and implement a real shader translation
  path such as Mesa SPIR-V -> NIR -> new ARE shader backend or a
  bounded, independently conformant SPIR-V backend. Implement real
  VkDispatch/queue/resource/pipeline/submit and cross-check against
  Vulkan CTS/Validation, then WSI, Unity Player and Editor.
- New shaders and unfamiliar opcodes must be rejected until each
  behavior is implemented and demonstrated with its own real
  shader-run/full framebuffer/depth differential regression.

Proof command under GitHub Actions: `Real SPIR-V SSA -> ARE tiles
execution (not Vulkan ICD)`, preserving the real
`glslangValidator` binary output and `spirv-val` result with the
exact HEAD-bound receipt. Never promote loader-reference Lavapipe
or restricted Python shader tests into an ARE Vulkan-device success.
