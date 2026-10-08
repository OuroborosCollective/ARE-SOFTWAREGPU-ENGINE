# Mitwirken / Contributing

Vielen Dank für Interesse an der ARE SoftwareGPU Engine. Der Fokus liegt auf echten CPU-Runtime-Nachweisen statt unbelegten GPU-Claims.

## Fehler melden und dokumentieren

Fehlerberichte und kleine Dokumentationsvorschläge sind willkommen. Bitte Betriebssystem, Python-Version, CPU-Modell, exakten Befehl, reproduzierbare Testdaten und beobachtetes Ergebnis mitgeben. Keine Passwörter, API-Keys oder privaten Spielerdaten in Issues.

## Codeänderungen und kommerzielle Rechte

Die Projektsoftware ist **nichtkommerziell unter PolyForm Noncommercial 1.0.0** verfügbar; der [Pflichtvermerk](NOTICE) ist bei Weitergabe zu bewahren.

**Wichtig:** Wer einen Code-PR einreicht, überträgt dadurch nicht automatisch Urheberrechte oder das Recht zur kommerziellen Weiterlizenzierung an OuroborosCollective. Weil für das Projekt separate kommerzielle Lizenzen vorgesehen sind, werden externe Codebeiträge **erst nach expliziter Klärung von Herkunft, Rechten und einer passenden Contributor-Vereinbarung** zur Übernahme geprüft. Bitte vor umfangreichen Beiträgen die Maintainer kontaktieren.

Technisch muss jeder PR seinen Zweck, geänderte Produktions-/Test-/Core-/Effekt-/Runtime-Flächen, Risiken, Rollback und Beweise aufführen. Nach einer Codeintegration sind echte Unit-/Regressionstests und CI-Readback erforderlich. Eine nachprüfbare `Memory.md`-Notiz dokumentiert Änderung, Erkenntnis und Evidence. Keine Mocks als Ersatz für reale Laufzeitnachweise.

## Sicherheit

Aktuelle HTTP/TCP-Dienste sind nicht für öffentliche Exposition freigegeben. Sicherheitsfunde bitte zunächst diskret an die Repository-Maintainer richten statt reproduzierbare Exploit-Details öffentlich zu posten.
