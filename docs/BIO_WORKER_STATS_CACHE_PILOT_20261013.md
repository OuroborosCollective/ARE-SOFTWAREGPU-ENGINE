# Cacheline-isolated worker accounting: actual PR #60 evidence (2026-10-13)

**Disposition: admit the research-only build switch; DO NOT promote it to the default renderer.**
The release/default policy, C++17 float32 raster contract, shader ordering and checkpoints
are unchanged. Zero proven production performance improvement is claimed.

## Provenance and scope

- GitHub PR [#60](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/pull/60), tested head `88b34eed17753cde6a06353060d72f5f801ed0ac`.
- GitHub [native parity, 15-pair pilot, and 40-cell full sweep](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38350237007): **PASS**; PR merge-test checkout `64f18140ff5bbc239d1fad0e9acd3e7a1a7a0646`, not the branch head. The GitHub workflow binds this checkout to the tested PR head.
- [Full 40-case raw JSON artifact 11790492499](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38350237007/artifacts/11790492499): ZIP SHA256 `30efa08273f95922ad5bdef5c1ad6c2b9a4b8fc19446aa772a364bceb7955072`; `benchmark.json` SHA256 `d6aab414aa191412cc1d4e44f0e311245ceaaaebb7b5c59e1e65e2c8a05db155`.
- [Independent 8-case 1/2-worker pilot artifact 11790596432](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38350237007/artifacts/11790596432): ZIP SHA256 `320efc138a8416b947a5423a25bc566036fd0223619c4448032bf0f42a9d282d`; `benchmark.json` SHA256 `0acb84916ae5bd8b7ae6b2a346d1a526581dcfd3006ae9186c88059d09908c0f`.
- Full run: 5 compile-time variants × 2 real native fixture scenes × 4 worker counts (1/2/4/8) = 40 cells, 15 warm-candidate timings and 15 frozen-historical-baseline timings per cell. All candidate cases retain `full_frame_parity=true`, `handoff_ready=true`, `worker_parity=true`; exact resolved/RGBA/float32-depth digests agree across workers and variants. Independent Python render/depth oracle test **PASS**, including 1/2/4/8 workers.
- GitHub-hosted Azure Linux x86_64 with **4 logical CPUs**, CPU affinity `[0,1,2,3]`; 8 workers oversubscribe this runner. Source hashes, compiler flags, binary SHA256, raw timings, IQR/MAD and frame digests remain in the raw artifact.
- [CPU regression CI](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38350236999) and [external Mesa comparison CI](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38350237001) both **PASS**, but neither proves a hardware GPU frame match.

## Direct same-workflow variant medians (ms; lower is better)

**Important:** These are candidate-versus-candidate medians from sequential variant sweeps on a shared runner. The reported per-variant `ratio_of_medians` in raw JSON compares against a separately timed *frozen historic renderer*, **not** against another research variant. The following percent is `100 * (padded-worker-stats / default - 1)`. Negative is faster; positive is slower.

| Scene | Workers | Default (ms) | Padded stats (ms) | Padded change |
|---|---:|---:|---:|---:|
| sparse64-tile1 | 1 | 5.883 | 5.891 | +0.1% |
| sparse64-tile1 | 2 | 4.407 | 5.453 | +23.7% |
| sparse64-tile1 | 4 | 3.736 | 3.549 | -5.0% |
| sparse64-tile1 | 8 | 3.992 | 3.778 | -5.4% |
| large4-tile16 | 1 | 6.751 | 6.875 | +1.8% |
| large4-tile16 | 2 | 3.759 | 6.106 | +62.4% |
| large4-tile16 | 4 | 3.322 | 3.343 | +0.7% |
| large4-tile16 | 8 | 3.426 | 3.431 | +0.1% |

### Independent earlier-on-the-same-PR pilot (15 repeats; 1/2 workers)

| Scene | Workers | Default (ms) | Padded stats (ms) | Padded change |
|---|---:|---:|---:|---:|
| sparse64-tile1 | 1 | 5.861 | 5.901 | +0.7% |
| sparse64-tile1 | 2 | 5.538 | 4.296 | -22.4% |
| large4-tile16 | 1 | 6.699 | 6.833 | +2.0% |
| large4-tile16 | 2 | 3.814 | 3.868 | +1.4% |

The sparse64/2-worker result **reverses sign** between runs (-22.4% pilot, +23.7% full sweep), consistent with run-to-run/scheduling noise. The large4/2-worker full-sweep regression is a serious negative finding. Do not hide either by aggregating the cases into one misleading global speedup.

## Admission decision and remaining questions

- **Safe to merge the opt-in research variant only** when final head CI is green and the append-only `Memory.md` entry is present: the default binary has no `ARE_BIO_PAD_WORKER_STATS` flag and remains unchanged; the optional compiler switch uses per-worker `alignas(64)` statistics.
- **Unsafe to promote as default:** no repeatable general speedup; small and very different scenes; no fixed processor frequency/thermal observations, perf c2c HITM samples, proven isolation beyond the declared runner affinity, Windows-native-specific build parity or production GLB/PBR benchmark for this switch. One GitHub runner is not a production optimization certificate.
- The pre-existing 64-byte pending/fence alternatives are separately controlled and untouched. Padding worker statistics cannot eliminate true shared-cursor or shared-checkpoint contention.
- For future policy selection, use an isolated controlled host with cross-variant alternation, consistent compiler/CPU affinity, 15+ paired runs and honest negative cases; include native PBR workloads and additional CPU-time/variance profiling.
