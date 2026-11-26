# Lokales Lernen für Raster und Video

Die SoftwareGPU kann auf einem Arbeitsrechner messen, welche von zwei Ausführungsvarianten für ähnliche Aufträge weniger Zeit braucht. Das Modell benötigt Python, SQLite und die vorhandene CPU. Es speichert Messwerte und kleine numerische Gewichte pro Auftragsklasse. Die Kalibrierung ist für Offline-Rendering und Asset-Produktion ausgelegt.

## Einschalten und nachsehen

Nach Installation des Engine-Pakets initialisiert `are-learning enable` den Speicher des aktuellen Benutzers. Neue Rasterizer und `are-render-video` finden ihn automatisch. Eine Anwendung kann mit `ARE_LEARNING_DB=/voller/pfad/lernen.sqlite3` einen eigenen Speicher verwenden. `ARE_LEARNING_DB=off` schaltet Messung und Auswahl für einen Prozess aus. Eine frische Installation ohne diese Einstellung und ohne initialisierten Speicher behält den bisherigen Ausführungspfad bei.

```sh
are-learning enable
are-render-video --fps 24 Vorschau.mp4 frames/*.png
are-render-video --fps 12 Vergleich.mkv raster/*.ppm
are-learning status
are-learning dataset --limit 10
```

Der Standardspeicher liegt unter `$XDG_STATE_HOME/are-softwaregpu/learning-v1.sqlite3`, ersatzweise unter `~/.local/state/are-softwaregpu/`. Die Befehle unterstützen `--db PFAD`. Die Videofunktion braucht ein vorhandenes FFmpeg/ffprobe-Paar im Suchpfad. Sie bevorzugt das versionierte Studio-Paar. Die Bilder werden in Argumentreihenfolge verarbeitet. Die Ausgabe wird erst nach der Kontrolle von Bildanzahl, Codec und Bildrate unter dem gewünschten Namen sichtbar. Der Befehl weist bestehende Ausgaben zurück.

## Was ein Lauf beibringt

- **Raster.** Die normalen `SoftwareRasterizer.draw_mesh`-Aufrufe messen die Rasterphase ab der vorbereiteten Geometrie. Beim originalen VertexColor-Shader kann der vorhandene Batch-Pfad gewinnen, bei Blinn-Phong eine größere Kachel. Beide Wege beginnen mit denselben vorhandenen Farb- und Tiefenpuffern. Eigene Shader, andere Backends, leere Draws und aktivierte Vorbereitungscaches liefern ausschließlich Referenzmessungen. Shader-Callbacks dieser Pfade laufen einmal.
- **Video.** Der ARE-Export vergleicht die automatische Eingabedekodierung mit einem einzelnen Decoder-Thread. Codec, Encoder-Threads, Qualitätsparameter, Bildrate und Filter bleiben durch das gewählte Ausgabeprofil vorgegeben. Die gemessene Zeit umfasst Encoding und ffprobe-Kontrolle. Ein direkt gestartetes fremdes FFmpeg und der interne Blender-Cycles-Renderer führen eigenen Code aus. Der ARE-Export verarbeitet auch deren fertige Bilder.
- **Auswahl.** Die Auftragsklasse enthält vorab verfügbare Merkmale. Beim Raster gehören dazu Auflösungsklasse, vorbereitete Dreiecke, geschätzte projizierte Fläche, Shader, Kachelgröße und Workerzahl. Beim Encoder zählen Quellformat, Eingabemenge, Bildanzahl, Bildrate und Zielcodec. Die Profile sind an Rechner, CPU-Zahl und die beteiligten Implementierungen gebunden. Bildinhalte, Dateinamen und Prompts gehören nicht zum Datensatz.
- **Gewichte.** Pro Klasse lernt das Modell die Kosten beider Wege in Nanosekunden und den logarithmischen Zeitgewinn aus echten Paaren. Ein neuer Wert trägt 25 Prozent zum gleitenden Mittel bei. Zuerst werden vier Paare in wechselnder Reihenfolge auf identischer Eingabe ausgeführt. Drei der vier letzten Paare müssen die Alternative vorne sehen, der gewichtete gepaarte Vorteil muss über zehn Prozent liegen und ihre geschätzte Laufzeit muss niedriger sein. Einzellaufzeiten aktualisieren die Kostenschätzung. Nach jeweils 32 erfolgreichen Aufträgen derselben Klasse wird erneut verglichen.
- **Korrektheit.** Für Vergleichsläufe müssen die SHA-256-Werte von vollständiger RGBA-Farbe plus Float32-Tiefe oder der dekodierten Videobilder mit Zeitstempeln übereinstimmen. Eine Abweichung oder ein Fehler der Alternative sperrt sie für das gespeicherte Profil. Der Referenzweg liefert das Ergebnis. Fehlgeschlagene Referenzläufe erzeugen kein Trainingsbeispiel. Nach der Kalibrierung laufen Einzelaufträge mit der gewählten Variante. Einzelfälle tragen keinen neu gemessenen Paarvergleich.
- **Speicher.** Die Datenbank schreibt Beispiel und Gewichte in einer Transaktion. Verschiedene Prozesse können ihren Lauf beenden, während andere rendern. Die letzten 4096 Beispiele bleiben erhalten. Die Gewichte aktiver Klassen enthalten deren bisherige geglättete Historie. Eine Klasse ohne verbleibendes Beispiel wird entfernt. Das Feld `last_learning_receipt` am Rasterizer und das JSON-Feld `learning` beim Video zeigen den gewählten Weg und Speicherfehler an.

