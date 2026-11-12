Changelog
=========


(unreleased)
------------

Fix
~~~
- Commit cache.py. [Paul Magister]

Other
~~~~~
- Docs(plan): mark plan_v2 complete. [Paul Magister]

  Refs #15
- Docs(gui): document the scan, filter, selection and export workflow.
  [Paul Magister]

  - Cover the setup screen, stale-library banner, unified scan, multi-select
    filters, selection, both export scopes and the activity page.
  - Explain the ephemeral browser-local selection and the export target rule.
  - Note that the GUI scans on first start, so no CLI run is required.

  Refs #15
- Feat(gui): export selected or filtered photos from the library. [Paul
  Magister]

  - Add browser-local selection with checkboxes, select-all-filtered, clear
    and a visible selected count; state survives filtering and pagination.
  - Add GET /api/photo-ids returning all ids matching the current filters.
  - Add an export form with target directory, default timestamped path, and
    copy/hardlink/symlink mode.
  - Export either the ticked ids or every photo matching the current filters,
    across all pages, as a background job with progress and result.
  - Reject a target inside the library root, an empty selection and an empty
    filtered result with a clear message instead of an empty export.

  Refs #15
- Feat(gui): filter the library on every metadata field. [Paul Magister]

  - Parse query parameters as strings so empty optional fields no longer
    produce a raw FastAPI 422 document; invalid values are ignored.
  - Accept multi-value filters (rating, event, group, label, blur, flags,
    camera make/model) as SQL IN clauses.
  - Add score/sharpness/aesthetic/subject ranges and explicit sort direction.
  - Rebuild the filter form with multi-select controls, Apply/Reset and a
    visible result count.
  - Render a flat tile grid with score, rating, subject sharpness, bokeh,
    blur, group, event and capture time per photo.
  - Add /api/photo-ids returning all ids matching the filters across pages.

  Refs #15
- Feat(gui): scan a library in one step and flag stale state. [Paul
  Magister]

  - Add library_status comparing files on disk with analyzed photos, reporting
    new, changed and missing counts.
  - Add a unified scan job (analyze + group/events + score) so scores and
    ratings appear without a separate select run.
  - Auto-scan an empty library and show a stale banner with a scan button.
  - Reconcile missing files after a scan and report what was removed.
  - Suppress duplicate scans while a job is active; rename Jobs to Activity.

  Refs #15
- Feat(scoring): judge sharpness on the subject, not the background.
  [Paul Magister]

  Shallow depth of field was penalised like a defect: a sharp subject in
  front of a deliberately blurred background lost sharpness points and was
  sometimes classified as defocus blur.

  - Measure subject-region sharpness from detection boxes, with a saliency
    window as fallback, and add a separate bokeh signal for subject/background
    separation.
  - Decide blur on the subject region when boxes exist; a soft background no
    longer counts as defocus blur.
  - Gate only on real motion/defocus blur with sufficient confidence, so low
    global sharpness alone never halves the score.
  - Persist the new metrics (schema v2 migration) and expose them in the JSON
    report, CSV, photo detail and analysis signature.
  - Drop the now unused blur_threshold setting.

  Refs #15
- Docs(plan): mark Phase 1 complete. [Paul Magister]

  Refs #15
- Feat(gui): serve media reliably and select the library root. [Paul
  Magister]

  - Read settings from app.state per request so a library root chosen in the
    GUI applies to every route and background job.
  - Add /setup to pick the library folder, show the active root, image count
    and state DB path, and reject a change while a job is active.
  - Send cache headers and 404s for /media instead of failing on a missing
    file.
  - Skip VCS, virtualenv, coverage, cache and IDE directories by default in
    find_images so a project root never pollutes the library.

  Refs #15
- Fix(db): allow SQLite connections across FastAPI threads. [Paul
  Magister]

  Sync endpoints and their dependency teardown run in different threadpool
  workers, so closing a request-scoped connection raised
  sqlite3.ProgrammingError and broke /media tiles. Open connections with
  check_same_thread=False and document the one-connection-per-request rule.

  Adds plan_v2.md and the Phase 1 tracking issue reference.

  Refs #15
- Docs(plan): mark GUI hardening phase complete. [Paul Magister]

  Fixes #14
- Fix(gui): harden launcher, filters and job workflows. [Paul Magister]

  Add a module entry point for python -m image_triage.gui, complete date and minimum-score filters with pagination preservation, fix export jobs to use the latest selection, report analysis progress, show stored overrides, make the events scatter lightweight, and remove obsolete sample image directories.

  Refs #14
- Feat(gui): add local FastAPI photo triage web interface. [Paul
  Magister]

  Add a FastAPI/Jinja/htmx GUI with library filters, sorting and pagination,
  photo detail and comparison, soft rating/keep/reject overrides that influence
  scoring, an event timeline with GPS scatter, and background analyze/select/export
  jobs. Add the gui command, GUI tests and documentation.

  Refs #13
- Test(quality): finish QA, build and sample-set checks. [Paul Magister]

  Prune stale previews, record the Pixabay sample set with credits, tighten the
  dependency metadata for optional GUI/GPU extras, and document the completed
  quality/build/scale checks.

  Refs #12
