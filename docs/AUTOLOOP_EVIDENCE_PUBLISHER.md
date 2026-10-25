# Autoloop: beweisgebundene CPU-Rangliste

Die Website liest ausschließlich `evidence/autoloop-accepted-leaderboard-v1.json` von GitHub `main` (nur lesend). Der Startstand hat absichtlich **keine Einträge**: Es gibt bislang keinen durch Autoloop bestätigten CPU-Rekord.

Der neue Publisher akzeptiert ausschließlich unveränderliche `are.autoloop-cpu-acceptance.v1`-Receipts in `evidence/autoloop/accepted/`, die ein separater **echter Renderer-Benchmark** erst noch erzeugen muss. Pro Kandidat sind fünf Szenen, 64/128 Pixel, 1/2 CPU-Worker und zwei vollständige Durchgänge mit je 15 alternierenden Baseline-/Kandidaten-Paaren erforderlich (20 Profile, 600 Paare). Farb- und Float32-Tiefenpuffer müssen jeweils identische SHA-256-Digests haben. Es werden keine historischen Zeiten mit anderen Runnern vermischt.

Publikation prüft den kanonischen Receipt-Digest, alle zehn tatsächlichen Quellhashes, genau 20 eindeutige Profile, alternierende Reihenfolge, mindestens 2 % geometrischen Gewinn je vollständigem Durchgang, keine Verschlechterung eines Profils über 2 %, die exakte Quellrevision und den tatsächlich erfolgreichen GitHub-Actions-Lauf für diesen Commit. Ungültige oder fehlende Belege blockieren den PR. Ein Test mit künstlichen Werten ist **kein Renderer-Leistungsbeleg**.

```bash
python -m unittest software_gpu.tests.test_autoloop_publication -v
python -m software_gpu.benchmarks.autoloop_publication --check
```

Zur Veröffentlichung nach einer **realen, genehmigten** Optimierung den Receipt und die deterministisch erzeugte öffentliche JSON-Datei im selben PR einreichen. `--write` regeneriert die Datei auf dem gebundenen Checkout, CI prüft lediglich mit `--check`, ohne nach `main` zu schreiben. Erst der geprüfte Merge aktualisiert die öffentliche Website beim nächsten Abruf.

`plateau_state` implementiert die angeforderte Stoppregel: drei vollständige Kandidatenkatalog-Durchgänge ohne bestätigten Gewinn; fehlende Tests und Fehler zählen nicht als Fortschritt, eine erfolgreiche Optimierung setzt den Zähler zurück. Der eigentliche autonome GitHub-Next-Autoloop-Scheduler und der echte A/B-Renderer-Experiment-Harness sind **noch nicht installiert**. Der bestehende VPS-Workflow wird nicht ausgelöst oder verändert. Kein Auto-Merge, kein GPU- oder FPS-Versprechen.
