# SoftwareGPU Workbench

Wiederverwendbares Plugin für ARE-SOFTWAREGPU-ENGINE. Es enthält einen
vollständigen Skill, einen portablen Python-Workflow und Vertrags-/Tuningreferenzen.
Es verwendet die echte Projektumgebung und vorhandene GitHub-/Wolfram-Werkzeuge.

```bash
python plugins/softwaregpu-workbench/skills/softwaregpu-workbench/scripts/workbench.py inspect --root . --output inventory.json
python plugins/softwaregpu-workbench/skills/softwaregpu-workbench/scripts/workbench.py verify --root . --output regression-results
python plugins/softwaregpu-workbench/skills/softwaregpu-workbench/scripts/workbench.py benchmark --root . --output bench-results --pixels 256 --repeats 15 --ablation --seconds 1800
python plugins/softwaregpu-workbench/skills/softwaregpu-workbench/scripts/workbench.py audit bench-results/surface-plan-benchmark.json --root . --output audit.json
python plugins/softwaregpu-workbench/skills/softwaregpu-workbench/scripts/workbench.py analyze bench-results/surface-plan-benchmark.json --root . --output effects.json
python plugins/softwaregpu-workbench/skills/softwaregpu-workbench/scripts/workbench.py train-preflight --root . --output cpu-preflight
```

`audit --root` verlangt passende Hashes aller zehn Benchmark-Quellen.
Ohne `--root` ist der Audit nur eine interne Artifact-Konsistenzprüfung.
`analyze` berechnet gepaarte Batch-/Scan-Effekte aus den vier echten Ablationen;
es kalibriert oder aktiviert kein automatisches Runtime-Gate.

`verify` führt die komplette bestehende Suite aus. Hostbedingte Fehler werden
mit ihrem tatsächlichen Exit-Code dokumentiert; kanonische Head-CI bleibt
vor Integration erforderlich. `train-preflight` führt den bestehenden CPU-Runner
aus, startet aber kein Training. Ein nicht erfülltes RAM-/Policy-Gate ist ein
Fehlerbefund, kein Trainingsnachweis.

Das Skript committet, merged und veröffentlicht nicht automatisch. Ein Skill
kann diese Arbeiten über vorhandene Werkzeuge im vom Nutzer autorisierten
Auftrag erledigen. Quellcode-Inventar ist statisch; CPU-Zeitvergleiche beweisen
keine Hardware-GPU-Parität.

Die Root- und `.codex-plugin`-Manifeste beschreiben dasselbe Plugin für die
jeweiligen Loader. Die Paketierung schließt Python-Caches und Ergebnisse aus.
Copyright und Nutzungsbedingungen: [NOTICE](NOTICE), [LICENSE.md](LICENSE.md).
