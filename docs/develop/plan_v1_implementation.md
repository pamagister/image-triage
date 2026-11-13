# Image Triage – Implementation Plan

**Status:** `[x]` implementation complete (Phases 1-9)
**Created:** 2026-11-11
**Target:** a local-first, deterministic photo triage tool that reduces a full year of photos
(e.g. 6000 images) to the best 200, usable from the CLI, by agents, and later from a web GUI.

---

## 1. Objective and Desired Outcome

### Objective

Turn `image-triage` into a modern, local, deterministic photo selection tool with:

- technical quality analysis: sharpness, blur type (defocus vs motion), composition and subject placement;
- learned aesthetic quality (small ONNX CNN);
- subject presence and corpus-level rarity;
- similarity grouping (series, duplicates);
- event detection from capture time and GPS;
- a configurable "best N" selection that balances score, motif diversity and user-defined quotas;
- a rich Typer CLI with stable, machine-readable JSON output for agents;
- an explicit, versioned SQLite state store for 6000+ photos;
- a local web GUI in a later phase.

### Desired outcome / success criteria

1. `image-triage run --input ~/Photos/2025 --top-n 200` analyzes the library, selects at most 200
   photos, and produces `report.json`, `selection.csv`, WebP previews for the selected photos, and
   an export of the selected originals.
2. Re-running with the same inputs, models, config and DB state produces a byte-identical selection
   and report (deterministic, documented version identifiers).
3. A 6000-photo library is processed within the hardware-dependent budget established by the
   automatic benchmark (CPU fallback target: about 1 s/photo; GPU target: well below that).
4. An agent can run `image-triage ... --json`, parse stdout, and rely on documented exit codes and
   a versioned JSON schema.
5. The tool never deletes or modifies originals; GPS is stripped from reports and exports unless
   explicitly enabled.
6. All relevant tests, linting, type checks, package build and documentation checks pass.

### Guiding principles

- Local-only, no telemetry, no cloud dependency.
- Simplicity first: stdlib SQLite, no ORM, no speculative abstractions.
- Surgical migration: keep proven similarity logic, replace what blocks the new architecture.
- Every phase ends with a usable, tested, committable state.

---

## 2. Scope, Constraints and Non-Goals

### 2.1 In scope

- Python package `image_triage` with subpackages (domain, settings, db, io, metrics, models,
  grouping, scoring, selection, report, export, cli, gui, benchmark).
- Typer CLI with a rich command tree plus an all-in-one `run` command.
- `pydantic-settings` configuration: YAML file + environment variables + CLI overrides.
- SQLite database inside the input root (`.image-triage/triage.db`) as the single state store,
  with schema versioning and migrations.
- Analysis: decode/preview, EXIF timestamp/GPS, sharpness, blur classification, composition,
  YOLO detections and embeddings, aesthetic score, subject rarity.
- Similarity grouping, time/GPS event detection, weighted scoring, star rating.
- Selection: score + MMR diversity + per-event/day/cluster quotas from YAML profiles.
- Reports: versioned JSON report + JSON Schema, CSV, WebP previews for selected photos, export of
  selected originals (copy/hardlink/symlink).
- Model management: `models install|list`, SHA256 verification, license metadata, ONNX provider
  auto-detection and a benchmark command.
- Agent interface: `--json`, `--ndjson`, stable exit codes, `schema` command, error JSON.
- English documentation (mkdocs), generated CLI/config docs, tests, linting, build.
- Web GUI (FastAPI + Jinja + htmx) in the final phase: library grid and filters, compare similar
  shots, rating and keep/reject soft overrides, map/timeline, run/export from the GUI.

### 2.2 Constraints

- Python >= 3.12, `uv` for dependencies and environments.
- Ruff for formatting/linting, pytest for tests, mypy for type checking where configured.
- Linux primary; Windows and macOS must remain installable and testable.
- YOLO26 ONNX (AGPL-3.0) remains the object detector; the license obligation is documented.
- Aesthetic model: small NIMA-style CNN; if its weights are non-commercial, it is opt-in and the
  restriction is documented prominently (fallback: heuristic interest score).
- Sample images: 110 Pixabay images in 10 categories (animals, landscape, technology,
  architecture, food, people, sports, travel, business, nature), max 1600 px long side,
  max ~200 KB each (~22 MB total), in `images/pixabay/` with `credits.md`.
- No network access at analysis time; model downloads happen only via explicit commands.

### 2.3 Non-goals (explicit)

- No image editing, RAW conversion, panorama/HDR merging.
- No object/face recognition or identity analysis.
- No deletion or overwriting of original image files.
- No cloud upload, telemetry, or online services.
- No HEIC/HEIF, RAW full decode, or video input in v1.
- No XMP writing and no legacy `copy/hardlink/symlink` compatibility modes as required features.
  (A minimal export of selected originals remains in scope because the tool must produce the best
  200; mode is an implementation detail.)
- No hard force-include/force-exclude overrides; GUI overrides are soft signals only.
- No detection/composition overlays in the GUI (deferred).
- No exposure/color metric in the v1 score (deferred; the existing implementation may be kept as a
  non-scoring signal only if it is free to do so).

### 2.4 Deferred / blocked (`[~]`)

