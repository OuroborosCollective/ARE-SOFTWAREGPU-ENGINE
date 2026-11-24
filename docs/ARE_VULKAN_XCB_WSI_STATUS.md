# Experimental ARE Vulkan CPU ICD: real XCB WSI (not Unity certification)

The native/vulkan/weighted/xcb_wsi.cpp native transport and
software_gpu/drivers/weighted_icd.py expose a real XCB window Vulkan
WSI path onto the existing ARE C++17 CPU raster. The calling application's
real XCB connection and window are used, not a surrogate. The native backend
performs checked XCB PutImage and independent X Server GetImage per present.

## Narrow supported profile

- Developer opt-in, Vulkan 1.0 on Linux XCB, depth-24 TrueColor, little-endian.
- Two FIFO swapchain RGBA8 images and an associated D32_SFLOAT render target.
- One graphics queue, bounded allocations, opaque-alpha color presentation.
- Pinned known SPIR-V shader pair with 24-byte position/RGB vertex format.
- Acquire/fence/semaphore handling; resized surface makes old swapchain stale.
- Strict reject on unsupported feature, invalid window, wrong size or failed
  real readback; neither successes nor timings are invented.
- No system-wide ICD registration or changes to existing Unity processes.

## Reproduction

The dedicated workflow .github/workflows/are-vulkan-xcb-wsi.yml runs
software_gpu.drivers.verify_weighted_wsi on an isolated Ubuntu Xvfb display.
A genuine Khronos Vulkan Loader and native client create an ARE PhysicalDevice,
VkDevice/Queue, real VkSurfaceKHR, VkSwapchainKHR, render pass, and call
vkQueueSubmit and vkQueuePresentKHR. A separate XCB GetImage query verifies
actual window pixels; an independent NumPy reference verifies 384 RGB/Depth
samples in each of two distinct frames. Original lib/manifest/probe/source SHA,
frame hashes and negative logs are stored in the receipt.

## Explicitly unverified

Khronos CTS; generic Vulkan application shaders; Vulkan 1.1+; Wayland;
Windows WDDM; real Unity 6 Player, Editor or Scene View using ARE; native
Unity-rendered frame; global system driver installation; and gameplay FPS.
Do not close parent #313 based only on this narrow Vulkan XCB proof.
