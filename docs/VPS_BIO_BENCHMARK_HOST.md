# Shared 8-vCPU Sovereign/Aurion host: protected SoftwareGPU benchmark lane

**Status: preparation only — NOT deployed or benchmarked on VPS.** The owner
authorizes work on the shared host, but Sovott reports `SSH_NOT_CONNECTED`.
No SSH key/password or machine command has been acquired from that tool.

## Observed host evidence, 2026-10-13 (Sovott private host broker)

- 8 logical CPU cores; 33,650,176,000 bytes RAM, roughly 24.1 GB available;
  one-minute load ~4.458 (load/8 ≈ 0.557 > pilot cutoff 0.25). This is shared with active Sovereign, Aurion and
  databases — they must not be stopped, restarted or throttled for benchmarks.
- Root/opt/docker share a 416,055,988,224-byte filesystem: 369,491,529,728
  bytes in use (**88.8081%**), 46,564,458,496 bytes available.
- Resource-pressure assess emits `P0 FILESYSTEM_CAPACITY_PRESSURE` above
  85%. **Both pilot and full are therefore STOP until an approved, separate
  cleanup changes the real readback**. No script overrides this pressure.
- No previous native-vs-native benchmark collected on this VPS, and no
  hardware PMU/`perf c2c` capability has been established.

## Bounded non-root workflow

`tools/vps_bio_host.py` is **Linux-only** for execution; it can be imported
by Windows CI for pure gate tests. It checks a clean **exact 40-hex SHA**
checkout and rejects root execution and excess load, insufficient memory,
disk pressure, CPU affinity shortages and concurrent runs.

| Profile | Worker sweep | CPU affinity | RAM address-space cap | Admission |
| --- | --- | --- | --- | --- |
| Pilot (default) | 1,2; packed vs padded | 2 cores | 4 GiB | ≥8 GiB free, disk usage <85%, per-affinity-core load ≤0.25 |
| Full (explicit only) | 1,2,4,8; four research variants | 8 cores | 4 GiB | ≥20 GiB free, disk usage <85%, load/core ≤0.15, `--confirm-full-window` |

Both use `nice +15`, finite subprocess wall/CPU limits and file-size limits,
a lock to prevent two benchmark sessions, and SHA-bound native build/frame
readback. They do not open a service, touch Docker, modify Sovereign/Aurion,
use Python in the native raster hot loop, or request remote secrets.

### On the host, only after Owner SSH restored and storage pressure cleared

Use a non-root, dedicated account with a bounded private workspace on the
**existing** VPS, not a new cloud service. Recheck the exact merged SHA at
runtime, install compiler/Python/NumPy dependencies in an isolated venv and
never use root or bind to public TCP ports.

```bash
# In a clean exact-SHA checkout of OuroborosCollective/ARE-SOFTWAREGPU-ENGINE:
head="$(git rev-parse HEAD)"
python tools/vps_bio_host.py inspect --expected-sha "$head"
python tools/vps_bio_host.py plan --expected-sha "$head"
# ONLY when both admission results say GO:
python tools/vps_bio_host.py run --expected-sha "$head"
```

Do **not** run that command today unless the real live gate permits it.
A full sweep additionally requires the dedicated quiet measurement window
and the explicit `--confirm-full-window` flag. Prefer low-impact pilot
before contemplating an eight-core run on a shared production machine.

`inspect` and `plan` are read-only (no output-directory or lock creation);
`run` uses a private output directory and creates
`benchmark.json` + `vps-host-readback.json` only after all admission
conditions pass. CPU-time, wall-time and result receipts are separate; a
passing receipt does not establish sustained multicore scaling.

### Evidence and failure handling

- On failure, preserve logs without deleting production data or bypassing
  resource gates; no restart or Docker prune.
- Any external performance number must show source/build/host SHAs,
  measured medians and IQR/MAD, affinity, actual CPU load and framebuffer
  / depth parity. A shared, busy VPS is not a clean benchmarking host.
- A `perf c2c` cache audit requires supported host PMU access. In its
  absence report `PERF_C2C_UNAVAILABLE` rather than claiming HITM evidence.
- This is a separate **deployment/test plan**, not a public Gradio service,
  GPU benchmark or validated 8-core improvement.

Existing technical foundation: [frontier cache experiment](BIO_FRONTIER_CACHE_ABLATION.md),
[real CI-pilot and negative cases](BIO_FRONTIER_CACHE_PILOT_20261013.md).