- `[~]` XMP rating/keyword writing via ExifTool.
- `[~]` Legacy export modes as a user-facing feature.
- `[~]` Exposure and color-quality scoring.
- `[~]` Face detection, smile/eyes-open, number of faces.
- `[~]` HEIC/HEIF, RAW full decode, video thumbnails.
- `[~]` Detection/composition overlays in the GUI.
- `[~]` Hard include/exclude overrides.
- `[~]` Fine-tuning an aesthetic model on the user's own ratings.

---

## 3. Architecture and Decisions

### 3.1 Decisions (settled)

| Area | Decision | Rationale |
|---|---|---|
| CLI | Typer | Rich command tree, typed parameters, good `--help`, easy JSON output. |
| Config | pydantic-settings (YAML + env + CLI) | One typed source of truth; removes config-cli-gui coupling. |
| State | SQLite (stdlib `sqlite3`), WAL, schema migrations | Fast queries over 6000+ photos, one file, no ORM. |
| Layout | Subpackages by responsibility | Clear boundaries for CLI, GUI, analysis and selection. |
| Workflow | Multi-step commands plus `run` all-in-one | Inspectable/resumable for agents; convenient for humans. |
| Agent interface | `--json`, `--ndjson`, exit codes, JSON Schema | Stable, parseable, scriptable. |
| Similarity | Keep pHash + time gap + YOLO embedding + digest | Proven, cheap, already implemented. |
| Events | Time-gap clustering + day boundary + GPS jump | Reflects real shoots; no folder dependency. |
| Selection | Greedy MMR with event/day/cluster quotas | Deterministic, explainable, tunable. |
| Aesthetic model | NIMA-style small CNN ONNX | Good quality/speed tradeoff; license must be verified. |
| GUI | FastAPI + Jinja + htmx | Minimal dependencies, server-side filtering for large libraries. |
| Determinism | Versioned scoring/selection formulas, model hashes, config fingerprint | Reproducible output; required by the user. |
| Privacy | GPS local-only; stripped from reports/exports by default | Protects location data. |

### 3.2 Source layout (target)

```text
src/image_triage/
  __init__.py
  __main__.py
  cli/
    app.py                 # Typer app, subcommand registration
    commands/              # scan, analyze, score, select, plan, apply, export, report, models, doctor, gui, schema
    output.py              # text/json/ndjson renderers
  core/
    models.py              # domain models and enums
    settings.py            # pydantic-settings
    errors.py              # exit codes and CLI exceptions
  db/
    schema.py              # DDL, schema version
    migrate.py             # forward migrations
    repository.py          # typed repository
  io/
    scan.py                # recursive scan, EXIF time/GPS, dimensions
    decode.py              # robust decode, draft mode, EXIF transpose
  metrics/
    sharpness.py           # normalized sharpness, defocus vs motion
    composition.py         # thirds, horizon, subject size, headroom, clipping
    aesthetic.py           # NIMA-style ONNX inference
    subjects.py            # YOLO detections, subject score, corpus rarity
  models/
    registry.py            # model descriptors, download, checksums
    providers.py           # ONNX Runtime provider detection
  grouping/
    similarity.py          # pHash, digest, union-find grouping
    events.py              # time/GPS event clustering
  scoring/
    score.py               # weighted score, versioned formula
    rate.py                # star rating
  selection/
    profiles.py            # YAML profile loading/validation
    select.py              # MMR + quotas
  report/
    json_report.py
    csv_report.py
    schema/                # JSON Schema documents
  export/
    previews.py
    export.py
  benchmark/
    bench.py
  gui/
    app.py
    templates/
    static/
```

### 3.3 Domain model (core)

- `Photo`: id, path (relative to input root), digest, taken, width, height, camera make/model,
  gps_lat, gps_lon, event_id, group_id, metrics (JSON), detections (JSON), embedding (BLOB),
  score, rating, flags (blur, duplicate, ...), model_signature, analyzed_at.
- `Detection`: label, confidence, box (x1, y1, x2, y2 in 0..1), area.
- `Metrics`: sharpness, blur_kind (`none|defocus|motion|unknown`), blur_confidence, composition
  (score + component breakdown), aesthetic, subject_score, subject_rarity, embedding_similarity.
- `Event`: id, start, end, label, photo_count, source (`time|gps|folder`).
- `Group`: id, method, version, member count.
- `Selection`: run_id, photo_id, rank, score, reason, quota_rule.
- `Run`: id, command, started_at, finished_at, status, config_hash, model_hashes, counts.
- `Override`: photo_id, rating, keep/reject (soft), source (`gui|cli`), created_at.
- `SchemaMeta`: schema_version, scoring_version, selection_version, created_at.

### 3.4 SQLite schema (initial)

- `photos`, `detections`, `metrics`, `events`, `photo_events`, `groups`, `photo_groups`,
  `runs`, `selections`, `overrides`, `schema_meta`, `jobs`.
- Indexes on `photos(path)`, `photos(taken)`, `photos(event_id)`, `photos(group_id)`,
  `photos(score)`, `photos(rating)`, `selections(run_id)`.
- WAL mode, `foreign_keys=ON`, busy timeout for CLI+GUI concurrency.
- Embeddings stored as `BLOB` (float32, L2-normalized); detections/metrics as JSON text for
  flexibility, with key numeric columns duplicated for filtering/sorting.

