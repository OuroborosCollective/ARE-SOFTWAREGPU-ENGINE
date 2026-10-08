# Proposed Aurion offline CPU render adapter (not deployed)

This is a future isolated tooling interface, **not** a live Aurion or SoftwareGPU runtime connection.

## Inputs (read-only)
- Exact source revision, task ID, model/mesh hash, camera/projection hash and deterministic render configuration.
- Explicit bounded CPU, RAM and wall-clock budget, plus caller-selected output dimensions.
- Optional signed/pinned fixture hashes for matching Aurion world projections; never import authoritative player state directly.

## Outputs (derived evidence only)
- BMP/PNG or numerical CPU-rendered output plus its SHA-256 and input-fixture hashes.
- Renderer version, CPU architecture, exact execution configuration, elapsed time and error class.
- Receipt binding canonical input digest, output digest and source revision; never assert deterministic equivalence without repeat-run equality and tolerance rules.

## Forbidden
- Writing World State, DB migration data, NPC authority, physics authority or 100-ms game tick outcomes.
- Replacing or mutating Aurion's deterministic causal replay oracle.
- Sending player data to a public network service; GPU/CUDA/DirectX compatibility promises without hardware-independent reproducible proof.

## Acceptance
1. Fixed seed/fixtures and repeated CPU output equality or documented numerical tolerance.
2. Linux/Windows independent runner evidence, fixed resource budgets and timeout/abort verification.
3. CPU baseline comparisons on identical inputs and hardware.
4. Security gate before network deployment.
5. A separate Aurion change reviewed against canonical owner contracts; runtime evidence and regression after each integration.
