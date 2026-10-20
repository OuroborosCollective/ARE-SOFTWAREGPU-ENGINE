# Experiment: Wolfram + C++17 Doppler **ohne** SpherePop

This research variant uses `native/raster/doppler_only.hpp`. Unlike the previous wavefront, it imports **no** SpherePop code, queue, event graph, staged Bind/Pop/Collapse history, or area completion map. Every target pixel is evaluated directly relative to the same fixed physical source position. The same owner-ID/depth rejection and artistic red/blue magnitude mapping are preserved.

**Independent Wolfram Language oracle:**

```wolfram
FullSimplify[{120/(120-30),120/(120+30),120/(120-0),
  120/(120-30/Sqrt[2]),120/(120+30/Sqrt[2])}]
(* {4/3, 4/5, 1, (4 (8+Sqrt[2]))/31, (4 (8-Sqrt[2]))/31} *)
```

These are ratios of classical acoustic wave frequencies for a moving source and stationary observer. They are **not** speedups, relativistic optical Doppler, PBR spectral accuracy, or a reproduction of every previous SpherePop pixel (the previous algorithm's emitter position changes at each hop). The center point is neutral by explicit policy.

**Real native A/B contract:** `native/raster/doppler_only_native_test.cpp` invokes actual `are::raster::draw` with two triangles to produce a 32² and 64² framebuffer. Runs each identical geometry at **raster-only**, **direct Doppler without SpherePop**, and **SpherePop+Doppler** (existing reference) for 15 alternating CPU repeats after warmups: 90 timed full-frame draws total. Reports all positive individual times, medians, paired ratios, tinted count, duplicate refusal count, depth and framebuffer debug digests. Alpha, background and float32 depth must be unchanged; negative depth, invalid buffers, velocity budget, wrong CPU rounding and FTZ/DAZ must fail closed. No artificial success threshold for timings. FNV-1a debug checksums are not cryptographic receipts; CI job logs and exact SHA bind measurements.

**Important fairness limit:** the image output differs between direct Doppler and chained SpherePop+Doppler because direct rays go from one fixed source while the chain's local emitter changes. CPU timings isolate the cost of these different algorithms with the same native raster input, **not** same-output algorithmic equivalence. No new production dispatcher, GLB importer or audio implementation is activated.

Run:

```bash
python -m unittest software_gpu.tests.test_doppler_only_wolfram_native -v
python -m unittest discover -s software_gpu/tests -v
```