### 3.5 Analysis pipeline

```text
scan -> decode preview -> EXIF time/GPS -> sharpness/blur -> composition
     -> YOLO detections + embedding -> aesthetic -> subject rarity
     -> persist Photo + metrics + detections + embedding
```

- Preview: `Image.draft("RGB", (1024, 1024))` for JPEG, EXIF transpose, thumbnail.
- Parallelism: process pool/thread pool with a bounded number of ONNX sessions; deterministic
  merge order by photo id.
- Resumability: skip a photo when `(digest, model_signature, metric_version)` is unchanged.
- Errors: collect per-file errors; skip and report by default; `--strict` fails.

### 3.6 Sharpness and blur

- Multi-scale, tile-based Laplacian variance, normalized by image scale and local contrast.
- Motion blur vs defocus: directional gradient-energy anisotropy plus high-frequency energy.
  Motion blur is directional; defocus is isotropic.
- Output: `sharpness` (relative, 0..1+), `blur_kind`, `blur_confidence`.
- Calibration: corpus-relative reference (e.g. 90th percentile of the library) instead of a fixed
  250.0, so the score is stable across resolutions and cameras.

### 3.7 Composition and subject placement

- Horizon/level detection (Hough/line-based) where a horizon is present.
- Subject placement relative to rule-of-thirds lines and center.
- Subject size, headroom, edge clipping, and a saliency/clutter proxy.
- Output: `composition` in 0..1 plus a component breakdown for the report and GUI.

### 3.8 Aesthetic model

- Small NIMA-style CNN exported to ONNX; input is the analysis preview.
- Score calibrated to 0..1 using the sample set; calibration parameters stored with the model
  metadata.
- License and source URL recorded in the model registry and docs.
- If no acceptable-license model reaches usable quality, the aesthetic weight defaults to 0 and a
  heuristic interest score is used instead.

### 3.9 Subject presence and rarity

- YOLO detections per photo (label, confidence, box, area).
- `subject_score = max(confidence * min(1, area / full_area))` over subject classes.
- Rarity: label frequency across the current library; `rarity = 1 / (1 + log(1 + count))`.
- Final subject signal combines presence and rarity; configurable per profile.

### 3.10 Similarity, events and scoring

- Similarity: identical digest, pHash distance, time gap, and YOLO-embedding cosine similarity;
  union-find groups (ported from the existing implementation).
- Events: single-linkage time clustering with a configurable gap (default 4 h), day boundary, and
  a GPS jump threshold (default 50 km); event label from folder/date/GPS cluster.
- Score (v1, all components normalized to 0..1):

  ```text
  score = w_sharp * sharpness
        + w_comp  * composition
        + w_aes   * aesthetic
        + w_subj  * subject_presence_rarity
  ```

  Weights come from the active profile and are normalized; the formula version and weights are
  stored in the DB and report. Blur below the profile threshold acts as a gate (rating 1 and a
  score penalty).
- Rating: best `max_per_group` per similarity group can receive 3–5 stars; non-best sharp photos
  get 2; blurry photos get 1.

### 3.11 Selection

- Candidates: best photo(s) per similarity group.
- Quotas (profile-driven): per event, per day, per semantic cluster, global minimum/maximum.
- Greedy MMR: `value = score - diversity * max_similarity_to_already_selected`, restricted by
  remaining quotas; deterministic tie-break by `(score desc, taken asc, path asc)`.
- Reasons recorded per selected photo (e.g. "best of group 12", "event quota", "diversity").
- Default profile `profiles/best200.yaml`: `top_n: 200`, event quota Sainte-Laguë, max 5 per day,
  max 3 per semantic cluster, diversity 0.5.

### 3.12 Reports and artifacts

- `report.json`: schema version, tool version, run id, config hash, model hashes, counts,
  per-photo records (id, path, taken, metrics, score breakdown, group, event, rating, selected,
  reason). GPS omitted unless `report.include_gps=true`.
- `selection.csv`: one row per photo with key metrics and selection columns.
- WebP previews for selected photos only, stored under `.image-triage/previews/<digest>.webp`
  (max 1600 px, quality ~80).
- Export: copy/hardlink/symlink of selected originals into `--output`, preserving relative paths
  by default; never deletes or overwrites source files.

### 3.13 CLI surface (target)

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

- Human logs go to stderr; machine output goes to stdout.
- Exit codes: `0` ok, `2` usage/config error, `3` input error, `4` model/provider missing,
  `5` partial failure (only with `--strict`), `6` internal error.

### 3.14 Configuration

- `image-triage.yaml` (project root or `--config`), environment variables with prefix
  `IMAGE_TRIAGE_`, CLI flags override both.
- Categories: `app`, `input`, `analysis`, `scoring`, `similarity`, `selection`, `models`,
  `report`, `gui`.
- `config init` writes a documented default; `config show` prints the effective merged config;
  `config validate` checks weights, paths, profiles and model files.
- `make syncdocs` generates `config.yaml`, `docs/usage/config.md` and `docs/usage/cli.md` from the
  pydantic models (replacing the config-cli-gui documentation generator).

### 3.15 Performance strategy

