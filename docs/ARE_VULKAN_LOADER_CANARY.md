# ARE real Khronos Vulkan Loader canary — Issue #313

**Stage:** isolated, source-built Linux ICD negotiation and instance lifetime
with **zero Vulkan physical devices**. This is a deliberate fail-closed
integration boundary; it is **not a functioning GPU**, not a Vulkan renderer,
and not Unity-compatible.

The canary is a genuine independently compiled ARE C++17 ELF shared library,
not Mesa Lavapipe, not an alias to any other Vulkan device and not a fake
`VkPhysicalDevice`. It exports the proper Khronos
`vk_icdNegotiateLoaderICDInterfaceVersion`,
`vk_icdGetInstanceProcAddr` and optional
`vk_icdGetPhysicalDeviceProcAddr` hooks. The real system
`libvulkan.so.1` Loader can invoke `vkCreateInstance`, a loader-magic-tagged
`VkInstance`, `vkEnumeratePhysicalDevices` and `vkDestroyInstance`.
Zero devices are returned until full ARE-owned VkDevice/queue/memory/resource
and executable pipeline contracts exist. Unknown functions return null.

## Run and validate (unprivileged, isolated)

The exact-head CI workflow `.github/workflows/are-vulkan-loader-canary.yml`
installs genuine Linux Vulkan development headers/loader as temporary
GitHub-runner dependencies, compiles `native/vulkan/loader_canary.cpp` to
`build/libare_vulkan_canary.so` and writes a temporary manifest:

```json
{"file_format_version":"1.0.0","ICD":{"library_path":"/absolute/working/path/build/libare_vulkan_canary.so","api_version":"1.0.0"}}
```

The manifest is **not** written to system ICD search paths. The test isolates
selection through `VK_DRIVER_FILES`, calls `libvulkan.so.1` via the real
Khronos API, expects a successful **instance** and **zero** devices, and
records exact Git source revision, ARE C++ and binary SHA-256, manifest SHA,
API return values and immutable canonical receipt digest. Direct inspection of
ICD negotiation alone is **not accepted** as Loader integration proof.

All features, extensions, surface operations, device memory, queues, command
execution and performance/weights remain **unavailable**, rather than
misrepresented. In particular:
- `are_vkphysicaldevice_exposed = false`
- `are_vulkan_graphics_functional = false`
- `are_weighted_graphics_execution = false`
- `unity_runtime_verified = false`

## Remaining gates, not proven by this PR

1. Implement actual immutable, memory-safe Vulkan resource/instance/device
   objects with resource lifetimes, one truthful CPU queue, command buffers,
   synchronization and limits without unsupported feature claims.
2. Bind genuine validated shader instructions/SPIR-V to the native C++ raster,
   and verify actual Vulkan images with RGBA8 + Float32 depth, replay and
   reference parity. Python-only SPIR-V is not native shader execution.
3. Once feature complete, expose a truthful ARE-owned `VkPhysicalDevice`
   through the **real** system Loader and confirm `vulkaninfo`,
   Vulkan validation and matching CTS slices; then genuine Unity Player and
   Editor tests with source/device/frame identity.
4. Thread the existing SQLite `LocalLearner` profiles through bounded
   CPU execution alternatives and real measured output parity **outside**
   the Vulkan dispatch and gameplay-authority tick. Never promote a
   weight-only synthetic success to functional Vulkan evidence.

Licensing: Khronos Vulkan-Headers and Vulkan-Loader are upstream APIs/tools;
this canary does not vendor Mesa sources. No global installation, display
server replacement, Vulkan device registration, Unity process modification or
production effect is performed.

Sources: Khronos Vulkan-Loader `LoaderDriverInterface.md`,
Khronos Vulkan-Headers `vk_icd.h`. This code is a deliberate first protocol
proof only.
