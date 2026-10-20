# Single-Origin Impact Wave — CAG/SpherePop-inspired CPU renderer research

**Alternative effect semantics; not a byte-identical optimization of chained SpherePop.** The default code path remains unchanged. This isolated C++17 header `native/raster/single_origin_impact_wave.hpp` implements one source per impact, zero queue insertions and zero re-emissions. A clipped impact rectangle is scanned once; a circle radius determines affected cells. Each affected cell is completed exactly once by a single row-major pass; no per-pixel SpherePop event is generated.

Wolfram math oracle checked `sqrt((x-x0)^2+(y-y0)^2)/c` and 120/(120±30). Unlike the historical 8-neighbor shortest-path arrival time (octile metric), an impact radius and wave arrival use Euclidean distance. The time expression is defined analytically but **the research kernel currently applies the effect instantaneously**; it does not animate a time-based front or persist completed areas across calls. Experimental Doppler color uses the same classical fixed-source formula and red/blue artistic tint as the prior render profile. This is not audio Doppler or a physical propagation simulation.

## Correctness and truth boundaries

Actual native C++17 triangles render into RGBA8 + float32 depth + object owner IDs. Comparison against the existing chained SpherePop wave includes two resolutions, byte-stable replay of each mode, owner/alpha/depth untouched outside target cells, no-Doppler neutral case, boundary source and radius zero, clipped radius, invalid-depth rollback and disallowed velocity. **Different source semantics produce different RGB**, so no cross-mode image identity is expected or asserted. Unlike the chained wave, `spherepop_starts==1`, `reemissions==0`, `queue_pushes==0` and `refusals==0`; the processed-cell counter proves that within one call every in-radius cell is visited once.

Baseline is the **already optimized chained renderer** (`reuse_factor=true`). Native A/B uses 15 alternating complete raster-and-effect runs at 32×32 and 64×64 on the same runner. Times, raw samples, repeats, frame digests, exact head and source hash should be retained in the CI evidence before any README speedup claim. Higher resolutions, textured GLB, full game FPS, shader sorting and production dispatch are out of scope. Do not mix this comparison with the Python Tiles-vs-C++ leaderboard or claim identical visual output.

### Test entrypoint

```bash
python -m unittest software_gpu.tests.test_single_origin_impact -v
python -m unittest discover -s software_gpu/tests -p 'test_*.py' -v
```

**Candidate future enhancement:** event time/ring masking by `distance / wave_speed`, with deterministic per-impact IDs and cross-frame policy. No persistent hit-state is implemented here, so the same source can be invoked again on another render frame.
