# ARE CPU-Testlabor auf gemeinsamem VPS

**Zieladresse:** `https://gpu.arelorian.de` (vorgesehen, **noch nicht als erreichbar verifiziert**). Die Hauptdomain `arelorian.de` bleibt frei. Diese Dokumentation installiert weder DNS noch Traefik automatisch und gibt keine bereits laufende öffentliche Instanz vor.

## Laufzeit- und Isolationsvertrag

```text
Android ARE-APK
  -> HTTPS 443 / gpu.arelorian.de
  -> bestehender VPS-Traefik mit echtem Zertifikat
  -> http://127.0.0.1:17860 (NUR Host-Loopback)
  -> are-softwaregpu-worker:7860 (Gradio mit Anmeldung)
  -> isolierter, budgetierter Offline-CPU-Render-Childprozess
```

- **3,0 vCPU CPU-Quota**, kein exklusives Pinning/Kern-Reservieren; 3 GiB Container-RAM, maximal 96 PIDs; `OPENBLAS_NUM_THREADS=3`, `OMP_NUM_THREADS=3`. Die aktuelle Python-Renderfixture nutzt intern auch Single-Thread-Abschnitte, daher beweist die Quota keine tatsächliche 3-Kern-Auslastung.
- `read_only` Rootfs, unprivilegierter UID/GID 10001, alle Linux-Capabilities entfernt, `no-new-privileges`, begrenztes tmpfs und **keine Compose-/Docker-Datenvolumes**. Temporäre Renderdateien sterben mit dem Job/Container.
- Maximal ein aktiver Gradio-Renderjob, Warteschlange maximal drei; pro Vorlagen-Job bestehende Budgetgrenzen von 90 s Deadline / 90 CPU-Sekunden / 2048 MiB Childmemory. Keine Spielserver-Autorität, keine beliebigen Uploads, keine freie Kommandoschnittstelle.
- Authentifizierung bleibt Pflicht. Das Passwort liegt als lokal angelegtes, read-only eingehängtes **Compose-Secret**, nicht im Git-Repository, nicht in Container-Environment-Variablen und nicht in einem Docker-Volume. Die Host-Datei unter `/opt/are-softwaregpu/private/gradio-password` muss für erneute Deployments absichtlich erhalten bleiben.
- Der Dienst hat **keinen direkt im Internet offenen Port**. Der Host-Loopback-Port 17860 darf nicht global freigegeben werden.

## Einmalige, überprüfte Installation

Nur der Administrator mit Zugriff auf den bestehenden Host, die DNS-Zone und den Traefik-Proxy führt diese Schritte aus. **Nicht** direkt auf einem Produktions-VPS aus einem ungeprüften PR bauen. PR-Head, GitHub-Actions-CPU-Test und Docker-Worker-Gate müssen für den identischen SHA erfolgreich sein.

1. `gpu.arelorian.de` als DNS-`A`-Eintrag auf die **tatsächlich bestätigte öffentliche VPS-IP** legen. Den bisherigen Domainbetrieb und vorhandene A/AAAA/MX-Einträge nicht überschreiben. Falls AAAA existiert, dessen Ziel gesondert prüfen.
2. Bestehenden Traefik-/ACME-Resolver, Port-443-Eintritt und Zertifikatsverwaltung inventarisieren. Danach **nur einen zusätzlich isolierten HTTPS-Router** für `Host(gpu.arelorian.de)` mit internem Upstream `http://127.0.0.1:17860` hinzufügen; nicht die bestehenden Aurion-/Sovereign-Router ändern. Den Resolver-Namen aus dem laufenden Proxy ablesen, nicht erraten.
3. Git-Checkout exakt auf den freigegebenen, von GitHub-CI geprüften SHA setzen; `git status --porcelain` muss leer sein. Der lokale Deploy-Schutz lehnt SHA-Abweichungen, unversionierte Dateien und veränderte Dateien ab.
4. Als autorisierter VPS-Administrator, aus dem sauberen Repository-Checkout:

   ```bash
   export ARE_EXPECTED_SOURCE_SHA="<vollständiger-freigegebener-40-Zeichen-SHA>"
   sudo --preserve-env=ARE_EXPECTED_SOURCE_SHA bash ops/softwaregpu-worker/deploy.sh
   ```

   Das Skript erzeugt bei Erstinstallation automatisch ein starkes Gradio-Passwort in einem hostseitigen rootgeschützten Verzeichnis. Den Wert nur direkt über eine vertrauenswürdige, geschützte Administrator-Sitzung aus `/opt/are-softwaregpu/private/gradio-password` entnehmen, **nie** im Issue, Chat, Commit oder CI-Log ablegen.
