# SoftwareGPU CPU-Benchmark auf gemeinsamem Sovereign-/Aurion-VPS

**Status 2026-10-13:** Das Repository enthält einen isolierten, nicht-rootfähigen
Benchmark-Starter, aber **keinen bestätigten VPS-Deploy und keinen Host-Benchmark**.
Die live aus Sovott gelesene Kapazität beträgt 8 logische CPUs, circa 31,34 GiB RAM
und 400-GB-Datenträger, aktuell ~88,8 % belegt, circa 46,6 GB verfügbar.
Das Broker-Health-Gate meldet `P0 FILESYSTEM_CAPACITY_PRESSURE`.
Die Owner-SSH-Sitzung meldet `SSH_NOT_CONNECTED`.
**Nicht auf dem Produktivhost starten, bevor diese Blocker behoben und verifiziert sind.**

## Ablauf

1. Nur **lesend** VPS-Host, GitHub-SHA, Docker-/Sovereign-/Aurion-Health,
   Plattenplatz, Last und Nutzerrechte prüfen. Kein SSH-Passwort oder PAT
   in GitHub, Logs, Kommandozeile oder diesem Dokument speichern.
2. Nach Entlastung des Datenträgers den *exakten* geprüften main-SHA in
   einem isolierten Verzeichnis unter einem **unprivilegierten** Benutzer
   auschecken. Keine Container, DB, Reverse-Proxys oder Systemdienste ändern.
3. Zuerst `inspect`, dann `plan` ohne Dateimutationen; sie sollen die
   tatsächlichen CPU-Affinitäts-, Load-, Disk- und Memory-Gates ausweisen.
4. **Pilot:** höchstens zwei zugewiesene CPUs, zwei Worker, `nice +15`,
   RLIMIT_AS 4 GiB, RLIMIT_FSIZE 1 GiB, Prozess-CPU-Budget 900 Sekunden,
   Wallclock-Abbruch 420 Sekunden, sperrende Einzel-Lauf-Sperre. Die
   Gesamtbenchmark-Laufzeit ist auf 300 Sekunden begrenzt.
5. Abbruch, wenn belegter Speicher >85 % (auch bei noch freien GB),
   verfügbarer RAM unter 4 GiB oder 1-Minuten-Last je CPU >0,60 ist.
   Kein Übersteuern, um einen Performancewert zu erzwingen.
6. Erst nach einem nachgewiesenen ruhigen Wartungsfenster, mindestens
   acht **tatsächlich zugeordneten** CPU-Threads, Last je CPU <=0,15
   und ausreichender Kapazität ist der separat bestätigte `full`-Lauf
   mit 1/2/4/8 Workern zugelassen. Keine allgemeine Freigabe für
   acht Worker nur aus dem Host-CPU-Modell ableiten.
7. Audit `benchmark.json`, alle Build-/Quell-SHA, alle 15 Messpaare,
   Farb-/Tiefenparität, `vps-host-readback.json` und
   `native-output.log` nach Ausführung. Ohne `PASS` und Hashreadback
   keinen Runtime-Erfolg ausgeben.

## Referenzkommandos (nur *nach* erfolgreicher SSH-Verbindung)

Die folgenden Beispiele setzen einen sicheren Checkout unter
`/home/benchmark/are-softwaregpu` und den tatsächlich aus GitHub gelesenen
40-stelligen Git-Head voraus. Platzhalter nicht unverändert übernehmen.

```bash
cd /home/benchmark/are-softwaregpu
python3 tools/vps_bio_host.py inspect --expected-sha <40-STELLIGE_SHA>
python3 tools/vps_bio_host.py plan --expected-sha <40-STELLIGE_SHA>
python3 tools/vps_bio_host.py run --expected-sha <40-STELLIGE_SHA>
```

Wegen der **aktuellen** P0-Datenträgerbelegung muss bereits `inspect` STOP
liefern; es ist **kein** Benchmark-Auftrag an einen produktiven Host ausgeführt.
Die 1/2-Worker-Pilotmessung erzeugt CPU-auf-CPU-Evidence, keinen Live-FPS-
oder GPU-Paritätsbeweis. Hardware-Cache-Kausalität (`perf c2c`) erfordert
zusätzlich vom Host bereitgestellte PMU-Rechte; das kann auf einem VPS fehlen.

[Native Experimente](BIO_FRONTIER_CACHE_ABLATION.md) ·
[Erster 32-Fälle-Pilot](BIO_FRONTIER_CACHE_PILOT_20261013.md) ·
[Abnahmeverträge](../software_gpu/docs/ARCHITECTURE.md).
