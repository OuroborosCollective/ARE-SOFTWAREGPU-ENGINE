# Private Gradio CPU arena

Optional UI over the **existing real** Phase-4 isolated offline render worker.
This is **not** the native GLB/PBR benchmark in `tools/benchmark_models.py`,
not a GPU device and not part of Aurion game authority. No original GLB
uploads, non-pinned sources, filesystem arguments or remote URLs are accepted.

## Local use

```sh
python -m pip install -e ".[gradio-arena]"
export ARE_GRADIO_USER=owner
export ARE_GRADIO_PASSWORD='replace-with-a-long-random-unique-password'
python -m plugins.gradio_arena.app
```

Open **http://127.0.0.1:7860** on the same machine and authenticate.
Never bind it to 0.0.0.0 or use public `share=True`; put a separately reviewed
authenticated tunnel in front of loopback if remote access is ever needed.
Keep credentials out of Git, environment dumps and browser examples.
Only the local owner can operate the UI. No Hugging Face Space is deployed.

The form chooses a strictly bounded seed and the repository-owned procedural
fixture, resolution 64/128/256, and one of three existing backends:
`tiles`, `tiles-plan`, `bands`. For each job a separate real child renderer
uses the canonical worker's admission checks, subprocess deadline, CPU and
memory budget; UI queues at most three jobs, with only one active.
Each result carries a real BMP framebuffer preview, replay digest, image file
digest, sample times, source/revision and resource receipt. Failures are not
converted into successful previews. No temporary asset is preserved.

## Verify

```sh
python -m unittest software_gpu.tests.test_gradio_arena -v
python -m unittest discover -s software_gpu/tests -v
```

The test suite includes an actual isolated 64x64 CPU render with readback,
plus invalid-input and missing-authentication negative tests. CI must pass on
the final PR head, including Windows, Linux, JIT and Mesa jobs. Existing
coverage gates remain unchanged.

## Evidence limits

UI response/render time includes network, queue, Python and browser costs,
and is **not** a CPU renderer benchmark. For 15-repeat paired performance
with source-hash audits use the existing SoftwareGPU Workbench and
`tools/benchmark_models.py`; do not compare timings from separate hosts
as a hardware performance claim. This opt-in UI intentionally does not
expose original GLB assets or PBR rendering until the same safety and
manifest gates can be implemented without exposing private source files.

## Public visibility

The owner approves public distribution of non-sensitive SoftwareGPU test scenes,
source-backed benchmark receipts and UI screenshots. The public repository and
Three.js reference documentation may be shared. This permission does not require
opening a remote command/render endpoint: the computational Gradio process retains
its password-protected loopback listener, fixed resource limits and finite queue.
A later externally hosted demo must first provide an authenticated, rate-limited
execution boundary and verify it with live readback before claiming it is online.