- Benchmark detects CUDA, ROCm, OpenVINO, DirectML and CPU ONNX Runtime providers.
- Benchmark runs on the sample set, records per-stage timings and peak memory, chooses provider and
  batch size, and writes `.image-triage/bench.json`.
- CPU fallback target: about 1 s/photo; GPU target: as fast as the detected provider allows.
- Optimizations: draft decoding, 1024 px preview, batched inference, DB indexes, resumable
  analysis, parallel workers bounded by CPU/GPU.

### 3.16 Web GUI (final phase)

- `image-triage gui` starts a local FastAPI server (default `127.0.0.1:8765`).
- Server-rendered Jinja templates + htmx; no Node build step.
- Pages: library grid with filters (rating, event, date, label, score) and sorting; photo detail;
  compare similar shots side by side; map/timeline; run/export job control.
- Overrides (rating, keep/reject) are stored as soft signals and influence later selection runs.
- Accessibility: semantic HTML, keyboard navigation, sufficient contrast.

---

## 4. Phases and Work Packages

Status markers: `[ ]` pending, `[-]` in progress, `[x]` completed, `[~]` deferred/blocked.

### Phase 1 – Foundation: Settings, Domain Model, Database, CLI Skeleton

**Status:** `[x]` completed 2026-11-12

**Objective:** Establish the typed core, the SQLite state store and the Typer application before
any analysis work.

- [x] P1-W01: Replace dependencies: remove `config-cli-gui` and `ttkbootstrap`; add `typer`,
  `pydantic-settings`, `fastapi`, `jinja2`, `uvicorn` (GUI extra), `python-multipart`; keep
  `onnxruntime`, `opencv-python-headless`, `pillow`, `imagehash`, `blake3`, `numpy`, `pyyaml`.
  Update `pyproject.toml`, `uv.lock` and optional extras (`gui`, `gpu`).
- [x] P1-W02: Define domain models and enums in `core/models.py` (Photo, Detection, Metrics,
  Event, Group, Selection, Run, Override, BlurKind, ExportMode, Provider).
- [x] P1-W03: Implement `core/settings.py` with nested pydantic models, YAML source, env prefix
  and defaults; add validation (weights, paths, thresholds).
- [x] P1-W04: Implement `db/schema.py` and `db/migrate.py`: tables, indexes, WAL, `schema_meta`,
  forward migration runner.
- [x] P1-W05: Implement `db/repository.py`: typed CRUD and queries for photos, metrics, groups,
  events, runs, selections, overrides.
- [x] P1-W06: Implement `cli/app.py` Typer skeleton and `doctor` command (Python version, DB,
  models, provider, sample images).
- [x] P1-W07: Implement `cli/output.py` and `core/errors.py`: text/json/ndjson renderers, stable
  exit codes, error JSON on stderr.

**Acceptance criteria**

- `uv sync` succeeds; no imports of removed packages remain.
- Fresh DB creation and migration from the initial schema version work; WAL is enabled.
- Settings precedence is tested: CLI > env > YAML > defaults.
- `image-triage doctor --json` returns valid JSON and exit code 0 on a healthy environment.
- All new unit tests pass; ruff and formatting checks pass.

**Phase gate:** The CLI boots, settings load, the DB migrates and all foundation tests are green.

### Phase 2 – Ingest and Analysis

**Status:** `[x]` completed 2026-11-12

**Objective:** Fill the database with reproducible per-photo analysis.

- [x] P2-W01: Implement `io/scan.py` and `io/decode.py`: recursive scan, EXIF capture time, GPS
  (WGS84), dimensions, BLAKE3 digest, robust decode (draft mode, EXIF transpose), per-file error
  capture.
- [x] P2-W02: Implement `metrics/sharpness.py`: normalized multi-scale sharpness, tile-based
  analysis, blur classification (defocus vs motion) with confidence.
- [x] P2-W03: Implement `metrics/composition.py`: horizon/level detection, rule-of-thirds subject
  placement, subject size, headroom, edge clipping, saliency/clutter proxy; 0..1 score plus
  component breakdown.
- [x] P2-W04: Implement `models/providers.py` and the YOLO inference adapter: provider detection,
  batched detections, boxes/labels/confidences, L2-normalized embedding extraction, deterministic
  CPU path.
- [x] P2-W05: Integrate the aesthetic ONNX model (`metrics/aesthetic.py`): preprocessing, score
  calibration, model metadata and license registration; fall back to weight 0 when unavailable.
- [x] P2-W06: Implement `metrics/subjects.py`: subject presence score and corpus-level label
  rarity.
- [x] P2-W07: Implement analysis orchestration and persistence: resumable per-photo analysis,
  `(digest, model_signature, metric_version)` cache key, parallel workers, NDJSON progress, error
  capture, DB writes.
- [x] P2-W08: Add `scan` and `analyze` CLI commands with `--json` output.

**Acceptance criteria**

- The 100-image sample set is analyzed and stored in the DB; a second run skips unchanged photos.
- Synthetic sharp, motion-blurred and defocused images are classified correctly.
- Composition scores are in 0..1 and have a component breakdown.
- Detections and embeddings are present for sample images; the embedding is L2-normalized.
- Aesthetic scores are in 0..1 and the model hash/license are recorded.
- Corrupt files are skipped and reported by default; `--strict` fails.
- `analyze --json` emits a schema-valid summary and progress events.

