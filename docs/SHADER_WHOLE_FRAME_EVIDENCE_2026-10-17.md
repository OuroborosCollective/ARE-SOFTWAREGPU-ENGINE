# Whole-frame CPU-Shader-Impact: reale draw_mesh-Messung (2026-10-17)

**Scope:** CPU-only, echte Geometry/Framebuffer-Schreibvorgänge mit exakt gleichen Shader-Varyings, identischen RGBA8-Farben und byte-identischen Float32-Depth-Daten. Die beiden Shader-Versionen werden auf **demselben Repository-Head** verglichen; die Referenz ist der explizit rekonstruierte vorherige VertexColor-Fragment- und Batch-Shader. Dies ist keine Hardware-GPU-Messung, keine automatische Policy-Aktivierung und keine allgemeine Aurion-FPS-Prognose.

Source-bound [GitHub Actions 39052922640](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/39052922640) auf **c60ee6155b9ab68ffd6483e580dce2c0a0637555**: Unit-Tests 3/3 PASS; 15 abwechselnde A/B-Paare in jeder der vier Szenen, im Runner verifizierter SHA-256-Receipt **6c9ad14f264157cf5e48568aaed3131390a22b9c1ec5cae7174400627c57dd9d**.

| Szene | Shader-Route | Gepaarten Median: vorherige Zeit / aktuelle Zeit | Kandidat schneller |
| --- | --- | ---: | ---: |
| 8 große überlappende Dreiecke | vollständiger `tiles`-Scalar-Draw | **1,8343×** | 15/15 |
| 160 kleine Dreiecke | vollständiger `tiles`-Scalar-Draw | **1,2132×** | 14/15 |
| 8 große Dreiecke | geplanter `tiles-plan`-Batch-Draw | **0,9975×** | 6/15 |
| 160 kleine Dreiecke | geplanter `tiles-plan`-Batch-Draw | **1,0754×** | 10/15 |

**Interpretation:** Die gemessene Scalar-Optimierung beeinflusst die vollständige Framezeit deutlich. Batch-Shading hat bereits vektorisierte Arbeit und profitiert deutlich weniger vom optimierten Konvertierungsschritt. 0,9975× ist praktisch neutral innerhalb normaler Host-Varianz – keinesfalls als positive Beschleunigung ausgeben. Die Werte sind szenen- und runnergebunden; andere Geometrie, Threadzahl, Auflösung und Shader können abweichen.

**Sicherheitsvertrag:** Baseline/Kandidat desselben Szenen-Durchlaufs müssen identische RGBA8- und Depth-Puffer-Hashes erzeugen. Das Benchmark-Gate prüft alle Wiederholungen, reale Batch-Aufrufe, bytegleiche Frames, Quellcode-Hashes, tatsächlichen Git-Head, Alternierung, rohe Zeiten und selbst signierten JSON-Receipt. Der Test verwendet für die Messung bewusst ein Batch-Minimum von **einem** Fragment, damit Batch-Ausführung bei kleinen Dreiecken belegbar ist; dies **ändert nicht die Produktions-Policy**. Die vorherige 32er-Batchschwelle hätte in dieser Szene den Batch-Pfad gar nicht ausgelöst. Die Clear-Kosten sind nicht in den separat gemessenen `draw_mesh`-Zeiten enthalten.

**Reproduktion:**

```bash
python -m unittest software_gpu.tests.test_shader_frames -v
python -m software_gpu.benchmarks.compare_shader_frames --output /tmp/frame-report.json --pixels 96 --workers 2
```

**Deployment-Grenze:** Der Run belegt den Forschungs-PR-Head, nicht eine `main`-Integration. Deren vollständige CPU-CI muss gesondert nachgewiesen werden. Keine Hardware-GPU-Parität, keine Modelltrainingsläufe und kein automatisch geändertes Auswahlmodell.
