# ARE SoftwareGPU Engine — shareable project brief

Public, evidence-first introduction for graphics developers, teachers, CPU optimization researchers and benchmark enthusiasts. These are **suggested descriptions**, not claims that a publication or press outreach has already occurred.

## English short description

**ARE SoftwareGPU Engine** is a source-available CPU-first graphics research project from OuroborosCollective. Explore deterministic software rasterization, tile binning, optional Numba/LLVM JIT, depth/color parity tests, a bounded native C++17 glTF/PBR research path, and reproducible benchmark receipts. A private Gradio console can run isolated CPU render samples. This is **not** a hardware GPU, CUDA, Vulkan or DirectX replacement.

[Repository](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE) · [Showcase](SHOWCASE.md) · [Original-model evidence](native-pbr-arena-report-20261013.md) · [Quickstart](QUICKSTART.md) · [Licensing](LICENSING.md)

## Deutsche Kurzbeschreibung

**ARE SoftwareGPU Engine** untersucht Software-Rasterisierung auf CPUs: Tile-Rendering, genaue Farb-/Tiefentests, optionales LLVM-JIT, native C++17-Modell- und PBR-Forschung und reproduzierbare Benchmarks. Eine optionale, authentifizierte Gradio-Oberfläche zeigt echte Offline-Renderjobs mit Prüfsummen. Kein GPU-Treiber und kein Versprechen von 60 FPS oder Hardware-GPU-Parität.

[Quellcode](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE) · [Bilder und Belege](SHOWCASE.md) · [Schnellstart](QUICKSTART.md)

## What can a visitor verify?

- Source, docs and tests are publicly browsable on GitHub.
- CI source and results can be inspected [here](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions); successful historical jobs are **not** a current deployed service.
- [Measured benchmark evidence](native-pbr-arena-report-20261013.md) includes case/scene assumptions, hashes and CPU-vs-CPU limitations.
- [Rendered reference sample](SHOWCASE.md) is committed evidence, not a claim of a running public Gradio service.
- Android APK, Node/Linux and Windows artifacts are downloadable **only when actually present** in [GitHub Releases](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases). Check [release status](RELEASE_STATUS.md) first.

## Audience and contribution ideas

Interesting reproducible contributions: Float32 edge cases, top-left triangle coverage, first-submission depth ties, near-plane clipping, raster CPU scheduling, native GLB/PBR import rejection tests, platform CI, and independent timing audits. Include real scene/fixture hashes, raw timings, source SHA and framebuffer/depth equivalence. Follow [contributing instructions](../CONTRIBUTING.md).

## Licensing and distribution

Code is **PolyForm Noncommercial 1.0.0**, source-available and not an OSI-approved open-source license. Keep the required notice, preserve third-party rights, and ask for a separate written commercial license where needed. Do not label it MIT/Apache/open source or promise unrestricted commercial reuse.
