# Source-textured GLB versus exact Godot game-frame parity

The previous coarse CPU preview is **not** a material correctness or game pixel parity reference: it samples one texture pixel per triangle, subsamples larger meshes to 36,000 triangles and applies painter-order output without a native float32 Z-buffer. This distorts colors and occlusion. Never classify its image hashes as full glTF PBR or Aurion game-equivalent.

## Genuine source-PBR readback (offline, not published as a render backend)

On the ten owner-supplied originals the independent bounded external VTK 9.6.2 / Mesa EGL **llvmpipe CPU** renderer imported the original GLB bytes and bound the glTF base-color textures, material factors, and additional PBR textures supported by VTK without decimating triangles. All ten original-file SHA-256 identities matched `evidence/owner-public-glb-batch-20261020.json`; every native EGL draw produced a real 512x512 PNG and a SHA-bound receipt. 10,140,549 total submitted source triangles across distinct renders. No original file was modified. This is **external Mesa CPU validation**; not an ARE native C++17 render, not a hardware-GPU render, not Android FPS and **not pixel parity with Godot**. The small rigged Aurion GLB uses `KHR_materials_specular` and `KHR_materials_ior`; VTK treatment of these extensions is not equivalent to a verified game implementation.

Reproducible local evidence: `owner_glb_source_pbr_evidence_20261020.json` and `owner_glb_diagnostic_vs_source_pbr_20261020.png` in the owner's conversation workspace, not assumed to exist in GitHub. This research PR contains no original GLB binaries or generated images.

## Native contract gate

`python -m unittest software_gpu.tests.test_owner_glb_frame_pixel_parity -v` exercises the fail-closed comparison logic. `python tools/owner_glb_frame_pixel_parity.py --reference godot.png --candidate are.png --reference-contract godot.json --candidate-contract are.json --receipt readback.json` compares the **decoded RGBA8** buffers without silently resizing, color-correcting, reinterpreting samples or accepting mismatched materials/camera/light/ticks. Exit 0 = exact pixel match, exit 1 = mismatch, exit 2 = incompatible/missing capture contract. A passing synthetic gate test does not prove any actual GLB frame parity.

The canonical Aurion Godot config readback uses Godot 4.7's `gl_compatibility` renderer, ETC2/ASTC import support, and default clear color `Color(0.025,0.045,0.065,1)` (in `OuroborosCollective/Echoes_of_Aurion/godot-client/project.godot`). To claim actual game fidelity, record source GLB hash, engine/scene revision, exact camera view/projection, lights/environment, material configuration/texture compression, color space, tonemap, sampling, animation timestamp, and frame tick. Capture the **actual Godot** and ARE framebuffers using the same immutable inputs, run this gate, and verify a 0-pixel-difference receipt. If unsupported glTF extensions, normal-map tangent basis, postprocessing, or sampling differ, treat it as a renderer compatibility task, not a cosmetic preview tweak.

This PR leaves production/native renderer, gameplay authority, and previous benchmarks untouched.
