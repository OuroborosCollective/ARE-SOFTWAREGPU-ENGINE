# Offline Wolfram-inspired research modules

- `scripts/miha_evidence_similarity.py` is a CPU-only, stdlib-only, **candidate** analysis of user-supplied immutable source IDs. Repeated identifiers count; empty evidence is excluded. It does not read or write Hugging Face, make payments or provenance assertions, run model training, access MariaDB, or import Aurion.
- `scripts/wolfram_multiview.py` is a separate optional *local* Wolfram reference. It creates scripts but does not invoke a kernel or claim PNG/graphics until explicitly run. Wolfram Cloud warned of non-cloud-compatible interactions; use static `"ThreeView"` for offline investigation.
- All external source SHA/revision fields are caller-declared until independently compared to actual immutable source bytes and GitHub/Hugging Face revision.
- No new default runtime dependencies or changes to the existing CPU renderer/Android release system.

Tests: `python -m unittest software_gpu.tests.test_miha_evidence_similarity -v`.

Official reference: https://resources.wolframcloud.com/FunctionRepository/resources/MultisetDiceDissimilarity/