- Feat(models): add model registry, benchmark and scale validation.
  [Paul Magister]

  Add a SHA256-verified model registry with YOLO install/list and explicit local
  aesthetic installation, provider-aware benchmark with per-stage timings and peak
  memory, and a deterministic synthetic 6000-photo generator. Document measured
  scale performance and add registry/benchmark tests.

  Refs #11
- Test(cli): ignore ONNX runtime warnings when parsing error JSON. [Paul
  Magister]

  Refs #10
- Feat(cli): publish JSON schemas, config docs and agent contract. [Paul
  Magister]

  Add report/plan/NDJSON JSON Schemas and a schema command, document stable exit
  codes and error JSON, replace the config-cli-gui documentation generator with a
  pydantic/Typer generator, rewrite the English docs and README, and remove the
  legacy stack. make syncdocs and mkdocs build pass cleanly.

  Refs #10
- Feat(selection): add profiles, quotas, reports and export. [Paul
  Magister]

  Add YAML selection profiles with Sainte-Laguë event quotas and per-day/cluster
  caps, deterministic greedy MMR, a versioned JSON report with JSON Schema, stable
  CSV, WebP previews, original export, and select/plan/apply/export/report/run CLI
  commands. Reports are byte-identical across repeated runs on the same DB state.

  Refs #9
- Feat(grouping): add similarity groups, events and scoring. [Paul
  Magister]

  Port pHash/digest/time/embedding union-find grouping with deterministic ids,
  add time/day/GPS event detection, weighted normalized scoring with a blur gate,
  star rating rules and the score CLI with JSON output. Persist groups, events and
  scores in SQLite.

  Refs #8
- Feat(analysis): add scan, metrics, YOLO and resumable analysis. [Paul
  Magister]

  Implement header scanning with EXIF time/GPS and BLAKE3 digests, robust preview
  decoding, tile-based sharpness with defocus/motion classification, composition
  metrics, YOLO detection/embedding inference, aesthetic scoring with a heuristic
  fallback, subject rarity, corpus calibration and resumable analysis. Add scan and
  analyze CLI commands with JSON and NDJSON output.

  Refs #7
- Feat(core): add typed settings, SQLite store and CLI foundation. [Paul
  Magister]

  Replace config-cli-gui and ttkbootstrap with Typer, pydantic-settings and
  FastAPI dependencies. Add domain models, nested settings with YAML/env/CLI
  precedence, a versioned WAL SQLite schema with forward migrations, a typed
  repository, stable exit codes/output renderers and a doctor command.
  Remove the legacy modules and tests they covered.

  Refs #6
- Add plan for the next big improvements. [Paul Magister]
- Ci(image-triage): clarify required Linux check in main workflow. [Paul
  Magister]

  Refs #5
- Ci(image-triage): Linux always-on, Win/macOS opt-in via --all. [Paul
  Magister]

  - flags job detects --all opt-in from commit subject / PR title / input
  - Linux test job (make test) always runs
  - Windows/macOS test jobs only run with build_all=true
  - Release DAG: quality gate blocks release/PyPI; build-linux always,
    build-windows/build-macos only opt-in
  - Separate build-*-yml workflows consolidated into release.yml
  - setup-environment uses cached setup-uv@v10.3.3

  Refs #5
- Add AGENTS.md. [Paul Magister]
- Use uv install for readthedocs. [Paul Magister]
- XMP-Ratings und Schlagworte werden standardmäßig nicht mehr in
  Fotodateien geschrieben. Sie lassen sich weiterhin explizit über
  Settings oder CLI aktivieren; ExifTool wird nur dann benötigt. Pro
  Foto-Unterordner wird bei normalen Läufen eine .image-triage.yaml mit
  Analysewerten angelegt. Bei unverändertem BLAKE3-Hash werden diese
  wiederverwendet, bei geändertem Foto neu berechnet. Gruppierung,
  Sterne und Auswahl entstehen weiterhin mit den aktuellen Fotos und
  Einstellungen. Der Cache wird auch bei aktiviertem XMP-Schreiben
  aktualisiert; --dry-run schreibt weiterhin keine Dateien. [Paul
  Magister]


0.0.2 (2026-10-06)
------------------
- Docs: Update HISTORY.md for release 0.0.2. [Paul Magister]
- Updated pyproject.toml to remove Deptry’s deprecated setting, which
  pointed at optional-dependency groups that this project doesn’t use.
  Added a targeted exception for lxml, an intentional dependency that
  Deptry otherwise flags as unused. [Paul Magister]
- Update config-cli-gui. [Paul Magister]
- Add tests that really work with the images and rate them. [Paul
  Magister]
- Fix generate_config_docs.py: provide real app name. [Paul Magister]
- Provide real test images. [Paul Magister]
- Fix docs generation, README.md and dependencies. [Paul Magister]
- Config_cli_gui.docs. [Paul Magister]


0.0.1 (2026-10-06)
------------------
- Docs: Update HISTORY.md for release 0.0.1. [Paul Magister]
- Initial commit with code for image triage. [Paul Magister]
- ✅ Project renamed from template. [github-actions[bot]]
- Initial commit. [Paul Magister]


