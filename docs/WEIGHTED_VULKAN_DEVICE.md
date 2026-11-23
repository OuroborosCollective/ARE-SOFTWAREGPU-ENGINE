# Experimental ARE Vulkan CPU device for Linux

This isolated developer ICD connects the Khronos loader to ARE. A native client creates a device, a graphics pipeline, a render pass with two linear memory-backed attachments and a primary command buffer. At queue submission the driver reads the vertex buffer, applies the supported vertex shader, clips the triangles and submits immutable draws to the native ARE C++ raster. The application can map and read RGBA8 and D32 images after completion.

The optional build requires Linux x86-64, a C++17 compiler, CPython development headers and shared library, NumPy, the Python Vulkan CFFI declarations (vulkan 1.3.275.1), Vulkan headers and registry XML, the system Vulkan loader, vulkaninfo, glslangValidator and spirv-val. Build and verify from the source checkout with a fresh output directory.

```sh
python -m software_gpu.drivers.verify_weighted_icd evidence-local/weighted-vulkan
```

The C++ application links to libvulkan. The loader selects the developer manifest only in the subprocess environment. The original zero-device admission still has its own manifest and independent checks. Use trusted, isolated processes with the developer driver. There is no system driver registration.

## Supported pipeline

The build binds two validated SPIR-V binaries to the hand-written native lowering for the pinned position/RGB shader sources. The pipeline accepts a triangle list, one interleaved Float32 position/RGB vertex buffer, a full positive-height viewport, single-sample RGBA8 and D32 attachments, strict less depth and opaque writes. Unknown shader modules and unsupported pipeline configurations fail creation. Native raster conversion and coverage obey the existing ARE numeric contract. Device enumeration in this experimental profile is separate from Vulkan conformance. General Unity shaders, textures, descriptors, WSI and swapchains require further implementation.

## Measured queue selection

The opt-in SQLite learner uses a Vulkan-specific scope bound to host, driver binary, pipeline implementation, packet and initial frame. The native strategies execute separate ordered draws or concatenate their triangles in order. Four measured pairs check RGBA, Float32 depth and raster counters. Subsequent fresh processes consult the persisted model. A slower candidate remains eligible for periodic retesting under the existing policy. Learning changes native submission selection only.

The verifier saves vulkaninfo output, loader diagnostics, mapped color/depth bytes, SHA-256 digests, the learning database, shader modules and per-submit receipts. It checks raster coverage and interpolated RGB against the input triangle, rejects a different validated shader, and checks byte-identical images across five separate client launches.

## Unity 6 acceptance player

Copy the contents of `tools/unity_vulkan_probe/` into the Assets directory of a fresh Unity 6 project. Run the Editor in batch mode with `-executeMethod BuildProbe.Build` and set `ARE_UNITY_PLAYER` to the absolute output executable path. The fixture builds Linux standalone with only Vulkan enabled. Launch the generated player with `-force-vulkan` in an isolated X display and select the developer ICD for that process. A successful application exits zero after recording the actual ARE device identity and checking two triangle readbacks with different fragment colors. The shader and render target deliberately exercise Unity's own pipeline. A startup error, fallback renderer, timeout, unsupported shader or missing readback marker fails this admission.