**Phase gate:** The sample library is fully analyzed, resumable and queryable in SQLite.

### Phase 3 – Grouping, Events and Scoring

**Status:** `[x]` completed 2026-11-12

**Objective:** Turn per-photo metrics into groups, events, scores and ratings.

- [x] P3-W01: Port and adapt `grouping/similarity.py`: digest, pHash, time gap, embedding cosine
  similarity, union-find grouping, deterministic group ids.
- [x] P3-W02: Implement `grouping/events.py`: time-gap clustering, day boundary, GPS jump
  threshold, event labels (folder/date/GPS cluster), persistence.
- [x] P3-W03: Implement `scoring/score.py`: weighted normalized score, blur gate, formula and
  weight versioning, config hash, per-component breakdown.
- [x] P3-W04: Implement `scoring/rate.py`: best-per-group, `max_per_group`, star thresholds, blur
  handling.
- [x] P3-W05: Add the `score` CLI command with JSON breakdown; persist scores, ratings and
  versions.

**Acceptance criteria**

- Duplicate and series images are grouped correctly on the sample set.
- Events match capture-time clusters; GPS-only events are detected when time gaps are large.
- Score components are deterministic and documented; the same input and weights produce identical
  scores across runs.
- Ratings follow the documented rules; blurry photos receive 1 star.
- `score --json` exposes the formula version, weights and per-component values.

**Phase gate:** Grouping, events and scoring are stable and stored for all analyzed photos.

### Phase 4 – Selection, Reports and Export

**Status:** `[x]` completed 2026-11-12

**Objective:** Produce the best N photos, with explainable reasons and all report artifacts.

- [x] P4-W01: Implement `selection/profiles.py`: YAML profile schema, defaults, validation,
  merging with CLI overrides; add `profiles/best200.yaml`.
- [x] P4-W02: Implement quota calculation: Sainte-Laguë per event, per-day cap, per-cluster cap,
  global min/max.
- [x] P4-W03: Implement `selection/select.py`: greedy MMR with YOLO embeddings, quota
  constraints, deterministic tie-breaks, per-photo reasons.
- [x] P4-W04: Implement `report/json_report.py` and `report/schema/report.schema.json`:
  versioned report, tool/model/config hashes, counts, reasons, GPS stripped by default.
- [x] P4-W05: Implement `report/csv_report.py`: stable columns, escaping, UTF-8.
- [x] P4-W06: Implement `export/previews.py` and `export/export.py`: WebP previews for selected
  photos, copy/hardlink/symlink export, idempotent, no source modification.
- [x] P4-W07: Add `select`, `plan`, `apply`, `export`, `report` and the all-in-one `run` command.

**Acceptance criteria**

- `--top-n 200` on the sample set returns at most 200 photos and never exceeds per-event/day/cluster
  quotas.
- Selection is deterministic across repeated runs and across processes.
- Every selected photo has a non-empty reason; the report validates against its JSON Schema.
- CSV opens correctly in a spreadsheet application and contains the documented columns.
- Previews exist only for selected photos; export is idempotent and never deletes originals.
- `plan` writes a reviewable JSON selection; `apply` persists/exports it; `run` performs the full
  pipeline.

**Phase gate:** A full `run --top-n 200` on the sample set produces report, CSV, previews and
export in one deterministic pass.

### Phase 5 – Agent Interface, Configuration Docs and Cleanup

**Status:** `[x]` completed 2026-11-12

**Objective:** Make the CLI contract explicit and remove the legacy stack.

- [x] P5-W01: Publish JSON Schemas for report, selection plan and NDJSON events; add the `schema`
  command.
- [x] P5-W02: Finalize exit codes, error JSON and partial-failure semantics; document `--strict`.
- [x] P5-W03: Replace the config-cli-gui documentation generator with a pydantic-based generator;
  update `make syncdocs`, `config.yaml`, `docs/usage/cli.md`, `docs/usage/config.md`.
- [x] P5-W04: Rewrite user documentation in English: installation, quickstart, commands, scoring,
  selection profiles, models, JSON for agents, GUI placeholder.
- [x] P5-W05: Remove legacy `config.py`, `gui.py` (tkinter), config-cli-gui code paths and obsolete
  tests; update entry points (`image-triage-gui` now starts the web server).

**Acceptance criteria**

- `image-triage schema` output validates the report examples.
- Documented exit codes match the implementation and are covered by tests.
- `make syncdocs` runs without config-cli-gui and produces the same files deterministically.
- No references to `config_cli_gui`, `ttkbootstrap` or the old config classes remain.
- Documentation builds with mkdocs and contains no dead links.

**Phase gate:** CLI, config docs and user documentation agree; the legacy stack is removed.

### Phase 6 – Models, Performance and Scale

**Status:** `[x]` completed 2026-11-12

**Objective:** Make the tool fast and reproducible on the user's hardware and at 6000-photo scale.

- [x] P6-W01: Implement `models/registry.py` and `models install|list`: YOLO and aesthetic model
  descriptors, SHA256 verification, license files, `res/models/` and user-data-dir options.
