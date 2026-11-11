# Performance and scale

## Benchmark

`image-triage benchmark` detects ONNX Runtime providers, runs every analysis stage on a small
sample and writes `<input>/.image-triage/bench.json`.

```bash
uv run image-triage benchmark --input images --json
```

On the development machine (CPU-only ONNX Runtime, 12 sample photos, 1024 px preview):

| Stage | ms/photo |
|---|---:|
| scan | 18.6 |
| decode | 84.0 |
| sharpness | 30.7 |
| composition | 99.8 |
| YOLO | 388.4 |
| aesthetic (heuristic) | 17.5 |
| **total** | **640.7** |

The CPU fallback target is about 1 s/photo, so the default configuration meets it on this
hardware. GPU providers (CUDA, ROCm, OpenVINO, DirectML) are detected and reported; the default
`models.provider` is `CPUExecutionProvider` for reproducibility. Set it to `auto` to prefer an
available GPU provider.

## 6000-photo scale run

The synthetic library generator creates a deterministic 6000-photo library without network
access:

```bash
uv run python scripts/generate_synthetic_library.py /tmp/library --count 6000
```

The run below used a 256 px preview, no YOLO model and the default profile:

```bash
uv run image-triage run \
  --input /tmp/library \
  --output /tmp/library-out \
  --top-n 200 \
  --json
```

Measured on the development machine:

| Metric | Value |
|---|---:|
| Photos analyzed | 6000 |
| Wall time, first run | 78 s |
| Wall time, resumable re-run | 9.3 s |
| Throughput, first run | ~13 ms/photo |
| SQLite database | 6.3 MB |
| Peak resident memory | ~165 MB |
| Selected photos | 200 |
| Events | 300 |
| Report size | 11 MB |

The re-run reused all 6000 analyses and produced a byte-identical `report.json`, including the
same run id, event ids and selection. This verifies deterministic selection at scale.

## Notes

- Decoding uses JPEG draft mode and a bounded preview (default 1024 px; 256 px for the scale
  run), which keeps memory bounded and avoids decoding full-resolution originals.
- Analysis is resumable: `(digest, model_signature, metric_version)` is the cache key.
- The database uses WAL mode and indexes on path, capture time, event, group, score and rating.
- With YOLO enabled, expect roughly 0.6 s/photo on CPU; the 6000-photo library then takes about
  one hour. Use `models.provider: auto` and a GPU extra for faster inference.
- The synthetic generator is for scale testing only; it does not replace real-photo validation.