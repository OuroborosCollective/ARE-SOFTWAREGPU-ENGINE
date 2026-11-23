# ARE SoftwareGPU as a Vulkan/OpenGL software device — P0 driver adaptation

**Decision date:** 2026-11-23. **Implementation status:** first source-tree native CPU
driver-adaptation slice; **NOT** a Vulkan ICD, registered GPU, WSI, OpenGL
driver, or Unity renderer. The [research issue/PR](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/pull/312)
is the integration record. The existing PolyForm Noncommercial license and
required notice apply. Khronos/Mesa/SwiftShader are architectural references;
no upstream third-party driver sources are copied or linked by this P0.

## Genuine external Vulkan Loader reference probe (Issue #313)

The opt-in `software_gpu.drivers.vulkan_reference` command launches the real
`vulkaninfo --summary` executable against an **installed Mesa Lavapipe** ICD,
using `VK_DRIVER_FILES` to isolate it. It requires actual `VkPhysicalDevice`
CPU enumeration, a Mesa llvmpipe/Lavapipe device name and Vulkan Loader
stderr that mentions the selected software driver. It archives the original
summary and loader log with hashes, the manifest digest, full source revision
and a canonical receipt digest. Errors or ambiguous device identity fail closed.

The dedicated Linux CI installs the distribution's `vulkan-tools` and
`mesa-vulkan-drivers` on an ephemeral runner; nothing is registered on the
VPS or an owner's workstation. The verified CPU Vulkan device belongs to
**Mesa**, *not to ARE*. `are_vulkan_icd=false` and
`are_loader_device_verified=false` remain explicit fields even after the
reference runs successfully. This is an external loader/platform preflight,
**not** an ARE graphics API implementation and not an FPS benchmark.

Example from a Linux host with its actual Mesa software driver installed:

```sh
python -m unittest software_gpu.tests.test_vulkan_loader_reference -v
python -m software_gpu.drivers.vulkan_reference \
  --manifest /usr/share/vulkan/icd.d/lvp_icd.x86_64.json \
  --source-revision "$(git rev-parse HEAD)" \
  --output evidence-local/vulkan-lavapipe/receipt.json
```

**Next actual source spike:** inspect the exact Mesa Lavapipe/NIR SPIR-V
front-end and shader-to-raster handoff against `native/raster/core.hpp`,
`native/raster/driver_adapter.hpp`, `software_gpu/graphics/shader.py`,
`software_gpu/core/memory.py`. Produce a checked operation/feature matrix
before choosing Mesa/NIR integration or a new ICD. No `vk_icd*` stubs or
manual generated manifest may be promoted to a functioning ARE device.

