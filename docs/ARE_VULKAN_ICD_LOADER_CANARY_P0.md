# ARE-owned Vulkan ICD loader canary — Issue #313

**Stage:** Actual Khronos Loader-ICD handshake and Vulkan 1.0 instance-level
admission, without falsifying a usable graphics device. This is NOT the
final ARE software Vulkan GPU. No host driver installation occurs.

- Compile `native/vulkan/are_loader_canary.cpp` **together with the actual**
  `native/raster/driver_adapter.cpp`, which exports ARE's native CPU-raster ABI
  in the *same* library. This binds source/compiled binary to ARE, not Lavapipe.
- Expose real `vk_icdNegotiateLoaderICDInterfaceVersion`,
  `vk_icdGetInstanceProcAddr`, and the minimal Vulkan 1.0 instance calls.
- A real application linked to the Khronos loader uses a **temporary isolated**
  `VK_DRIVER_FILES` manifest. It calls `vkCreateInstance`, then
  `vkEnumeratePhysicalDevices` and destroys its instance. Loader debug must
  show real calls to the ARE-owned library, not a Mesa alias. Our ICD returns
  `VK_SUCCESS` with count 0. The Ubuntu Khronos loader was observed translating
  that **negative no-device** case to `VK_ERROR_INITIALIZATION_FAILED` (-3)
  without returning a device count. The verifier accepts that result *only*
  if native ICD call tracing independently proves the real zero-device return.
  It must not call this a usable Vulkan device or claim `vulkaninfo` sees ARE.
- Until true VkDevice/queue/resources, executable shaders and native
  render commands are implemented, our ICD reports **zero** physical devices,
  all physical-device queries expose zero capabilities on unsupported handles,
  and `vkCreateDevice` fails closed. It is forbidden to advertise a fictional
  `VkPhysicalDevice` or convert a no-device loader rejection into a device pass.
- The same library's `are_driver_abi()` must return 1, its CPU-only
  capabilities must still deny Vulkan/WSI/SPIR-V. Existing ARE native
  raster/float32/depth and 100-ms gameplay tick remain untouched.
- The original source revision, full native source SHA mapping,
  native binary SHA, probe binary SHA, manifest SHA, loader stdout/stderr
  hashes and truthful zero-device count go into a canonical SHA256 receipt.
  The CI uploads the **actual** receipt.

The admission test on Linux runs:

```sh
python -m software_gpu.drivers.verify_loader_canary \
  --expected-revision "$(git rev-parse HEAD)" \
  --output evidence-local/vulkan-loader/receipt.json
```

It requires libvulkan-dev and the real system Vulkan loader. No fake
loader, shim-replacement libvulkan, synthetic success, or mock physical
device is permitted. `vulkaninfo` seeing an ARE device, validation layers,
CTS draw, textures, SPIR-V-to-ARE compilation, VkQueueSubmit, WSI,
Unity Player/Editor and Zink remain **unverified**.

**Next P0 milestone:** Implement real VkDevice, bounded resources,
VkCommandBuffer/VkQueueSubmit with genuine ARE C++ triangle output
and full color/depth replay. Only then can the device enumerate as
`VK_PHYSICAL_DEVICE_TYPE_CPU` with honest limits/features.

**Learn-weights contract:** This canary performs no rendering via Vulkan
and therefore must not fabricate per-driver learning samples. The previously
merged `LocalLearner` native command path remains operational. Future real
Vulkan submission can share its SQLite storage with separate source-,
host-, packet- and pipeline-bound weights after actual parity, not by copying
historic profiler numbers.
