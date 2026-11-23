# Native deterministic CPU command submission — Issue #313

**Status:** opt-in API-neutral P0 command execution on ARE's real C++17 raster core.
It is **not** a Vulkan ICD, `VkCommandBuffer`, `VkQueueSubmit`, shader
pipeline, Vulkan memory API, or Unity renderer.

The existing `are_driver_draw_v1` interface is intentionally unchanged.
`software_gpu.drivers.command_submission` adds the smallest useful ordered
command envelope *above* that boundary:

```text
caller-provided prepared triangles (23 Float64 fields per triangle)
 -> record_native_draws() (copy immutable bytes; digest per record)
 -> frozen packet (ordered per-draw digests and combined digest)
 -> submit_native_draws() (validate full packet + frame + budgets)
 -> isolated staging RGBA8/Float32 depth buffers
 -> real AREDriverBridge.draw_packed: reference = separate ordered draws;
    parity-gated candidate = concatenated ordered triangles in one C++ draw
 -> compare full staged RGBA8 + Float32 depth + sample counters in paired probes
 -> commit staged buffers only if ALL real native draws succeeded
 -> observed final SHA-256(color), SHA-256(depth), counts, native binary SHA
```

## Verifiable properties

- Frozen `NativeRecordedDraw` dataclass and immutable byte payload detach the
  recording from subsequent edits to NumPy inputs. No global queue,
  background scheduler, or wall-clock simulation influence.
- Captured 23-f64 triangle records have exact packed count/size and SHA-256.
  Packet digest binds the sequence of individual record counts and hashes.
  All packet and framebuffer contracts are rechecked before the first draw.
- Up to 256 ordered records with a total of 200,000 triangles, up to 4,194,304
  pixels and a conservative submission budget of 64 million triangle-pixel
  candidates. Unsupported profiles (e.g. `spirv-vulkan`) fail closed.
- The API wrapper retains original RGBA8 and Float32 depth intact on a
  late native failure, including a nonfinite triangle in the final draw:
  only the scratch buffers are mutated. Committing two output arrays is
  synchronous and requires exclusive caller ownership. It is **not** a
  thread-safe or crash-atomic transaction and does not claim disk persistence.
- The existing native raster's strict-less depth, first-submission tie owner,
  top-left rule and ordered Float32 contract are preserved, with real replay
  parity against direct native calls.
- Every nonempty native command packet consults the existing opt-in
  `software_gpu.learning.LocalLearner` SQLite store. Each native command
  profile is host-/CPU-/binary-/source-/packet-/initial-frame-hash-bound;
  per-command samples preserve the original reference/candidate timing,
  complete output digests and match/block status in that *same* database.
  Four successful real paired probes and the existing speed/recency gates
  precede candidate routing; periodic rechecks apply unchanged. A single
  command is observational only and creates no fake optimization variant.
  On unset/off/unavailable learning the normal native reference runs.
- The alternative collapses multiple **ordered** prepared triangles into
  one genuine C++ draw call without modifying shader/raster logic. A/B
  parity includes complete RGBA8, Float32 depth and coverage counts.
  Candidate mismatch or error blocks that saved profile, and does not
  publish candidate output. No speedup is asserted without source-bound
  paired timings on the actual target workload.
- Historical `ARE-Lerndaten.zip` source revision
  `e898487ef655698513441d660d4cbe813699ea3f` contains separate
  host-bound raster/FFmpeg profiles and **does not** certify performance
  of this new profile; never migrate stored weights across source hashes.
- The existing restricted SPIR-V subset in PR #317 still runs on Python
  CPU tiles. Native C++ shader execution is **not** silently enabled.

Run the original integration tests from the source checkout:

```bash
python -m unittest software_gpu.tests.test_native_command_submission \
  software_gpu.tests.test_native_command_weights \
  software_gpu.tests.test_driver_adapter \
  software_gpu.tests.test_learning_route_coverage -v
```

CI matrix: `.github/workflows/are-native-command-submission.yml` on Linux
and Windows. The dedicated negative/positive weight test uses real native
C++ output, a temporary SQLite file, and a controlled saved-weight edit as
**selection-only evidence** (not as synthetic speed evidence). Original
Linux and Windows full-frame parity receipts remain artifact-backed.
Exact-HEAD full regression/receipt and independent merge readback
are separate admission requirements; running the test file alone does not
prove a Vulkan loader device, WSI or Unity Scene/Game viewport.

**Next actual Vulkan milestones:** define Vulkan resource/object lifetime,
bound Vertex/Index/Descriptor/Pipeline contracts and synchronization;
connect an actual SPIR-V/NIR shader backend to native draw execution;
then implement real Loader/ICD entry points and run `vulkaninfo`, Vulkan
Validation and CTS against a truly ARE-owned CPU `VkPhysicalDevice`.