5. Readback: `docker inspect are-softwaregpu-worker` muss **3 000 000 000 NanoCPUs**, 3 GiB RAM, UID 10001, keine Volumes, `127.0.0.1:17860` und den erwarteten Source-SHA-Label zeigen. Localhost-Login muss erreichbar sein, `/config` ohne Anmeldung muss mit HTTP 401 abweisen. Anschließend TLS-Domainzertifikat für `gpu.arelorian.de` unabhängig validieren und den **echten Standard-Test** aus der Android-App durchführen (128×128, Seed 686, `tiles-plan`, drei bytegleiche Wiederholungen, SHA-256-Receipt). Keine Produktivfreigabe aus einem bloßen grünen Docker-Build.

**Wichtig:** `deploy.sh` kann den DNS-Provider, den bestehenden Proxy, dessen Zertifikatsresolver und Hostinger-Zugang nicht eigenmächtig umkonfigurieren. Das aktuelle Sovereign-Hostwerkzeug erlaubt den ARE-Compose-Stack noch nicht: `Compose-Stack ist nicht freigegeben`. Deshalb ist diese Variante ein CI- und Review-fähiger Deployment-Plan, **kein Beleg einer abgeschlossenen VPS-Installation**.

## Automatische Garbage Collection – eng begrenzter Eigentümer

Bei **jedem erfolgreichen** `deploy.sh`-Update:

1. `docker compose -p are-softwaregpu up -d --build --remove-orphans --wait` ersetzt die alte ARE-Instanz und entfernt eigene verwaiste Compose-Container erst mit erfolgreichem Healthcheck. Darüber hinaus werden nur **gestoppte**, doppelt markierte ARE-Worker-Container entfernt.
2. Alte **dangling** Images werden nur entfernt, wenn sie das eindeutige `org.ouroboros.service=are-softwaregpu-worker`-Label tragen **und** kein einziger Docker-Container sie mehr verwendet.
3. Alte Volumes werden ausschließlich nach exaktem Projektlabel `com.docker.compose.project=are-softwaregpu`, zusätzlichem `org.ouroboros.lifecycle=disposable`-Label **und** verifizierter Nichtverwendung entfernt. Der aktuelle Stack erzeugt selbst **keine Volumes**. Historische nicht eindeutig markierte Volumes bleiben unangetastet und benötigen eine explizite Eigentümerprüfung.
4. **Verboten:** `docker system prune`, `docker volume prune`, `docker image prune`, globale Containerbereinigung und erzwungenes Entfernen genutzter Images. Aurion, PatchMon, MariaDB, Sovereign und deren Daten bleiben unangetastet. Bei fehlgeschlagenem Healthcheck gibt das Skript Fehler zurück und startet keine Müllbereinigung; der vorherige funktionsfähige Stand muss separat auf Versionsebene gesichert werden.

Sichtprüfung ohne Mutation:

```bash
docker ps -a --filter 'label=com.docker.compose.project=are-softwaregpu'
docker volume ls --filter 'label=com.docker.compose.project=are-softwaregpu'
docker image ls --filter 'label=org.ouroboros.service=are-softwaregpu-worker'
docker system df
```

## CI und Regression

Der Workflow `.github/workflows/are-worker-vps-gate.yml` baut auf einer **ephemeren GitHub-Actions-VM** tatsächlich ein Docker-Image, startet einen auf 3 vCPU / 3 GiB begrenzten Worker, prüft Bindung, Mounts und Isolation sowie die echte Standard-128px-Gradio-Callback-Kette samt HTTP-401-Sperre. Er beendet ausschließlich den CI-eigenen Stack. Das ist **kein** Nachweis für die öffentliche VPS-Domain, die echte Android-WebView-Session oder Hostinger-DNS.

```bash
python -m unittest software_gpu.tests.test_vps_gradio_worker_contract -v
python -m unittest software_gpu.tests.test_gradio_arena software_gpu.tests.test_gradio_arena_ui -v
bash -n ops/softwaregpu-worker/deploy.sh
```
