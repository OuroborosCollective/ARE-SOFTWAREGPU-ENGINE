# Read-only Wolfram / MIHA tools

Both tools are **offline opt-in** development utilities, outside CPU raster
hot paths, CI release dispatches and Aurion authority.

- `python3 scripts/wolfram_multiview.py --mesh mesh.json --script view.wl --png view.png` generates only a **Wolfram Language script**, not a PNG. Input JSON schema `are.offline-mesh.v1` includes a declared full `source_revision`, vertices and zero-based triangle indices. This declaration is NOT independently verified provenance. Use a separately authenticated local Wolfram execution to produce and hash a real render if needed. Resource version: MultiviewGraphics3D 1.0.0.
- `python3 scripts/miha_evidence_similarity.py --input source-ids.json --output candidates.json` takes `miha.source-multisets.v1` with a full `dataset_revision` and records with id/source_ids. Its exact rational Dice distances are **candidate ranking, not causal/source/payment evidence**. Empty source sets are insufficient evidence, not zero similarity. It never reads or writes the Hugging Face dataset.
- `python3 -m unittest software_gpu.tests.test_wolfram_offline_tools -v` tests both scripts without requiring Wolfram or Hugging Face services.
- No changes to live renderer, Godot, 100-ms tick, database, cloud credentials, or deployment are authorized by these tools.
- AdaptiveCellularAutomaton and HistoricalCountrySpacetimePlot remain research references; do not add randomness to the deterministic core or equate historical maps with evidence graphs.

Sources:
https://resources.wolframcloud.com/FunctionRepository/resources/MultiviewGraphics3D/
https://resources.wolframcloud.com/FunctionRepository/resources/MultisetDiceDissimilarity/
