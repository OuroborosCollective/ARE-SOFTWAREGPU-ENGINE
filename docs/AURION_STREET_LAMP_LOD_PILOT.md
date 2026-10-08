# Aurion original street lamp: offline CPU fixture pilot

This is a read-only research path for Issue #6, **not a live Aurion adapter**.

## Original source and provenance

The owner supplied 4 original `Aurion_Street_Lamp_LOD[0-3].glb` files in conversation on 2026-10-09. Their SHA-256, sizes, vertex and triangle counts are pinned in [manifest.json](../fixtures/aurion/street_lamp/manifest.json).

| LOD | Vertices | Triangles | Original GLB bytes |
|---|---:|---:|---:|
| 0 | 4089 | 4172 | 2514256 |
| 1 | 3368 | 3128 | 2484916 |
| 2 | 2605 | 2086 | 785232 |
| 3 | 1629 | 1042 | 259136 |

All four GLBs contain one mesh, one material and three images. **The originals are NOT checked into the repository**: source hashes in the manifest are evidence of uploaded originals, not proof that a GitHub runner has them. CI can verify a real synthetic GLB2 payload and worker behavior, but cannot claim to have rendered the four owner GLBs until they are explicitly supplied to its runner.

## Run the real original fixtures

Place the four unchanged owner-provided GLB files into a private `/path/to/originals` directory, and run:

```bash
python -m pip install -e .
python -m software_gpu.integrations.aurion.offline_lod_worker \
  --model-dir /path/to/originals \
  --output-dir /tmp/are-aurion-lamp-evidence \
  --pixels 192 --repeats 2 --timeout 90 --memory-mb 4096
```

Each file must match its exact original SHA-256. No network service or token is used. Results include real CPU-drawn BMPs, source/output digests, multiple-run exact replay checks, elapsed times and a JSON receipt. Run only on trusted local files and in a sandbox.

## What is measured and what is not

- CPU geometry-only flat shaded view at a fixed camera, resolution and deterministic triangle order.
- The renderer uses ARE's actual tile pipeline, not a thumbnail mock. Source GLB metadata and buffers are decoded with bounded and validated accessors.
- Real spawned process timeout/kill and Linux `RLIMIT_AS` (not a complete cross-platform memory sandbox); no Aurion world-state or 100-ms-tick writes.
- Pixel replay hash is required to match repeated renders on the **same** host.
- glTF PBR shading, normal/texture mapping, skeletal animation and full Aurion WebGL/WebGPU equivalence are **not** validated.
- Previously measured CPU reference images and their hashes are **not** ARE outputs and are only an independent visual/LOD baseline.
- Differences in LOD image shapes are expected: no byte-equality claim across LOD levels.

## What remains before marking Issue #6 fully complete

1. Make all four original GLBs available as pinned inputs on the GitHub runner via an authorized artifact/source import, or a trusted private asset channel.
2. Run repeated ARE rendering against those **exact** originals, store real output image/receipt evidence, compare against Aurion's existing asset pipeline on the same host.
3. Establish measured benefit (new error detection, deterministic evidence or lower measured compute overhead). If no advantage, keep the integration optional and offline.
4. Only then consider an independent read-only Aurion CI integration PR. No gameplay or render-runtime replacement.

No ScaNN or network service is involved.
