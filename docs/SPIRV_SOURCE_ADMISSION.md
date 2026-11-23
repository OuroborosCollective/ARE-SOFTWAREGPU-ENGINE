# SPIR-V P0 real-source admission (Issue #313)

This slice adds a **source intake**, not a Vulkan ICD or shader interpreter.
It is deliberately independent of the canonical ARE C++ raster.
There is no SPIR-V-to-ARE-IR lowering, buffer/image binding, VkShaderModule,
VkPipeline, VkQueueSubmit, WSI or Unity runtime path in this PR.

## Real pipeline and evidence
```text
GLSL vertex and fragment source
  -> real glslangValidator -V --target-env vulkan1.1
  -> original .spv module bytes
  -> bounded wordstream inspection (no trust or execution implied)
  -> real Khronos SPIRV-Tools spirv-val --target-env vulkan1.1
  -> SHA-bound, positive validator result and exact unchanged module hash
  -> receipt explicitly states ARE shader execution = FALSE
```

Linux CI on an ephemeral Ubuntu-24.04 runner installs glslang-tools and
spirv-tools, compiles **real** GLSL triangle shader modules and runs the
validator on each. The test suite also rejects malformed module headers,
truncated instructions, missing memory model, unsupported capabilities,
duplicate entry points, unknown execution stages, and absent validator.
Negative synthetic byte arrays are *only* parser test inputs and are never
accepted as real shader runtime evidence.

The limited preflight recognizes Vertex and Fragment `OpEntryPoint` only,
Shader capability (1), and supported logical memory model declarations.
It deliberately refuses extra shader capabilities pending source-level
review. Full syntactic/semantic validity is the actual external
`spirv-val` process, **not** the header parser.

## Existing ARE boundaries and remaining translation contracts

| Vulkan responsibility | Current verified ARE source | Gap to implementing a real Vulkan device |
| --- | --- | --- |
| Shader ingest | `software_gpu/drivers/spirv_admission.py` verifies genuine shader source | OpCode/Type/Constant/Variable/Function -> ARE IR lowering and tests **missing** |
| Vertex stage | `software_gpu/graphics/shader.py` Python `Shader.vertex_shader` and `Vertex` | SPIR-V variables, attributes, descriptor bindings, clip-position and interpolation semantics **missing** |
| Raster | `native/raster/core.hpp`, `driver_adapter.hpp/.cpp` CPU vertex-color packed triangles | Native SPIR-V shader invocation and shader module/resource-to-ARE bridge **missing** |
| Memory | `software_gpu/core/memory.py` host virtual memory subsystem | Vulkan heap types, VkBuffer/VkImage/VkDeviceMemory, map/unmap/visibility and lifetime ownership **missing** |
| Queue / command buffers | No Vulkan command queue | Recording, ordered submit, pipeline objects, synchronization and barriers **missing** |
| Presentation | Current headless RGBA8/Float32 Depth | Linux surface/swapchain/acquire/present **missing** |
| Vulkan Loader | PR #314 real Mesa Lavapipe reference | ARE ICD negotiation, dispatch objects, physically enumerated ARE device **missing** |

A valid source module is only an *input candidate*. We must neither
advertise a `VkPhysicalDevice` nor claim Unity/renderer compatibility based
on it. The first valid native execution milestone must use a
real shader-lowered Vulkan triangle whose output bytes are compared to
the ARE CPU raster under the documented strict-depth, top-left,
Float32-order and submission-tie contracts. A fixed-color shortcut and
a renamed Mesa Lavapipe renderer are not acceptable substitutions.

The 100-ms / 10-Hz world tick and rendering/presentation remain separate.

**Next decision gate:** compare the actual Mesa Lavapipe SPIR-V -> NIR
implementation, licenses and upkeep with a separately owned small
translator on the concrete shader fixture corpus. Record observed
opcodes/resources, supported and unsupported transformations, integer/
Float32 contracts, source SHAs, tested binaries and CTS scope before a
render backend claims SPIR-V support.

## Execution
```sh
python -m unittest software_gpu.tests.test_spirv_admission -v
# Linux only, with actual glslangValidator and spirv-val installed:
# See .github/workflows/spirv-source-admission.yml for the exact shader
# source, invocation, revision and artifact admission.
```

The workflow's original GLSL, SPIR-V modules and receipts are archived
without standing in for a running Vulkan loader or functioning ARE shader.
