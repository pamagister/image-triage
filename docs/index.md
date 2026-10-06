[![Github CI Status](https://github.com/pamagister/image-triage/actions/workflows/main.yml/badge.svg)](https://github.com/pamagister/image-triage/actions)
[![GitHub release](https://img.shields.io/github/v/release/pamagister/image-triage)](https://github.com/pamagister/image-triage/releases)
[![Read the Docs](https://readthedocs.org/projects/image-triage/badge/?version=stable)](https://image-triage.readthedocs.io/en/stable/)
[![License](https://img.shields.io/github/license/pamagister/image-triage)](https://github.com/pamagister/image-triage/blob/main/LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/pamagister/image-triage)](https://github.com/pamagister/image-triage/issues)
[![PyPI](https://img.shields.io/pypi/v/image-triage)](https://pypi.org/project/image-triage/)


# Image Triage

Analysiert Fotos, gruppiert ähnliche Aufnahmen (Serien, Duplikate), wählt pro Gruppe die beste
Variante, erkennt Objekte (YOLO), schreibt Sterne (1–5) und Objekt-Schlagworte als XMP und
exportiert entweder alle guten Bilder oder die **N relevantesten** – breit gestreut über alle
Unterordner und Motive. Originale werden nie gelöscht.

## Installation

Läuft unter Windows und Linux (Python ≥ 3.12, [uv](https://docs.astral.sh/uv/)).

```bash
uv sync
uv run image-triage-download-model       # YOLO-Modell nach res/yolo/ (oder Button in der GUI)

# Optional: ExifTool zum Schreiben von Rating/Schlagworten direkt in Bilddateien
winget install OliverBetz.ExifTool       # Windows
sudo apt install libimage-exiftool-perl  # Debian/Ubuntu
```

Das Modell (`res/yolo/yolo26n.onnx`, ~10 MB, Ultralytics YOLO26, AGPL-3.0) ist nicht im Repo.
Der Pfad ist relativ zum Arbeitsverzeichnis. Wer die GUI nicht im Projektordner startet, setzt
`models.object_detector` in den Settings auf einen absoluten Pfad. Ohne Modell: `--models-enabled false`.

## Verwendung

### Schnellstart: die besten 10 Bilder aus `images`

Im Projektordner in einer normalen Eingabeaufforderung (cmd), PowerShell oder Linux-Shell:

```bat
uv run image-triage --input images --output selected --top-n 10
```

Die 10 Bilder landen in `selected\` (Ordnerstruktur bleibt erhalten). Die Originale werden dabei
nicht verändert: Wiederverwendbare Analysewerte einschließlich erkannter Objekte werden
standardmäßig in einer versteckten `.image-triage.yaml` pro Foto-Unterordner gespeichert. Sterne
und Auswahl werden bei jedem Lauf anhand der aktuellen Fotos und Settings neu berechnet. Wer nur
sehen will, was gewählt würde, hängt `--dry-run` an (Ausgewählte sind im Log mit `x` markiert).

Rating und Schlagworte können optional direkt in die Fotos geschrieben werden. Dafür ExifTool
installieren und `--write-xmp-rating true` und/oder `--write-keywords true` angeben. Der YAML-Cache
wird auch dann angelegt und aktualisiert.

### Weitere Beispiele

```bash
# Die 100 relevantesten Fotos aus allen Unterordnern
uv run image-triage --input Photos_of_2025 --output Best_of_2025 --top-n 100

# Alle Fotos ab 4 Sternen, nur anzeigen
uv run image-triage --input images --min-rating 4 --dry-run

uv run image-triage --config config.yaml --input images

# GUI
uv run image-triage-gui
```

Alle Parameter stehen in [`config.yaml`](config.yaml) (mit Kommentaren). Die wichtigsten sind
auch als CLI-Option verfügbar (`uv run image-triage --help`), in der GUI unter *Settings*.
CLI, GUI und Config-Datei werden über [config-cli-gui](https://github.com/pamagister/config-cli-gui)
aus derselben Parameterdefinition (`src/image_triage/config.py`) erzeugt.

## Ablauf

1. **Scan** – Bilder (`jpg`, `png`, `tif`, `webp`) rekursiv einlesen; der Output-Ordner wird ignoriert.
   Aufnahmezeit: EXIF, sonst aus dem Dateinamen (`IMG_20150502_071410`, `2015-03-10 09.00.10`),
   sonst Änderungsdatum.
2. **Analyse** (auf 1024-px-Vorschau)
   - Schärfe: Laplace-Varianz, 90. Perzentil über ein 4×4-Raster (scharfes Motiv vor unscharfem
     Hintergrund zählt als scharf)
   - Belichtung: Anteil ausgefressener Lichter/abgesoffener Schatten, extreme Helligkeit
   - Objekte (YOLO26, 80 COCO-Klassen) ab `models.confidence`, dazu ein Inhalts-Embedding
     (gemittelte Backbone-Features aus demselben Modelllauf)
3. **Gruppierung** – identische Dateien (BLAKE3) sowie Aufnahmen mit ≤ `max_time_gap_s`
   Sekunden Abstand, deren pHash-Abstand ≤ `max_hash_distance` **oder** deren Embedding-Ähnlichkeit
   ≥ `min_embedding_similarity` ist (erkennt Serien auch, wenn sich jemand bewegt).
4. **Score** (0–1) – gewichtetes Mittel aus
   `min(1, Schärfe / sharpness_reference)`, Belichtung und Motiv. Das Motiv ist die beste Detektion
   aus `subject_classes` (Personen, Tiere): Konfidenz × Größe, ab 5 % der Bildfläche voll.
   Objekte sind bewusst nur ein Bonus (`object_weight`), damit Landschaften ohne Personen nicht
   verlieren.
5. **Rating**
   | Sterne | Bedingung |
   |---|---|
   | ★★★★★ / ★★★★ / ★★★ | beste(s) `max_per_group` Bild(er) der Gruppe, je nach Score (`min_score_5`, `min_score_4`) |
   | ★★ | scharf, aber schlechter als das beste Bild der Gruppe |
   | ★ | unscharf (Schärfe < `blur_threshold`) |
6. **Auswahl**
   - `top_n` > 0: Kandidaten sind die besten Bilder jeder Gruppe (jedes Motiv nur einmal).
     Jeder Ordner mit Bildern gilt als Ereignis (Urlaub, Feier, …) und bekommt Plätze im Verhältnis
     zu seiner Zahl an Motiven, mindestens einen. Innerhalb eines Ereignisses wird gierig gewählt:
     hoher Score, aber mit Abzug (`diversity`) für Bilder, deren Inhalt einem schon gewählten ähnelt.
   - `top_n` = 0: alle Bilder ab `min_rating`.
7. **Metadaten-Cache** – Analysewerte werden je Foto-Unterordner in `.image-triage.yaml` abgelegt.
   Dateiname und BLAKE3-Hash identifizieren jedes Foto. Bei gleichem Hash werden die gespeicherten
   Analysewerte wiederverwendet; bei geänderter Datei wird neu analysiert. Gruppierung, Bewertung
   und Auswahl werden mit den aktuellen Fotos und Settings jedes Mal neu berechnet.
8. **Optionales XMP** – nur wenn `metadata.write_xmp_rating` und/oder `metadata.write_keywords`
   aktiviert sind, schreibt ExifTool `XMP:Rating` und erkannte Objekte als `XMP-dc:Subject`
   (vorhandene Schlagworte bleiben erhalten, Duplikate werden vermieden). Bei RAW-Dateien kann
   zusätzlich ein `.xmp`-Sidecar geschrieben werden.
9. **Export** – Auswahl kopieren, hart- oder symbolisch verlinken (Ordnerstruktur bleibt erhalten,
   vorhandene Dateien werden nicht überschrieben).

`--dry-run` führt nur Analyse und Bewertung aus und loggt das Ergebnis (`x` = ausgewählt).

## Tests

```bash
uv run pytest
```
