# Shared VPS: ARE SoftwareGPU Bio CPU benchmark safety gate

This is a **read-only host check and an explicitly opt-in native benchmark** for
the VPS already running Sovereign and Echoes of Aurion. It does **not**
install a permanent daemon, Docker container, public Gradio listener, firewall
rule, SSH key, service unit or package publisher. It never restarts existing
services. Python only checks preconditions and orchestrates the real C++17 binary.

## Verified host snapshot on 2026-10-13

Via the already connected **Sovott host capacity broker** (not SSH):

| Metric | Observed |
| --- | ---: |
| Logical CPUs | 8 |
| RAM | 33.65 GB total, 24.10 GB available |
| Disk | 416.06 GB total, 46.56 GB free |
| Disk used | **88.81% — broker P0 capacity pressure** |
| 1-minute load | 4.458 across 8 logical CPUs |
| Sovereign and Aurion | Existing Docker containers running |
| Owner SSH session | **SSH_NOT_CONNECTED** |

**Admission for today's snapshot: STOP.** The non-root `pilot` profile
requires disk at most 85% used and 1-minute CPU load no higher than
0.25 × available affinity CPUs; this snapshot fails both. The full
profile is stricter and requires explicit `--confirm-full-window`.
No benchmark process was executed on this host while these gates failed.
Do not delete, prune, restart or reconfigure Sovereign/Aurion merely to
make capacity numbers pass.

## Deploy procedure after restoring SSH and host headroom

Use the existing authenticated owner-managed SSH mechanism. A persistent
remote shell is **not presently available through the GitHub or Sovott
tools in this conversation**, so these are verifiable handoff instructions,
not a claim that deployment has happened.

On the host, use an unprivileged local benchmark account. Verify that the
configured checkout is exactly the reviewed SHA and that its tracked
working tree is clean. Use a dedicated output directory under the
account's home, not Docker's filesystem. Install dependencies without
a privileged system-wide package mutation (approved Python venv and C++17
compiler). Never put secrets in the receipt.

```bash
# Execute only from the checked-out ARE-SOFTWAREGPU-ENGINE repository
EXPECTED_SHA="$(git rev-parse HEAD)"
python tools/vps_bio_host.py inspect \
  --profile pilot --expected-sha "$EXPECTED_SHA"
```

`inspect` prints an explicit GO/STOP JSON decision and returns a nonzero
exit when resource pressure is unsafe. This is the **first** action on the
VPS; it does not render or allocate significant workload.

Only after checking that Sovereign and Aurion latency, backups and health
remain stable, and that the **fresh** host gate says GO:

```bash
python tools/vps_bio_host.py run \
  --profile pilot --expected-sha "$EXPECTED_SHA"
```

The pilot restricts worker affinity to at most 2 CPUs, increases OS nice
priority value to 15, uses 4 GiB virtual address-space limit, a 1 GiB
file-size limit, finite CPU and wall-clock limits, and a single-run file
lock. It executes `tools/benchmark_frontier_cache.py` on two fixed
fixtures, 1 and 2 workers, default and padded-only variants, 15 native
paired repeats. No network listener is opened. A `PASS` receipt is accepted
only with exact HEAD, expected count of cases and framebuffer parity.

The full 1/2/4/8-worker × 4-variant sweep is **not** cleared by a successful
pilot alone. It is allowed only if the VPS is quiet, has 8 available
affinity CPUs, disk below 85%, at least 20 GiB free disk and 8 GiB free RAM,
and the owner deliberately requests `--confirm-full-window`. Do not run
the full profile during Aurion/Sovereign workloads.

## Evidence and monitoring

- Record the initial admission JSON, exact Git commit, kernel/CPU model,
  compiler/build flags, process CPU affinity, raw native benchmark JSON and
  SHA-256, before/after service health, memory/load/disk snapshots.
- Record all regressions; do not select the fastest variant using a single
  noisy observation or compare different hosts as one hardware ranking.
- On failure, leave the production services untouched and capture the
  benchmark stderr/exit only. The source code remains unmodified.
- Profile with `perf c2c` only if the VPS virtual CPU exposes suitable PMU
  capabilities and security policy allows it. Do not change kernel
  `perf_event_paranoid` globally simply to obtain performance counters.
- The host has a shared VPS hypervisor. Even after a GO admission, no isolated
  metal-level throughput guarantee or independent False Sharing proof follows.

Related: [native frontier research](BIO_FRONTIER_CACHE_ABLATION.md) ·
[real GitHub pilot](BIO_FRONTIER_CACHE_PILOT_20261013.md).
