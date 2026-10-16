# What CPU Rasterizer Benchmarks Really Prove

A renderer gets faster. The profiler says "8x." Does that mean it can replace a GPU? No. Before trusting the number, we need to answer: *What ran? What was the baseline? Did it produce the same pixels?*

This is a practical account of experiments behind [ARE SoftwareGPU Engine](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE), a CPU-first graphics research project. It is **source-available under PolyForm Noncommercial 1.0.0**, not OSI-licensed open source or a hardware GPU driver. The following measurements compare CPU paths against CPU paths.

## Define correctness before benchmarking

Software rasterizers can appear faster because they accidentally skip work. Our experiments check near-plane clipping, shared-edge top-left coverage, strictly defined depth ties, perspective-correct interpolation, and full color/depth output parity.

To reproduce a comparison, use the same source revision, scene, camera, geometry, draw order, random seeds, framebuffer size, and shader inputs. Save the **RGBA bytes and float32 depth bytes** (or their cryptographic hashes) from each path. If the output differs, explain the divergence before reporting an optimization as equivalent.

The useful question is not only *how many milliseconds did we save?* but *did we render the same contract?*

## Three benchmarks with three different meanings

The repository records the following scoped results:

| Reported gain | Measured CPU comparison | Boundary |
| --- | --- | --- |
| **7.00x** | Native C++17 vertex-color raster test versus Python/NumPy batch-first, 13,312 triangles at 256 × 256 | Not a PBR test or hardware GPU comparison |
| **1.554–1.709x** | Native bio-inspired PBR path versus a native PBR baseline on measured original-model scenes | Scene-specific, not a universal speedup |
| **8.40x** | Optional experimental deferred visibility plus batch shading versus Python tiles, five overlapping layers at 96 × 96, two workers | Combines two effects; research configuration only |

The native model and PBR experiments are described in the [benchmark methods and evidence](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/blob/main/docs/BIO_RENDERER_PERFORMANCE_EVIDENCE.md). The deferred experiment's [PR and CI receipt](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/pull/73) let readers inspect the exact provenance.

**Do not multiply the gains together.** The baselines, algorithms, workloads, and environments differ.

## A controlled three-way ablation changes the story

An 8.40x result can sound like deferred visibility alone is transformative. But that comparison also includes batch shading. A separate three-way experiment compared deferred processing with a dedicated batch-first control:

- Five overlapping layers in far-first order: **1.42x** over batch-first in the measured paired runs.
- One layer: **1.03x**.
- Five layers in near-first order: **0.91x** — the deferred variant actually lost.

This is why an optimization should be tested under different scene structures and draw orders, not only its most favorable case. These numbers belong to one specific workload, not a guarantee for arbitrary games or scenes. Details and source-bound CI receipts are collected in the [repository README](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE#beste-belegte-cpu-ergebnisse--spitzenwerte-zuerst).

## A reproducible CPU benchmark checklist

1. Pin the source commit SHA and every imported scene/model asset hash.
2. Document CPU, operating system, compiler/interpreter versions and worker count.
3. Use identical scene input and framebuffer dimensions in every compared path.
4. Test color and depth parity, including difficult clipping and occlusion cases.
5. Collect repeated paired wall-time samples, not a single best frame.
6. Report both wins and losses, with the precise baseline for each claim.
7. Keep experimental and production paths visibly distinct.
8. Do not extrapolate CPU-vs-CPU numbers to graphics hardware, gameplay frame rates, or other hardware.

The source repository includes a [quickstart](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/blob/main/docs/QUICKSTART.md), [project showcase](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/blob/main/docs/SHOWCASE.md), and detailed [licensing information](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/blob/main/docs/LICENSING.md). Interested graphics programmers can inspect the tests and run their own counter-experiments.

## What this work does not claim

This project does not demonstrate hardware-GPU parity, a CUDA/Vulkan/DirectX replacement, universal FPS targets, or a production-ready cloud rendering service. Research variants are not automatically enabled in every runtime. Its noncommercial source license requires separate permission for commercial use.

**AI assistance disclosure:** This educational article was prepared with AI assistance, using the publicly documented test and benchmark evidence linked above. Results and limitations should be independently checked against the cited source revisions; AI assistance did not perform new benchmark runs for this article.

---

*Have you encountered benchmark wins that disappeared when you changed draw order, scene density, or the baseline? Reproducible negative results are especially welcome in the discussion.*