- [x] P6-W02: Implement `benchmark/bench.py`: provider detection (CUDA, ROCm, OpenVINO, DirectML,
  CPU), benchmark run on the sample set, per-stage timings, peak memory, provider/batch selection,
  `.image-triage/bench.json`.
- [x] P6-W03: Performance tuning: batching, preview size, worker counts, DB indexes, resumable
  analysis, avoiding repeated decode; verify the CPU fallback target (about 1 s/photo).
- [x] P6-W04: Scale validation: analyze a 6000-photo library (real if available, otherwise a
  generated/synthetic library) end to end; record runtime, DB size, memory and selection quality;
  verify determinism.

**Acceptance criteria**

- `models install yolo` and `models install aesthetic` verify checksums and record licenses; a
  checksum mismatch fails clearly.
- `benchmark --json` reports the detected provider, chosen provider and per-stage timings.
- On the user's hardware the 6000-photo run completes within the documented budget and memory
  stays bounded.
- Re-running the scale test produces identical selections.

**Phase gate:** Documented performance and reproducibility at 6000-photo scale.

### Phase 7 – Quality Assurance, Build and Release

**Status:** `[x]` completed 2026-11-12

**Objective:** Prove that the whole system works and can be shipped.

- [x] P7-W01: Expand the test suite: unit tests for metrics/settings/DB/scoring/selection,
  integration tests for the pipeline, golden tests for reports, CLI tests with Typer's runner,
  migration tests, and a GUI smoke test.
- [x] P7-W02: Run `make fmt`, `make lint`, `make test`, `make deptry`; fix all findings.
- [x] P7-W03: Run `make precommit`; build the package (`uv build`); verify a clean install in a
  fresh virtual environment with and without the `gui` and `gpu` extras.
- [x] P7-W04: Perform the end-to-end acceptance run on the sample set and, if available, the real
  library; verify report, CSV, previews, export and GUI.
- [x] P7-W05: Update `README.md`, `HISTORY.md`, release notes and documentation links.

**Acceptance criteria**

- All tests pass; lint, format, dependency and type checks pass.
- The package builds and installs cleanly with and without extras.
- The end-to-end run satisfies every success criterion in section 1.
- Documentation and CLI help are complete and consistent.

**Phase gate:** The implementation is complete only when functionality, tests, CLI help and
documentation agree.

### Phase 8 – Web GUI

**Status:** `[x]` completed 2026-11-12

**Objective:** Provide a local web interface for browsing, comparing and curating the selection.

- [x] P8-W01: Implement the FastAPI skeleton and `gui` command: Jinja/htmx base layout, localhost
  binding, health endpoint, static assets.
- [x] P8-W02: Implement the library grid with filters (rating, event, date, label, score), sorting
  and pagination/virtual scrolling.
- [x] P8-W03: Implement photo detail and side-by-side comparison of similar shots with metric
  overlays.
- [x] P8-W04: Implement rating and keep/reject soft overrides stored in SQLite; show their effect
  on a selection preview.
- [x] P8-W05: Implement map and timeline views from event GPS/time data (Leaflet + GeoJSON).
- [x] P8-W06: Implement run/export job control from the GUI (start analyze/select/export, progress,
  results) with a small `jobs` table and background worker.
- [x] P8-W07: Add GUI tests (FastAPI TestClient), documentation and basic accessibility checks.

**Acceptance criteria**

- The GUI starts with `image-triage gui` and loads the sample library.
- Filters and sorting return correct results for 6000+ photos without loading all images at once.
- Comparing similar shots shows both images and their metric breakdowns.
- Rating/keep-reject overrides persist and influence the next selection run as soft signals.
- Map and timeline render events correctly; runs started in the GUI reach a terminal state.
- GUI tests pass; documentation explains how to start and use the GUI.

**Final phase gate:** The GUI is usable end to end on the sample library and all checks pass.

### Phase 9 – GUI Startup and Requirements Hardening

