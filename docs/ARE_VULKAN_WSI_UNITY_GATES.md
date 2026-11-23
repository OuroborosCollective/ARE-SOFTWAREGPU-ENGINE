# ARE real Vulkan WSI admission: Linux XCB/Xvfb -> Unity 6

**Status: SPECIFICATION ONLY.** A successful libvulkan1 install or an ARE CPU
RGBA framebuffer does not mean ARE supports VkPhysicalDevice, VkDevice,
VK_KHR_surface, VK_KHR_swapchain or the Unity Editor.

## Stable boundaries

- Authority: ARE's existing C++17 raster/driver ABI is the sole CPU raster
  execution target. Python SPIR-V admission alone is not native shader execution.
- Core: no wall clock, unseeded randomness, arbitrary Vulkan feature claims or
  gameplay simulation tick changes. Presentation never changes 100 ms / 10 Hz
  simulation authority.
- Renderer: 32-bit float depth (strict-less first-wins), top-left fill, exact
  color/depth parity and ordered commands remain invariants.
- Device truth: isolated `VK_DRIVER_FILES` points only at an independent
  ARE-owned ICD, never Mesa renamed to ARE. All capabilities must have actual
  working Vulkan operations before publishing a physical device.
- Owner-scoped Linux Ubuntu 22.04.5: `libvulkan1` was installed and its
  `vkEnumerateInstanceVersion` call returned API version 1.3.204. This is a
  loader receipt, not a Vulkan device or WSI test.
- No system-wide ARE ICD manifest, Unity process modification, compositor
  replacement or display-service change during early admission.

## Ordered integration stages (none may claim a later stage)

1. **CPU resource admission (PR #322):** owned, budgeted buffer and RGBA8/f32
   image; authentic C++ driver draw; repeated command replay; invalid second
   draw cannot partially commit; stale handles fail; paired Linux/Windows
   unmodified originals and receipt SHA-256. No Vulkan handles here.
2. **Actual Vulkan device:** loader accepts independent ICD and enumerates one
   ARE-owned CPU VkPhysicalDevice only after honest Vulkan-1.0 features, limits,
   format properties, memory heaps/types, queue families, device lifetime,
   synchronization, command pools, buffers and ordered native execution exist.
   Expose only supported SPIR-V capabilities and operations. Unsupported
   extensions are not advertised. Validate `vkQueueSubmit`, buffer-to-image,
   image/depth readbacks and native reference parity. A CPU picture from a
   non-Vulkan CLI is not this gate.
3. **Actual Linux surface:** `VK_KHR_surface` and the platform extension
   `VK_KHR_xcb_surface` are advertised only with working instance entrypoints
   and correct lifetime/connection ownership. Implement
   `vkCreateXcbSurfaceKHR`, `vkDestroySurfaceKHR`,
   `vkGetPhysicalDeviceSurfaceSupportKHR`,
   `vkGetPhysicalDeviceSurfaceCapabilitiesKHR`,
   `vkGetPhysicalDeviceSurfaceFormatsKHR` and
   `vkGetPhysicalDeviceSurfacePresentModesKHR`. Reject wrong connection,
   destroyed/foreign surfaces, invalid queue families and unsupported
   formats/composite alpha/extent. No hardcoded positive surface-support
   answer without an actual XCB surface and present path.
4. **Swapchain + presentation:** `VK_KHR_swapchain` is a device extension,
   advertised only after `vkCreateSwapchainKHR`,
   `vkDestroySwapchainKHR`, `vkGetSwapchainImagesKHR`,
   `vkAcquireNextImageKHR`, `vkQueuePresentKHR` and the
   image-availability/lifetime/fence semantics are implemented. Only bounded
   compatible image count/format/extent/present modes are accepted. Real
   compositor/Xvfb/XCB pixel readback must equal the actually rendered ARE
   RGBA image with documented byte order and row pitch. No fabricated
   display-vsync, FIFO or mailbox promise; correctness first.
5. **Actual process end-to-end:** compile driver with exact source SHA and
   preserve binary/hash + ICD manifest hash. Isolate loader with
   `VK_DRIVER_FILES`; run real `vulkaninfo`, Vulkan validation layers,
   applicable CTS slices, and a test application that opens Xvfb/XCB window
   and calls actual Vulkan Surface -> Swapchain -> Acquire -> Draw/Copy ->
   Present -> native XCB screenshot readback. Verify update after a second
   frame, resizing/out-of-date, destruction and negative present attempts.
6. **Unity Linux Player then Editor:** with actual ARE device selected by
   the installed Khronos Vulkan loader, run one Unity 6
   `-force-vulkan` Player under an isolated display; capture the Player.log
   device/vendor strings, source/driver identity, actual rendered scene and
   frame hashes. Only then test Editor Scene/Game view. Unity startup or
   rendering via Mesa llvmpipe is **not** ARE validation.

## Red/green negative-first matrix

| Boundary | Must fail safely | Positive evidence |
|---|---|---|
| Buffer | oversized allocation, stale or foreign handle, bad offset/stride | real native frame equivalence |
| Vulkan device | unknown feature/extension, invalid queue family, invalid memory type | real loader-enumerated ARE CPU device |
| XCB surface | disconnected X server, invalid window, wrong surface lifetime | actual Xvfb XCB window and VkSurfaceKHR |
| Swapchain | unsupported pixel format, extent, image count, dead surface | actual vkAcquireNextImageKHR/vkQueuePresentKHR |
| Synchronization | unsignaled fence, invalid semaphore order, use-after-free | ordered queue completion and pixel identity |
| Integration | wrong ICD JSON, stale binary SHA, Mesa fallback | device/binary/source/frame receipt chain |

A green build, isolated Loader API result, Xvfb window by itself or static
manifest does **not** upgrade any later stage.

Authoritative reference: Khronos Vulkan Loader Driver Interface
https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderDriverInterface.md

Tracking issue: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues/313
