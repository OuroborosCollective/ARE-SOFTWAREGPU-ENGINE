# Wolfram CAG geometric oracle pilot

This is **Computation-Augmented Generation (CAG)** as an **offline research and verification boundary**, consistent with Aurion's existing Wolfram CAG analysis design. It is **not** a GPU, rendering runtime optimization, second world authority, or authenticated Wolfram CAG API integration.

## Real Wolfram evaluation

A live Wolfram Language kernel evaluated exact rational expressions for:
1. Clipping of one triangle across the homogeneous near plane, with two new vertices and a remaining polygon area.
2. Perspective-correct vertex interpolation of the blue channel at one interior pixel.
3. Exact 4x MSAA sample coverage and 8-bit resolved intensity.
4. Exact top-left rule ownership of two screen-space triangles sharing an edge (16 covered pixels, zero overlap).

Those results, not numbers inferred from ARE, are stored in `evidence/wolfram-cag-geometry.v1.json`.
`software_gpu/research/wolfram_cag_oracle.py` validates the protocol, all-finite small rational literal grammar, bounded fixture size, read-only authority boundary and source hash. It provides a machine-readable evidence receipt.

```bash
python -m software_gpu.research.wolfram_cag_oracle
python -m unittest software_gpu.tests.test_wolfram_cag_oracle -v
python -m unittest discover -s software_gpu/tests -v
```

The **real CPU pipelines** are tested; fixtures never write world, gameplay, network, or persistence state. Linux and Windows testing runs under ordinary GitHub Actions without a Wolfram account or key.

## Critical integrity distinctions

- The checked-in JSON is a frozen offline snapshot from **Wolfram Language Evaluator**, and not evidence of an authenticated `https://services.wolfram.com/api/cag/v1/WolframLanguageCompute` HTTP call.
- A matching CPU test is a **parity observation for those four cases**, not mathematical proof of an arbitrary full renderer and not a GPU performance benchmark.
- A Wolfram response is an oracle for proposed exact numerical invariants, not a command to modify runtime or authoritative Aurion geometry.
- Do **not** copy the Aurion `WOLFRAM_CAG_API_KEY` into this repo or Actions. Aurion owns its existing authenticated Wolfram CAG bridge in `server/wolframCag.ts`; this repo currently owns only offline public fixtures.
- Never accept generated Wolfram code, arbitrary expressions or untrusted Python/Wolfram evaluation through this research fixture path.
- Future optional provider integration must have a bounded server-only secret boundary, explicit timeouts, receipts with canonical request/result SHA-256, fail-closed status distinctions, independent replays, test coverage and owner approval.

## Scope and next research

Expand only after negative tests and CI prove this pilot: right/far-plane clipping, perspective interpolation with heterogeneous `w` and clipped varyings, NaN/overflow cases, adversarial near-zero edge tie tests and cross-backend byte/depth replay. Test more seeds and CPU architectures. ScaNN/vector-search is **not** part of this experiment.

## Provenance

Provider: Wolfram Language Evaluator, exact rational arithmetic. Mathematics generated externally to the ARE renderer. Canonical boundary: `numeric_geometry_only`; `mutationAuthority=none`. Optional cross-project reference: `OuroborosCollective/Echoes_of_Aurion/docs/migrations/AIM249_WOLFRAM_CAG_BRIDGE.md`. That Aurora bridge is not activated or modified by ARE.
