# Installation

## From PyPI

```bash
pip install image-triage
image-triage doctor
```

## From source

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/pamagister/image-triage.git
cd image-triage
uv sync
uv run image-triage doctor
```

For development, install the dev and docs groups as well:

```bash
uv sync --all-groups
```

## Optional models

Image analysis works without downloaded models, but YOLO subject detection and embeddings need
the YOLO26 ONNX model:

```bash
uv run image-triage models install yolo
```

The model is stored under `res/yolo/` by default and is never committed to the repository.

## Optional web GUI

The local web GUI is started with any of these equivalent commands:

```bash
uv run python -m image_triage.gui
uv run image-triage gui
image-triage-gui  # after installation
```

It binds to `127.0.0.1:8765` by default and has no authentication; it is intended for a single
local user. On first start it asks for the photo library folder, then scans it, so no CLI run is
required before the library appears. See [the GUI guide](../usage/gui.md) for the full workflow.