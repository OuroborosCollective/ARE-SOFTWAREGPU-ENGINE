# Public-release intake: original Meshy GLB samples (2026-10-13)

The owner authorized public redistribution of these original GLBs. This commit
**does not falsely claim that the binaries are stored permanently in GitHub**.
It publishes exact original hashes and known external upload pointers. It does
not publish either MP4 (not authorized by the user for public hosting here).
The C++17 production shader/renderer policy remains unchanged.

| Alias | Triangles | Rig joints | Animation clips | Input bytes | Public source |
|---|---:|---:|---:|---:|---|
| azure-knight | 107,798 | 39 | 8 | 34,812,540 | External uploaded CDN asset; public reachability unverified |
| crimson-dragon | 91,084 | 81 | 0 | 34,114,068 | External uploaded CDN asset; public reachability unverified |
| maize-field | 7,653,974 | 0 | 0 | 235,861,308 | **Pending permanent large-file host** |

Source-of-truth manifest: `evidence/meshy-public-assets-20261013.json`.
It contains original filenames, size, SHA256, model metadata and source URLs.

Manual github workflow `meshy-original-assets.yml` checks the original two
external files with a finite size budget, SHA256 and GLB magic, returning only a
small JSON artifact and not republishing content in CI. Maize exceeds the upload
provider's 100 MiB file limit and remains unhosted. No silently decimated
substitute, fake frames, or subset-as-original is allowed.

Model compatibility is **not** proven by manifest readback. The existing native
`software_gpu.research.model_probe.load_asset` has an admitted subset of one mesh,
one indexed primitive, OPAQUE double-sided material, joint skin with LINEAR/STEP
TRS, no required extensions; these models appear to match this subset on static
metadata, subject to running the actual C++17 import/pose/PBR tests. The original
maize has 7.65M triangles and 4.17M vertices, close to native limits of 8M /
6.1M; budgeting the number of tile × face references is also necessary.
The original knight contains 78 TRS channels per animation; Dragon is rigged
but has no animation clips and should render using bind pose only.

Publishing GLB originals is owner authorized; downstream redistribution and use
still remain subject to Meshy terms and any embedded third-party IP rights.
No third-party license is fabricated here.