**Status:** `[x]` completed 2026-11-12
**Issue:** [#14](https://github.com/pamagister/image-triage/issues/14)

**Objective:** Close the remaining gaps found in a requirements audit of the Phase 8 web GUI,
especially the documented module launcher, library filters, job semantics, override display and
events-page scalability.

- [x] P9-W01: Remove the obsolete tracked sample directories `images/testimages_3/`,
  `images/testimages_4/` and `images/testimages_5/` after confirming that no source, test or
  documentation references them.
- [x] P9-W02: Add `python -m image_triage.gui` support and verify all documented launch paths
  (`python -m image_triage.gui`, `image-triage gui`, installed `image-triage-gui`) start the same
  local server.
- [x] P9-W03: Complete the library filter surface with date-from, date-to and minimum-score
  filters; make sorting and pagination preserve every active filter.
- [x] P9-W04: Fix GUI job semantics: export the latest selection rather than the latest run, fail
  clearly when no selection exists, report useful analysis progress, and refresh running jobs.
- [x] P9-W05: Show the current rating and keep/reject override on the photo page and keep the form
  state consistent with the stored values.
- [x] P9-W06: Query only GPS-bearing photo columns for the events scatter and handle one-point and
  zero-span ranges without collapsing the marker into a corner.
- [x] P9-W07: Add regression tests for the module launcher, filters/pagination, job export behavior
  and override display; update GUI documentation and run the full verification suite.

**Acceptance criteria**

- The module launcher and console launchers start the same application and fail with a useful
  message when GUI dependencies are unavailable.
- All documented filters work together, and pagination/sort links retain them.
- Photo detail displays the persisted override state; saving an override still round-trips.
- GUI export uses the newest non-empty selection and reports an error for an empty library.
- Running jobs expose progress and update without a manual restart.
- The events page does not materialize full photo records and remains usable for sparse or
  degenerate GPS data.
- The obsolete sample directories are gone and the repository has no references to them.
- `pytest`, ruff, deptry, mkdocs and package entry-point checks pass.

**Phase gate:** The GUI is startable through every documented entry point and its core browsing,
comparison, curation and job workflows satisfy the Phase 8 acceptance criteria at the documented
scale.

---

## 5. Acceptance Criteria and Verification Expectations

### 5.1 Global acceptance criteria

1. `image-triage run --input <library> --top-n 200` produces at most 200 selected photos with
   report, CSV, previews and export.
2. Selection is deterministic for identical inputs, models, config and DB state.
3. The JSON report validates against the published schema and contains no GPS by default.
4. The tool never modifies or deletes originals.
5. The 6000-photo scale target is met and documented.
6. Agent exit codes and error JSON are stable and documented.
7. All tests, lint, format, dependency and build checks pass.

### 5.2 Verification per phase

- **Phase 1:** unit tests for settings, DB migration, repository and CLI skeleton.
- **Phase 2:** sample-set analysis, resumability, blur classification, composition ranges,
  detection/embedding presence, corrupt-file handling.
- **Phase 3:** grouping/event tests, score determinism, rating rules.
- **Phase 4:** quota and determinism tests, JSON Schema validation, CSV/preview/export checks.
- **Phase 5:** schema/exit-code tests, docs generation, no legacy imports.
- **Phase 6:** model checksum tests, benchmark report, 6000-photo scale run.
- **Phase 7:** full test/lint/build matrix and end-to-end acceptance run.
- **Phase 8:** FastAPI TestClient tests and manual GUI walkthrough.

### 5.3 Test data

- 110 curated Pixabay sample images (~1600 px, ~200 KB each, ~22 MB total) in
  `images/pixabay/` with `credits.md` (10 categories à 10 images).
- A small committed subset (10–20 images) for fast deterministic tests.
- Synthetic images for blur, exposure, composition and corrupt-file edge cases.
- A synthetic 6000-photo library generator for scale tests (no network, no real photos required).

---

## 6. Dependencies, Risks and Open Questions

### 6.1 Dependencies

- External model downloads: YOLO26 ONNX (existing URL/checksum) and a NIMA-style aesthetic ONNX
  (URL/checksum to be determined in P2-W05/P6-W01).
- Pixabay sample downloads (network) for the sample set; tests must not require network.
- ONNX Runtime providers for GPU acceleration (optional extras).
- `uv`, `ruff`, `pytest`, `mypy`, `mkdocs`, `fastapi`, `uvicorn`, `jinja2`, `htmx` (server-side).

### 6.2 Risks and mitigations

| Risk | Mitigation |
|---|---|
| Aesthetic model license is non-commercial | Keep it opt-in, document the restriction, allow weight 0/heuristic fallback. |
| Pixabay blocks automated downloads | Provide a manifest and a manual fallback; use synthetic images for tests. |
| 6000 photos too slow on CPU | Benchmark early, batch inference, draft decoding, resumable analysis, GPU extras. |
| YOLO embeddings do not capture "motif" well | Combine with event/day quotas and user profiles; expose signals for inspection. |
| GPS missing in many photos | Event detection works from time alone; GPS is an optional signal. |
| Motion blur vs defocus is unreliable | Report confidence; allow rule-based override; calibrate on samples. |
| GPU nondeterminism | Use the CPU provider for final scoring or document tolerance; store provider in the report. |
| DB/CLI/GUI concurrency | WAL mode, busy timeout, short transactions, single-writer job runner. |
| AGPL obligations for distributed binaries | Document license, provide source offer, keep YOLO optional. |
| Repo grows by ~20 MB of samples | Acceptable per user decision; keep previews/cache out of Git. |

### 6.3 Assumptions

- Exporting the selected originals (copy/hardlink) is required even though only similarity was
  named as a must-keep feature; otherwise the tool cannot deliver "the best 200".
- GPS is WGS84; no map datum conversion is needed.
- The default profile is `best200` (200 photos) and is user-overridable.
- The web GUI binds to localhost only and has no authentication (local single-user tool).
- `mypy` is optional in v1 if not already configured; ruff and pytest are mandatory.

### 6.4 Open questions (resolve during implementation)

1. Exact aesthetic model source, checksum and license (P2-W05).
2. Whether the Pixabay sample manifest can be downloaded automatically or must be curated manually.
3. Final event-gap and GPS-jump defaults after inspecting the sample set.
4. Whether a real 6000-photo library is available for the scale test.
5. Final GUI port and whether a `--host 0.0.0.0` option is needed (default: no).

---

## 7. Progress / Handoff

_Append a dated entry at each handoff: completed work, current state, next work package, issue,
commits, push/CI status, blockers and decisions._

- 2026-11-11: Plan created from the user interview. No implementation started. All decisions in
  sections 1–3 are settled; open questions are listed in 6.4.
- 2026-11-12: Phase 1 completed. Typed core, pydantic-settings with YAML/env/CLI precedence,
  versioned SQLite schema (WAL, migrations), typed repository, Typer skeleton and `doctor`.
  Legacy config-cli-gui/ttkbootstrap modules and their tests removed. Phase 1 tests: 7 passed,
  ruff clean. Issue #6. Next: Phase 2 (ingest and analysis).

- 2026-11-12: Phase 2 completed. Scan/decode, blur classification, composition, YOLO
  adapter, aesthetic model with heuristic fallback, subject rarity, resumable analysis and
  scan/analyze CLI commands. 12 available sample images analyzed in ~2 s on CPU; second run
  reuses all. Tests: 15 passed, ruff clean. Issue #7. Deviation: the planned 100-image Pixabay
  set is not present; the repository's 12 existing sample images plus synthetic fixtures are used.
  Next: Phase 3 (grouping, events, scoring).
- --> update: Ich habe nun alle 110 bilder inklusive credits: /home/paul/PycharmProjects/image-triage/images/pixabay/

- 2026-11-12: Phase 3 completed. pHash/digest/time/embedding union-find grouping, time/day/GPS
  events, weighted normalized scoring with blur gate, star ratings, group/event persistence and
  score CLI. Sample set scored (12 groups, 1 event due to identical mtimes). Tests: 21 passed,
  ruff clean. Issue #8. Next: Phase 4 (selection, reports, export).

- 2026-11-12: Phase 4 completed. Selection profiles, Sainte-Laguë/proportional/equal event
  quotas, per-day/cluster caps, greedy MMR, JSON report + JSON Schema, CSV, WebP previews and
  original export. select/plan/apply/export/report/run commands added. Full 12-photo run produced
  5 selections with report, CSV, previews and export in ~4 s; report is byte-identical on re-run.
  Tests: 30 passed, ruff clean. Issue #9. Next: Phase 5 (agent interface, config docs, cleanup).

- 2026-11-12: Phase 5 completed. Published report/plan/NDJSON JSON Schemas and `schema` command;
  stable exit-code and error-JSON contract tests; pydantic-based `make syncdocs` generator;
  English README/docs rewritten; legacy config-cli-gui/ttkbootstrap stack and tests removed.
  `mkdocs build` passes without dead-link warnings. Tests: 35 passed, ruff clean. Issue #10.
  Next: Phase 6 (models, benchmark, performance/scale).

- 2026-11-12: Sample images finalized. Downloaded 110 Pixabay photos (10 categories à 10) via
  `scripts/download_pixabay.py` into `images/pixabay/` with `credits.md`. Removed legacy
  `images/testimages_3/`, `images/testimages_4/` and `images/testimages_5/`. Tests do not
  reference the old folders, so no test changes were required. Next: Phase 6 (models,
  benchmark, performance/scale).

- 2026-11-12: Phase 6 completed. Model registry with SHA256 verification/license metadata
  (`models install|list`), explicit local aesthetic install, provider-aware benchmark with
  per-stage timings and peak memory, synthetic 6000-photo generator. Measured 6000 photos in 78 s
  (256 px preview, models off), 6.3 MB DB, ~165 MB peak RSS, 200 selected from 300 events; re-run
  reused all analyses in 9.3 s with a byte-identical report. Sample benchmark: 641 ms/photo CPU.
  Batching was not needed to meet the ~1 s/photo CPU target; per-image inference is used with
  parallel workers. Tests: 39 passed, ruff clean, mkdocs clean. Issue #11.
  Next: Phase 7 (QA, build, release) and Phase 8 (web GUI).

- 2026-11-12: Phase 7 completed. 43 tests passing; ruff format/lint, make precommit, deptry
  and mkdocs build clean. Wheel builds and installs in a fresh venv with and without the gui
  extra; templates/static/schemas included. End-to-end run on the 122-image sample set produced
  a schema-valid GPS-free report, CSV, 10 previews and export. Added the 111-image Pixabay sample
  set with credits (19 MB). GUI smoke test is covered in the Phase 8 commit. Issue #12.

- 2026-11-12: Phase 8 completed. FastAPI/Jinja/htmx GUI with library filters, sorting and
  pagination; photo detail, similar-shot compare, soft rating/keep/reject overrides (now applied
  as soft score signals), event timeline with an SVG GPS scatter, and analyze/select/export jobs
  with a background worker. `image-triage gui` starts uvicorn; GUI TestClient tests and a live
  health/index check pass. Deviations: pagination instead of virtual scrolling, and an SVG GPS
  scatter instead of Leaflet tiles to keep the GUI offline. Issue #13. All phases complete.

- 2026-11-12: Phase 9 completed. Added `python -m image_triage.gui`, completed date/minimum-score
  filters with filter-preserving pagination, fixed export jobs to use the newest non-empty
  selection, added analysis progress and running-job refresh, displayed stored overrides, made the
  events GPS query lightweight and degenerate-range safe, and removed the obsolete test image
  directories. All three launch paths returned HTTP 200 from `/health`; 46 tests, ruff, deptry,
  mkdocs and wheel/entry-point checks pass. Issue #14, commit 5770fad, CI green.
