# Bio frontier cache: measured pull-request pilot (2026-10-13)

This report **only summarizes real native measurements** from the exact GitHub
Actions PR #58 checkout. It is not a performance certification, not an independent
CPU cache/PMU audit, and does not change the production policy.

**Source evidence:** [32-case run 38339193637](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38339193637), [full raw artifact 11786391901](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38339193637/artifacts/11786391901) (GitHub retains workflow artifacts for 30 days).
- `benchmark.json` 175,426 bytes; SHA-256 `aa248450e85e350ea9bf4284bc6f96da53ada16c755623a79a679f5b6ecf9abb`.
- GitHub artifact ZIP SHA-256 `5b3a2da8d97c482dc59541a8ee3966341cbedc298b91d2e64e7d2f499e8a5885`.
- PR merge-test checkout `f831ab03267e7a719c223adcce5f5d218afea224`, PR head `fcf440aa3e76ea6e7b9f78a3544b0402c9560d89`.
- Python is build/orchestration only; actual elapsed frame timing is inside native C++17.
- Hardware environment: GitHub-hosted Azure x86_64 Linux, **4 logical CPUs**, affinity `[0,1,2,3]`; 8 native workers **oversubscribe** this host.
- All four variants compiled; **32 cases**, 15 alternating baseline/candidate pairs each, strict native framebuffer/resolved/depth equality and matching cross-variant frame digest; the separate [native parity job](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38339193637/job/115106135055) verified actual independent Python RGBA/depth oracle.

## Actual candidate medians, milliseconds (smaller is better)

These are the candidate frame medians from the run. Do **not** use each
variant's separate frozen-historical-baseline ratio as a direct causal
between-variant speedup.

| Scene / CPU workers | Default packed + acq_rel | Padded pending | Release+acquire fence | Padded+fence |
| --- | ---: | ---: | ---: | ---: |
| sparse64, tile=1, 1 worker | 4.698 | 4.781 | 4.690 | 4.770 |
| sparse64, tile=1, 2 workers | 4.599 | 4.755 | 3.473 | 4.595 |
| sparse64, tile=1, 4 workers | 3.026 | 2.956 | 3.103 | 2.964 |
| sparse64, tile=1, 8 workers | 3.346 | 3.300 | 3.232 | 3.130 |
| large4, tile=16, 1 worker | 5.366 | 5.378 | 5.364 | 5.373 |
| large4, tile=16, 2 workers | 3.097 | 4.850 | 3.011 | 2.878 |
| large4, tile=16, 4 workers | 2.642 | 2.640 | 2.669 | 2.653 |
| large4, tile=16, 8 workers | 2.738 | 2.789 | 2.818 | 2.717 |

- **Negative case:** the padded-only 2-worker large4 frame is **4.850 ms** versus **3.097 ms** for default, in this run. It must not be hidden or averaged away.
- **Positive but unproven candidate:** the release/fence 2-worker sparse64 case is **3.473 ms** versus **4.599 ms** for default. The lack of a repeat on a controlled fixed-affinity host means this **cannot** establish causal cache benefit.
- **Scaling limit:** default large4 4 workers **2.642 ms**, 8 workers **2.738 ms**; on a four-logical-CPU host additional threads did not help this scene. That is **not** proof of false sharing.
- No clear, broad win across all eight scene/worker combinations. **Default remains unchanged.**

## What is still necessary before choosing an optimized default

Run the same 32 cells **repeatedly** on an isolated native Linux benchmark host,
with pinned CPU affinity, processor frequency/thermal context, source compiler flags
and current-source hash readback. Use `perf c2c` only if PMU permissions and the
specific CPU allow useful HITM sampling. Compare HITM by address and source offset
between packed/padded layouts. Run TSAN/ASAN/UBSAN and a C++17 memory-order
review separately. Only after consistent full-buffer parity and meaningful
speedup across the target workloads should any research variant become a default.

Until then, this document records *exploratory evidence with negative cases*,
not an optimization decision. [Research methodology](BIO_FRONTIER_CACHE_ABLATION.md).