References: [official Vulkan Loader driver interface](https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderDriverInterface.md)
and [Mesa software driver runbook](https://docs.mesa3d.org/install.html).

## The verified architectural boundary

```text
Existing Python geometry/clip + VertexColorShader (source checkout)
    -> 23-f64 packed triangle records, explicit ordered-f32 contract
    -> software_gpu.drivers.native_bridge (opt-in, digest-bound ctypes)
    -> are_driver_draw_v1 / are_driver_capabilities_v1 (C ABI v1)
    -> existing native/raster/core.hpp :: are::raster::draw
    -> caller-owned RGBA8 and IEEE Float32 depth (headless)
    -> SHA-256 over exact color/depth bytes

NOT IMPLEMENTED:
    Vulkan Loader -> Vulkan ICD -> VkPhysicalDevice
    SPIR-V -> compiler/IR -> Vulkan shader execution
    Vulkan WSI/surface/swapchain/present
    Mesa/Gallium/Zink OpenGL, DXGI/WDDM/DRM, Unity
```

The native library exports only `are_driver_abi`,
`are_driver_capabilities_v1` and `are_driver_draw_v1`. It does **not** export
`vk_icdGetInstanceProcAddr` or `vk_icdNegotiateLoaderICDInterfaceVersion`,
is **not** shipped with a Vulkan ICD JSON manifest, and must **never** be
advertised through `VK_DRIVER_FILES` or a registry key. No unsupported
features, vendor ID, Vulkan version, physical device, or frame rate are invented.

### Core and effect invariants

- The original `native/raster/core.hpp` numeric algorithm, packed layout,
  edge top-left convention, strict less-than depth, first-submission tie
  ownership and Float32 operation order are untouched. Build flags prohibit
  fast-math and fused contraction.
- Typed ABI v1 rejects unknown profile/flags/reserved/struct sizes **before**
  running the rasterizer. Its only supported profile is the existing
  prepared-vertex-color triangle format. No arbitrary SPIR-V or descriptors.
- Requests are bounded to 200,000 triangles, 4,194,304 pixels, 4,096 per
  dimension and 64 million candidate samples per draw. Native core validates
  *all* triangle records before any pixels or counters are written.
- Non-overlapping, aligned, caller-owned memory is required. The Python
  wrapper validates NumPy dtype, shape, contiguity and buffer aliasing; the
  native bridge additionally rejects overlapping declared ranges. As with
  the existing C ABI, arbitrary pointers from an untrusted process are
  **not** memory-safe: this is a trusted in-process boundary only.
- No background draw queue, global device singleton, system installation,
  kernel driver, network, PBR, renderer auto-selection, or simulation mutation.
  Render timing and future WSI presentation must stay separate from any
  deterministic 100-ms/10-Hz world tick.

### Reproduction (source checkout)

```bash
python -m unittest software_gpu.tests.test_driver_adapter -v
python -m unittest software_gpu.tests.test_native_raster -v
python -m unittest discover -s software_gpu/tests -v
```

The test builds and loads a *real* C++17 shared library, calls the actual
rasterizer with nonempty triangles, compares complete RGBA8 **and** Float32
depth against the independent existing native adapter, repeats the draw with
identical input, and checks SHA-256 of both buffers. Malformed profile,
descriptor sizes, nonfinite late triangles, overlap and binary hash mismatch
must fail closed without modifying images/counters. A source/build receipt
records compiler version/flags, source hashes and binary hash.

These tests prove only the CPU bridge for their actual environment and exact
commit. A passing Python unit test or published workflow **does not** prove
that Unity, the Vulkan Loader, Mesa or any OS discovered this adapter.

## Phased API/device implementation decision

| Priority | Surface | Required concrete implementation | Evidence / stop gate |
| --- | --- | --- | --- |
| P0 done only after CI | Native Driver Adapter Layer | Real C ABI to existing CPU raster and typed truthful capabilities | Exact PR-head Linux/Windows real C++ color/depth replay, failure atomicity, source/binary hashes |
| P0 research | Mesa Lavapipe integration vs own ICD | Source spike: map NIR/SPIR-V, image/buffer, descriptors, command-buffer and queue ownership onto ARE | Code-level ownership and license/maintenance decision; **no claim of ICD** |
| P0 future | Linux headless Vulkan ICD | Loader negotiation/dispatch; instances, physical/logical device, queues, memory, resources, shaders, pipeline and submit; honest CPU `VkPhysicalDevice` metadata | Actual `VK_DRIVER_FILES` isolated `vulkaninfo --summary` and full dump, loader debug proves ARE library, Validation and CTS subset |
| P1 | Offscreen graphics | SPIR-V vertex+fragment, real Vertex/Index Buffer, descriptor/pipeline/triangle, depth/blend | Vulkan triangle rendered via *real* ICD; full frame/depth hashes and negative validation |
| P1 | Linux WSI | X11 or Wayland surface, swapchain, acquire/present separated from submit | Window visibly presents real ARE-generated frames; WSI evidence independent of offscreen proof |
| P1 | Unity Player then Editor | Force Vulkan + select ARE device with other ICDs isolated | Real Player.log / Editor.log: Vulkan device identity and loader binding, shader compilation, Scene/Game views, consecutive frames |
| P1 | OpenGL | Zink on full ARE Vulkan feature profile; alternatively new Gallium `pipe_screen/pipe_context` driver | Required Zink profile + `glxinfo -B` or EGL device evidence; native frame/depth regression |
| P1 | Windows Vulkan | Build Windows ICD DLL and supported software-driver loader registration | Windows `vulkaninfo`, loader+Validation logs, Unity Player/Editor smoke |
| P2+ | DRM/KMS, WDDM, virtual displays | Only after a documented requirement for kernel adapter, D3D or remote display | Actual OS display/adapter identity; never equate IDD/VKMS with rendering |
| Not planned | Native macOS `MTLDevice` injection | No publicly documented generally installable third-party software Metal GPU route | No fake Metal/Unity claim |

**Architectural caution:** A Gallium driver permits OpenGL through Mesa state
trackers but does **not** automatically yield a Vulkan ICD. Zink is OpenGL
on Vulkan and requires substantially more Vulkan features than a single
triangle. Lavapipe internals are not a generic Gallium-to-Vulkan adapter.
SwiftShader/Lavapipe are reference software ICDs, **not ARE backends** until
real execution is traced to ARE. WARP is a comparison renderer, not an
extensible ARE rasterizer.

### Independent runtime evidence for future Vulkan admission

Pin `repo SHA -> compiled ICD binary hash -> manifest hash -> loader log
-> vkPhysicalDevice identity -> validation/CTS subset -> framebuffer+depth
hash -> WSI presentation -> Unity logs`. Keep unknown/not executed separate
from failed, and never use generated JSON, a simulated `vulkaninfo` printout,
software device *naming*, CI green alone, or a mock Vulkan API as proof.
Reuse Khronos Loader, CTS and Mesa upstream references without unreviewed
license mixing; retain explicit owner approval for system driver registration.

References: [Khronos Vulkan Loader](https://github.com/KhronosGroup/Vulkan-Loader),
[VK-GL-CTS](https://github.com/KhronosGroup/VK-GL-CTS),
[Mesa Gallium/Zink/Lavapipe](https://docs.mesa3d.org/),
[Google SwiftShader](https://github.com/google/swiftshader),
[Unity command-line graphics selection](https://docs.unity3d.com/Manual/EditorCommandLineArguments.html).
