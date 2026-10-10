# Kalibrierung und CPU-Finetuning

## Renderer abstimmen

Erst `scripts/workbench.py analyze` auf echten Ablationen ausführen. Batch-Gewinn und Scan-Gewinn getrennt als gepaarte Verhältnisse mit Streuung beurteilen. Kleine Rauscheffekte und negative Fälle behalten. Für ein Kostenmodell nur vor der Auswahl verfügbare Merkmale verwenden: vorbereitete Dreiecke, Bounding-Box-Samples, Bins, kleine Paare und deklarierter Shader-Typ. `shaded_samples`, Depth-Ergebnisse und Shader-Aufrufe entstehen erst während der Ausführung und sind ohne bezahlten Probe-Pass keine Vorabmerkmale.

Dreiecksanzahl und -größe unabhängig sweepen; 128/256/512 px und budgetiert 1024 px prüfen. Mindestens eine SHA-gepinnte reale GLB-Geometrie durch den bestehenden Offline-Worker messen. Dessen Flat-Color-Ergebnis belegt keine Textur-/PBR- oder vollständige Game-Äquivalenz. Ganze Szenenfamilien zum Test zurückhalten; Leave-one-row-out ersetzt diesen Test nicht. Koeffizienten, Einheiten, Feature-Schema, Trainings-/Holdout-Hashes und Policy-Version speichern. Ein kleines synthetisches Dataset rechtfertigt keinen universellen Runtime-Gate.

## CPU-LoRA abstimmen

Die SoftwareGPU ist ein CPU-Renderer; sie ersetzt weder PyTorch-Autograd noch eine Trainings-GPU. Vor ML-Läufen `scripts/miha_cpu_runner.py`, `fixtures/miha/training.json` und `.github/workflows/miha-cpu-training.yml` lesen. Den realen RAM-/Langsequenz-/Modellrevision-Gates folgen. `scripts/workbench.py train-preflight` ruft den vorhandenen CPU-Preflight auf, trainiert aber nicht und lädt keine Modellgewichte.

Erst bei bestandenem Preflight den vorhandenen `audit`, dann den vom aktuellen Auftrag gedeckten `train`-Pfad verwenden. CPU explizit wählen; CUDA/HIP/ROCm-Geräte nicht aktivieren. Modell-, Tokenizer- und Dataset-Revisionen pinnen; längste Beispiele, Seeds, Loss, Laufzeit, Peak-RAM und Eval-Ergebnisse erfassen. Die `software_gpu.training.metrics`-Callback-Bilder gegen ihre Hash-Receipts prüfen. Einen blockierten RAM-Gate als BLOCKED melden. Kein verkürztes Training als vollständigen Nachweis verkaufen. Gewichte/Adapter nur veröffentlichen, wenn der aktuelle Auftrag es deckt; Canonical/Atomic/Hugging-Face-Readbacks erhalten.
