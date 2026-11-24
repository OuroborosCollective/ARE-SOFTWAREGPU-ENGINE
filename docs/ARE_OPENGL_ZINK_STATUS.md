# ARE OpenGL / Mesa Zink: genuine Vulkan capability preflight

Baseline source: 134bb723449456775003d76e77248a582da94b21.

- A real Khronos loader enumerates the ARE CPU Vulkan 1.0 ICD and presents
  two native XCB frames. This is not OpenGL support.
- Isolated Ubuntu 22.04 Mesa23.2.1 GLX control loads llvmpipe, succeeds,
  but is not ARE. Zink forced with only the ARE ICD exits 139 (SIGSEGV),
  with no OpenGL renderer and no Heaven FPS/Score. Root crash stack unproven.
- Native Vulkan query reports five absent GL2.1 baseline features and
  fifteen absent device extensions / alternative extension groups.
  Never set false advertised capabilities simply to make GLX start.

The native/vulkan/weighted/opengl_zink_capability_probe.cpp client queries
the real Vulkan loader. software_gpu/drivers/verify_opengl_zink_preflight.py
checks the exact Git SHA, ICD manifest and native library SHA, raw CLI
exit code, actual Vulkan device identity and capability consistency.
It records an explicitly incompatible status; it NEVER reports that an
OpenGL context or Heaven score was obtained. Unknown exit codes, fake
identities, changed source revisions or contradictory JSON fail closed.

## Next independently testable implementation stages

1. Implement real generic SPIR-V shader paths, descriptor-set allocation
   and uniform/storage/image resource bindings with hash-bound tests.
2. Implement texture samplers, buffer transfers, layouts, blending,
   dynamic rendering/attachments, additional depth/color formats and
   correct pipeline compatibility.
3. Advertise Vulkan features/extensions only after their actual native
   execution has passed independent frame, depth and negative tests.
4. Demonstrate Mesa Zink -> ARE on an actual OpenGL context with
   GL_RENDERER identity AND Vulkan ARE native submission/driver SHA.
5. Extend to the Heaven-required GL context and collect a complete
   Heaven 4.0 run with true ARE GLX + frame provenance and FPS/score.

Mesa requirements: https://docs.mesa3d.org/drivers/zink.html.
No Unity/Windows/Wayland/system-driver/global-loader certification.