Die ersten Vergleichsläufe kosten zusätzliche Zeit und Speicher. Läuft die Referenz auf einem Rechner besser, kann sie die bevorzugte Variante bleiben. Das Verfahren verändert weder Motiv noch Spielregeln. Zeiten oder Trainingsgewichte gehören nicht in Simulations-Hashes.

## Laufzeitvergleich auf dem eigenen Rechner

```sh
python -m software_gpu.benchmarks.compare_local_learning --output holdout.json
```

Der Test trainiert mit einem Rechteck. Zwei überlappende Dreiecke mit anderen Tiefen und Farben bleiben für die Prüfung zurück. Für jeden Messdurchgang werden die Gewichte desselben Trainingsstands wiederhergestellt. Die Reihenfolge mit/ohne Lernen wechselt. Der Bericht enthält Rohzeiten einschließlich Lernverwaltung im Draw, die tatsächlich verwendete Variante und beide vollständigen Puffer-Hashes. Er liefert eine Aussage über diesen Shader, diese Geometrie und diesen Rechner.

## Weitere gewichtete Autorenpfade (opt-in, 21. November 2026)

Die bestehenden Raster- und Video-Pfade behalten ihre vorhandene Lernlogik. Bei aktiviertem lokalen SQLite-Lerner koennen jetzt auch BMP- und PPM-Byte-Exporte zwei vollstaendig verglichene Encodings messen; `last_export_learning_receipt` belegt die Wahl. Der Blender-CPU-Bridge und der Aurion-Offline-Worker reichen Raster- und Export-Receipts weiter, ohne Gameplay-Authority oder die Bilddaten zu veraendern.

`run_model(..., workers='auto')` vergleicht native C++17-Ausgaben mit einem und zwei Workern, inklusive aller RGBA8-Frames, resolved Beauty und Float32-Depth. **Explizite Workerzahlen bleiben fest**. Das Visual Asset Lab behaelt seine obligatorische 1/2-Worker-Abnahme und nutzt den gesondert gepaarten Auto-Pfad nur bei aktiviertem Lernen. `convert_ktx2_glb` vergleicht bei vorhandenem signaturgeprueften Khronos-CLI dessen PNG-Extraktion mit offizieller RGBA8-Extraktion und unabhaengiger PNG-Kodierung; massgeblich ist identische dekomprimierte Pixelinformation, nicht die verlustbehaftete Ursprungs-PNG. Bei Paritaetsverlust oder Kandidatenfehler wird die Alternative pro Profil dauerhaft blockiert.

**Grenzen:** Auto-Auswahl wird nie fuer fest vorgegebene Benchmark-Worker erzwungen; Writer lernen nur ihre Byte-Kodierung (nicht Shader/Pixel). Keine Gewichte in World-Seeds, Spielregeln, Replay- oder Source-SHA-Identitaet; keine Geschwindigkeitsgewinne ohne reale gepaarte Messwerte. KTX2-Authoring bleibt offline und SHA-/Lizenz-geprueft.

Ein explizit angelegter `CagToneShader` kann im bestehenden Raster-Lerner
gegen die skalare Ganzzahlreferenz antreten. Anleitung, Batch-Gegenprobe und
Kaltstartkosten stehen im [CAG-Shader-Piloten](CAG_SHADER_PILOT.md).
