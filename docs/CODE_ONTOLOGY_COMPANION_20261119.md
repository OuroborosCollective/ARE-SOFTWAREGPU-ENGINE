# Code Ontology Companion – optionale statische ARE-Architekturprüfung (2026-11-19)

## Funktionsumfang

Diese Integration benutzt die **offizielle Version 0.6.0** von [battle-doll/code-ontology-companion](https://github.com/battle-doll/code-ontology-companion/releases/tag/v0.6.0) als **separaten, nur lesenden Quellcodeanalysator**. Sie ist kein neuer Renderer, keine zusätzliche Autorität im Gameplay und kein Runtime-/Performance-Orakel. Der native **C++17-Kern ist nicht unterstützt**; der Python-Pfad wird als partiell analysierbar gekennzeichnet.

### GitHub Actions – tatsächlicher Funktions-Smoketest

Die optionale Workflowdatei [code-ontology-companion.yml](../.github/workflows/code-ontology-companion.yml) läuft bei passenden PR-Änderungen und manuell über `workflow_dispatch`. Sie hat nur `contents: read` und erhält keine Secrets.

1. Checkout der zur CI gehörenden Revision und Python 3.12; erst die lokalen Vertrags-Unit-Tests ausführen.
2. Die vollständige offizielle Release-ZIP 0.6.0 beziehen und den **SHA-256** gegen die veröffentlichte Release-Asset-Digestangabe `7c0e8f8daa9f4f5ddecce654a425c76c1d3dc664ba18651dc2050bcbb1d8f217` prüfen. ZIP-Zahl, Größen und Entry-Pfade vor Extraktion begrenzen; Symlinks und Pfadtraversal ablehnen.
3. Verifizierte `companion.py` und drei erforderliche Nachbarskripte ausschließlich im separaten Entpackverzeichnis verwenden. Keine ähnlich benannten Skripte aus dem Zielrepository ausführen.
4. `doctor`, `preflight`, `init --authorized` in **temporärem Runner-Workspace außerhalb des Repositories**, `status` mit aktuellem Source-Manifest, gefilterte Symbolsuche nach `SoftwareRasterizer`, `impact --depth 2`, `history`, unverändertes `sync` als Idempotenzprobe.
5. Für `diff` einen zweiten temporären, **ausdrücklich synthetischen und isolierten** Python-Quellbaum anlegen, einmal verändern und den echten Upstream-`sync`/`diff`-Ablauf prüfen. Der Zielrepository-Code wird nie für den Diff verändert.
6. Ausschließlich gekürzte, nicht sensitive Konsolenresultate ausgeben. Ontology-Graph, RDF, `graph.html`, private Source-Manifeste, Quell-Bodies und absolute Checkoutpfade bleiben **ephemer im Runner** und werden **nicht hochgeladen**.

Das ist ein echter Parser-/Werkzeug-Funktionstest am Projektquellbaum, aber **kein Laufzeit-Tracing**. Statische Importkanten beweisen weder tatsächliche Funktionsaufrufe noch Worker- oder CPU-Auslastung.

### Reproduzieren

```bash
python -m unittest software_gpu.tests.test_code_ontology_ci -v
# In GitHub: Actions -> Code Ontology Companion -> Run workflow
```

Mit einem zuvor verifizierten vollständigen Release-Bundle und autorisiertem lokalen Repository lässt sich der Runner ohne Netzwerkdatenübertragung des Repository-Inhalts verwenden:

```bash
python scripts/code_ontology_ci.py \
  --bundle /path/to/verified-extracted-release \
  --repo /path/to/ARE-SOFTWAREGPU-ENGINE \
  --output-dir /safe/path/outside-repository
```

Die optionalen **lokalen MCP-Tools** (Workspace-Suche/Neighbors/Snapshot-History usw.) erfordern die vollständige passende Release-Installation und separate Konfiguration. Sie werden hier absichtlich weder als vermeintlicher ChatGPT-MCP-Endpunkt hinzugefügt noch mit bereits installierten Plugins verdoppelt. Die CLI deckt die statische Suche und Impact-Analyse bereits ab. Kein Ollama, LLM-Download, Graphdatenbankdienst oder persistenter Daemon wird gestartet.

### Grenzen und Qualitäts-Gates

- **Core:** keine Änderung an `SoftwareRasterizer`, Geometry-Edge-, SurfacePlanner-, Float32-/Depth-/RGB- oder native-C++-Verträgen.
- **Produktion:** kein Deployment und kein Eingriff in das produktive Rendering/Android.
- **Test:** echter offizieller Analyzer arbeitet über den vollständigen ARE-Python-Checkout; isolierter Testfixture-Diff ist *kein Produktions- oder Runtime-Beweis*.
- **Persistenz:** temporäres, automatisiert wieder entfernte Workspace mit Git-Revision, lokalen SHA-256-Manifests und privatem Snapshot; kein Spiele-Save.
- **Effekte:** offline Graph/HTML/RDF-Berechnung, nicht veröffentlicht oder als aktive Grafikprojektion ausgegeben.
- **Runtime-Projektion:** keine entsprechende Runtime-Verbindung etabliert.
- **Rangliste:** [neuer Testkatalog](../evidence/test-series-catalog-v1.json) enthält die Testreihe **neueste zuerst**, aber ohne fiktive FPS. Der [CPU-Ranglistenbericht](CPU_WAVE_RANGLISTEN.md) zeigt denselben Eintrag.
- **Merge:** vollständige GitHub-CI, Readback des exakten finalen SHA, genau ein kurzer append-only `Memory.md`-Eintrag und erneute End-Head-Tests.

Der vollständige Python-Architektur-Snapshot ist nur dann frisch, wenn `status.freshness == current`. Tests gegen synthetische Fixtures sind als Vertrags-/Verhaltenstests getrennt von tatsächlicher Quellenanalyse. C++17 benötigt separat einen Clang-basierten Ontologie-Adapter; die Version 0.6.0 behauptet diesen nicht.

## Privacy / Sicherheit

Das GitHub-Release wird im CI-Runner geladen. Die Veröffentlichung von Source-Namen, Pfaden oder strukturellen Beziehungen als externes Artefakt ist **nicht** Bestandteil dieser Integration. Die GitHub-Actions-Logs dokumentieren nur statische Prüfungsstatus und Summen. Jede spätere Freigabe eines Graphen, Veröffentlichung oder private Repository-Analyse muss die jeweilige Zugriffsgrenze eigenständig beachten.
