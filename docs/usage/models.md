# Models

## YOLO26 object detector

YOLO26 is used for subject detection, corpus-level label rarity and content embeddings. The
model is not committed to the repository.

```bash
uv run image-triage models install yolo
uv run image-triage models list
```

The download is checksum-verified (SHA256) and its license is recorded in
`res/models/registry.json`. YOLO26 is licensed under AGPL-3.0; if you distribute a binary that
includes it, you must comply with the AGPL source and license obligations.

Without the model, analysis still runs. Subject score and rarity default to zero and grouping
falls back to digest, pHash and capture time.

## Aesthetic model

The aesthetic stage accepts a small NIMA-style ONNX CNN. No centrally hosted, license-verified
download is bundled because the available NIMA weights are often non-commercial or have unclear
redistribution terms. Install a local file explicitly:

```bash
uv run image-triage models install aesthetic --path /path/to/aesthetic.onnx --sha256 <sha256>
```

The SHA256 and your chosen license metadata are recorded in the registry. If no aesthetic model
is installed, a deterministic heuristic interest score is used instead. This is documented in the
report as `metrics.aesthetic_source: "heuristic"`; a learned model reports `"onnx"`.

## Provider selection

`image-triage benchmark` lists available ONNX Runtime providers. The default is CPU for
reproducibility. To prefer a GPU provider, set `models.provider` to `auto`, `CUDAExecutionProvider`,
`ROCMExecutionProvider`, `OpenVINOExecutionProvider` or `DmlExecutionProvider` in
`image-triage.yaml` or with `IMAGE_TRIAGE_MODELS__PROVIDER`.