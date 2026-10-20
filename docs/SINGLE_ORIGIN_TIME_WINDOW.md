# Single-Origin Impact Wave: stateless time-window pulse (C++17 research)

**Goal:** Animate a circle/shell from one CAG source without reintroducing SpherePop's per-area re-emission, pending queue or cross-frame progress. This is an isolated header `native/raster/single_origin_time_window.hpp`; the previously merged `single_origin_impact_wave.hpp` and production raster remain unchanged.

## Mathematics and boundary conditions

A grid area at integer pixel center `(x,y)` has Euclidean arrival time

`a(x,y)=hypot(x-source_x,y-source_y)/wave_speed`.

Wolfram confirmed `hypot(3,4)/5=1`, classical Doppler extrema `4/3` and `4/5`. With elapsed time `t` and positive duration `w`, an area is active iff it lies within impact `radius`, and `t-w < a <= t`. At `t=0` specifically the source itself is active. The **trailing boundary is open** to avoid a second hit at a shared tick boundary. No mutable hit-record survives a call; the caller must render each frame from its pristine source framebuffer if it requires an isolated single-pass visual effect.

Pixels outside the active interval, depth-winning non-target objects and background remain unchanged. Alpha and float32 depth are never changed. The velocity budget and native rounding environment are validated. Invalid dimensions, depth, owner/scene, duration, timestamps, velocity and buffer lengths are rejected without partial RGBA mutation.

## Real native validation

`native/raster/single_origin_time_window_test.cpp` rasterizes two real triangles through `are::raster::draw` at 32/64/128/256 px, checks exact RGB/alpha/depth equality to the existing instantaneous single-origin implementation when the pulse's window includes every impacted area, and checks replay equality at the same timestamp.

It compares 1-second adjacent windows at wave speed=1 around radius=3; **each area belongs to exactly one tick** (the seed at t=0). It tests the source, ended front, moving ring, target ownership, other meshes, error rollback, no-Doppler and four different framebuffer resolutions.

Three CPU modes use the same native raster, alternating 15 timed runs per mode/resolution: instantaneous reference, full time-window (identical RGB expected), narrow time-window ring (different output, smaller affected region). Timing includes rasterization, buffer creation and effect. Raw durations, medians and hashes are emitted to exact-head CI. There is **no guaranteed speedup**: a narrow wave performs less work and produces less image effect than the full-frame comparator.

The time-window kernel does **not** yet own persistent impact IDs, cumulative compositing, animation scheduling, GLB assets or production deployment. Benchmark entries belong in README only after the exact-head CI gates are successful; treat smaller ring times as computational cost, not a same-output speedup.
