<!-- This README.md is auto-generated from docs/index.md -->

[![Github CI Status](https://github.com/pamagister/image-triage/actions/workflows/main.yml/badge.svg)](https://github.com/pamagister/image-triage/actions)
[![GitHub release](https://img.shields.io/github/v/release/pamagister/image-triage)](https://github.com/pamagister/image-triage/releases)
[![Read the Docs](https://readthedocs.org/projects/image-triage/badge/?version=stable)](https://image-triage.readthedocs.io/en/stable/)
[![License](https://img.shields.io/github/license/pamagister/image-triage)](https://github.com/pamagister/image-triage/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/image-triage)](https://pypi.org/project/image-triage)

# Image Triage

Image Triage is a local-first, deterministic photo selection tool. It analyzes a photo library,
groups similar shots, scores technical and aesthetic quality, and selects the best N photos with
explainable quotas and diversity rules. Originals are never modified or deleted.

## Features

- Technical quality: sharpness, defocus versus motion blur, composition and subject placement.
- Learned aesthetic score (small ONNX CNN) with a deterministic heuristic fallback.
- YOLO26 subject detection, corpus-level label rarity and content embeddings.
- Similarity grouping for duplicates and bursts (BLAKE3, pHash, time gap, embeddings).
- Event detection from capture time, day boundaries and GPS jumps.
- Deterministic "best N" selection with event/day/cluster quotas and MMR diversity.
- Typer CLI with stable JSON/NDJSON output and documented exit codes.
- Versioned SQLite state store for 6000+ photos.
- Local FastAPI web GUI (later phase).

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run image-triage doctor
```

The YOLO26 model is not committed. Install it explicitly when you want subject detection:

```bash
uv run image-triage models install yolo
```

Without the model, analysis still runs with sharpness, blur, composition, exposure, heuristic
aesthetics and grouping based on pHash/time/digest.

## Quickstart

```bash
# Analyze a library and export the best 200 photos.
uv run image-triage run --input ~/Photos/2025 --output best-of-2025 --top-n 200

# Inspect the machine-readable result.
uv run image-triage run --input ~/Photos/2025 --output best-of-2025 --top-n 200 --json
```

The output directory contains:

- `report.json` - versioned report with per-photo metrics and score breakdown.
- `selection.csv` - one row per photo for spreadsheets.
- `originals/<relative path>` - copies/hard links/symlinks of the selected originals.
- `<input>/.image-triage/previews/<digest>.webp` - WebP previews of selected photos.

State is stored in `<input>/.image-triage/triage.db` (SQLite, WAL). Re-running reuses unchanged
analysis and is deterministic for the same inputs, models, config and DB state.

## Commands

```text
image-triage scan       --input ... [--json]
image-triage analyze    --input ... [--profile ...] [--json] [--ndjson]
image-triage score      [--input ...] [--json]
image-triage select     --top-n 200 [--profile ...] [--json]
image-triage plan       --input ... --output plan.json [--profile ...]
image-triage apply      --input ... [--plan plan.json]
image-triage export     --input ... --output ... [--mode copy|hardlink|symlink]
image-triage report     [--input ...] [--format json|csv] [--output ...]
image-triage run        --input ... [--top-n 200] [--profile ...] [--json]
image-triage models     install|list [--model yolo|aesthetic]
image-triage benchmark  [--input samples] [--json]
image-triage doctor     [--json]
image-triage schema     [--output schemas/report.schema.json]
image-triage config     init|show|validate
image-triage gui        [--host 127.0.0.1] [--port 8765]
```

Full CLI help is generated in [`docs/usage/cli.md`](docs/usage/cli.md).

## Pipeline

1. **Scan** - recursive JPEG/PNG/TIFF/WebP discovery, EXIF capture time, GPS, dimensions and
   BLAKE3 digest.
2. **Analyze** - 1024 px preview, tile-based sharpness, blur classification, composition,
   YOLO detections/embeddings, aesthetic score, subject rarity and exposure.
3. **Group** - exact duplicates and visually similar shots close in time.
4. **Events** - time-gap, day-boundary and GPS-jump clustering.
5. **Score** - normalized weighted score with a blur gate; 1-5 star rating.
6. **Select** - best per group, event quotas (Sainte-Laguë by default), per-day and per-cluster
   caps, greedy MMR diversity.
7. **Report/export** - JSON report, CSV, WebP previews and optional export.

## Configuration

Configuration uses `image-triage.yaml` with environment overrides. Precedence is:

```text
CLI options > IMAGE_TRIAGE_* environment variables > image-triage.yaml > defaults
```

```bash
uv run image-triage config init
uv run image-triage config show
uv run image-triage config validate
```

The generated defaults are in `config.yaml`; all fields are documented in
[`docs/usage/config.md`](docs/usage/config.md). Selection profiles live in `profiles/`; the default is
`profiles/best200.yaml`.

Performance and scale measurements are in [`docs/usage/performance.md`](docs/usage/performance.md);
model installation and licensing are in [`docs/usage/models.md`](docs/usage/models.md).

## JSON for agents

All commands that support `--json` write a stable JSON document to stdout; human logs go to stderr.
`analyze --ndjson` streams one event per line. Exit codes are stable:

| Code | Meaning |
|---|---|
| 0 | success |
| 2 | usage/configuration error |
| 3 | input error |
| 4 | model/provider missing |
| 5 | partial failure (only with `--strict`) |
| 6 | internal error |

See [`docs/usage/agents.md`](docs/usage/agents.md) and the schemas published by `image-triage schema`.

## Web GUI

The local web GUI is implemented with FastAPI, Jinja and htmx. Start it with:

```bash
uv sync --extra gui
uv run image-triage gui
```

It provides library filtering, photo detail, comparison, soft rating/keep-reject overrides, an
event timeline with a GPS scatter plot and run/export job control. See
[`docs/usage/gui.md`](docs/usage/gui.md).

## Development

```bash
make install
make test
make lint
make docs
```

## License

Image Triage is distributed under the terms in `LICENSE`. The optional YOLO26 model is
AGPL-3.0; its license obligation is documented in the model registry and documentation.