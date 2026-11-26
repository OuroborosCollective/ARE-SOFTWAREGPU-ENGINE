# Authenticated CAG pilot for a local tone shader

The shader applies smoothstep independently to each quantized RGB8 channel.
Wolfram computes all 256 integer outputs once. The existing tile renderer
applies the table on the CPU. Alpha, coverage and Float32 depth follow the
original raster path. This is an opt-in artistic transfer curve.

## Prepare, replay and render

On the authorized credential-owning server, run the following command with
its existing `WOLFRAM_CAG_API_KEY_FILE` mount or `WOLFRAM_CAG_API_KEY`
binding. The standalone Python file needs only the standard library. It sends
one bounded, fixed expression to Wolfram over TLS. Transport or validation
errors fail preparation. Transfer the resulting public numerical receipt.

```sh
python software_gpu/research/cag_profile.py > provider.json
```

From a clean checkout, the checked-in receipts support offline replay with
no credentials. The comparison uses a temporary SQLite database. To obtain an
independent new timing, use a fresh output filename.

```sh
python -m unittest software_gpu.tests.test_cag_tone -v
python -m software_gpu.benchmarks.compare_cag_tone evidence/cag-smoothstep/repeat-provider.json local-render.json --handoff evidence/cag-smoothstep/handoff.json
```

For a normal draw with an existing ARE learning store:

```python
from pathlib import Path
import json
from software_gpu.graphics.cag_tone import CagToneShader
from software_gpu.research.cag_profile import replay

receipt = json.loads(Path("evidence/cag-smoothstep/repeat-provider.json").read_bytes())
shader = CagToneShader(replay(receipt))
renderer.draw_mesh(vertices, indices, shader)
print(renderer.last_learning_receipt)
```

Use the ordinary tiles backend. A disabled learner runs the scalar formula.
The existing LocalLearner compares the scalar and batch lookup paths on the
same initial buffers and admits the candidate with its usual measured gates.
The pilot has its own scope within that store. Other shaders retain their own
selection logic. No source image or geometry goes to the provider.

## Measured run

Render source commit `c5c45d4db3c68ac82a9812a571bedfe6c4ae87e3`.
The two authenticated responses have distinct provider UUIDs and the same
256-byte table SHA-256. Each value also passed a local exact arithmetic check.
The second response fed the measured run. Request/response hashes support
content verification. These local receipts are not provider signatures.

| Held-out scene, 128 × 128, one CPU worker | Median of 12 complete local frames |
| --- | ---: |
| Scalar smoothstep | 40.445 ms |
| Batch arithmetic, same quantization | 4.656 ms |
| Batch lookup, fixed | 4.532 ms |
| Learn-Weight selection, including administration | 5.382 ms |

Four training pairs preceded the held-out overlapping triangles. The learner
served the candidate in all 12 draws. Each path matched all 16,384 RGBA8 pixels
and Float32 depth words. Of these, 9,287 pixels had geometry. RGBA RMSE and
maximum absolute channel error were zero. The large change is scalar-to-batch.
The 0.125 ms median difference between the two fixed batch paths on one host
does not establish a general advantage for Wolfram. Local generation of the
identical lookup table took 28.3 µs.

The first HTTPS call took 3.981 s, the repeat 3.216 s. The repeat took 6.898 s
from workstation dispatch through Sovott to local receipt materialization,
including the provider time. For the four training and twelve evaluation
frames, component totals were 7.137 s for the cold pilot including delivery
and 0.636 s for scalar rendering. These totals exclude benchmark-only
controls. At the observed medians, cold delivery and calibration would be
recovered after approximately 198 held-out frames versus scalar. The local
batch arithmetic control was already faster than the learned path. This run
supports no break-even claim against a locally generated identical table.

The owner-declared developer grant implies zero incremental API fees for both
requests. Provider billing and the host's electricity/VPS allocation were
not observed. The report includes request/response sizes, learner samples,
all frame timings, CPU time for the comparison process including controls,
and full buffer hashes. Time measurements are observations for this workload.

[Provider responses, delivery and render receipts](../evidence/cag-smoothstep/)
· [Wolfram API contract](https://www.wolfram.com/apis/documentation/cag/wolfram-language-computation-api/)
