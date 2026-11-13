# Image Triage v2 - GUI Workflow and Quality Plan

**Status:** `[ ]` planned
**Created:** 2026-11-12
**Supersedes:** the GUI-related parts of [`plan_v1_implementation`](plan_v1_implementation.md) (Phases 8-9). `plan_v1_implementation` remains the historical record.
**Target:** a local-first GUI workflow that can scan a selected photo library, explain and filter its metadata, curate a temporary selection, and export selected or currently filtered photos without manual CLI steps.

---

## 1. Objective and Desired Outcome

### Objective

Repair the current GUI failures and turn the GUI into the primary workflow for a local photo library:

1. every image tile and media view loads reliably;
2. an empty or stale library is detected and repaired through one visible scan action;
3. the library can be filtered by all relevant metadata, including multi-value filters such as ratings 4 and 5;
4. the result is a flat, responsive tile view that updates when filters or sorting change;
5. images can be selected with checkboxes, including "select all filtered" and opt-out, without a server-side shortlist;
6. selected or currently filtered photos can be exported from the library page to a user-chosen target directory;
7. sharpness scoring respects intentional subject/background separation instead of treating shallow depth of field as a defect.

### Desired outcome

- `python -m image_triage.gui`, `image-triage gui` and `image-triage-gui` all start the same server.
- On first use the user selects the photo library root in the GUI. Tool directories such as `.venv`, `.git` and `htmlcov` are never scanned.
- If the selected library has no state, the GUI starts a scan automatically. If files were added, changed or removed, the GUI shows a clear stale-library banner and a scan button.
- After a scan, every tile shows score, rating, sharpness, blur, composition, aesthetic, subject, event, group and capture metadata.
- The filter form supports multi-select values and returns the matching tiles on Apply; empty optional fields never produce a 422 JSON page.
- "Select all filtered" selects every photo matching the current filter across all pages; individual checkboxes can opt out. The selection is browser-local and deliberately ephemeral.
- "Export selected" exports exactly the checked photos. "Export all" exports every photo in the current filtered view, not only the current page.
- Export asks for a target path, defaults to a timestamped directory such as `export_2026-11-12_18-30`, and runs as a background job with visible progress/result.
- Intentional bokeh is not penalised as blur. A sharp subject with a soft background can score well; only actual motion/defocus blur is gated.

### Success criteria

- Media requests work under the live ASGI server and under concurrent requests.
- A fresh library auto-scans; a stale library shows a banner and scans on request.
- Applying filters updates the tile grid; pagination and sorting preserve filters.
- Rating 4 and 5 can be selected together.
- Selected and filtered exports produce the expected files and never modify source images.
- The sharpness/bokeh change is covered by synthetic regression tests.
- All existing tests, Ruff, deptry, mkdocs, wheel/entry-point checks and CI remain green.

---

## 2. Scope, Constraints and Explicit Non-Goals

### 2.1 In scope

- SQLite connection handling for FastAPI's threadpool.
- Media serving and image error handling.
- GUI library-root selection and safe filesystem scanning.
- Unified scan/analyze/group/score workflow and stale-library detection.
- Multi-metadata filter model, repository queries and tile UI.
- Client-side ephemeral selection, select-all-filtered, clear and export controls.
- Selected/filtered export jobs with a user-specified output directory.
- Subject-aware sharpness, bokeh-aware scoring and blur gating.
- Regression tests, documentation and end-to-end verification.

### 2.2 Constraints

- Keep the local-only, no-cloud, no-telemetry design.
- Keep the server-rendered FastAPI + Jinja + htmx approach; no Node build step or SPA rewrite.
- Do not modify or delete original image files. Export only copies/hardlinks/symlinks.
- Preserve CLI determinism and the existing JSON report schema; metric changes must be versioned.
- Use `uv`, pytest, Ruff and the existing Make targets.
- The GUI remains a single-user localhost tool without authentication.

### 2.3 Explicit non-goals

- No server-side shortlist, user accounts or multi-user state.
- No persistent selection database; selection is intentionally browser-local/ephemeral.
- No image editing, RAW conversion, panorama/HDR merging, face recognition or video.
- No new object detector or aesthetic model.
- No detection/composition overlays in this iteration.
- No XMP writing.
- No HEIC/HEIF or RAW full-decode support.
- No cloud upload or online map tiles.
- No automatic hard force-include/exclude overrides.
- No rewrite of the CLI command surface.

### 2.4 Deferred / blocked (`[~]`)

- `[~]` Persistent, shareable selection lists.
- `[~]` Server-side multi-user shortlists.
- `[~]` Detection/composition overlays and richer visual comparison.
- `[~]` Advanced map/timeline interactions.
- `[~]` RAW/HEIC and video thumbnails.
- `[~]` Fine-tuning the aesthetic model on user ratings.

---

## 3. Current Defects and Root Causes

These are the concrete defects observed in the current GUI and how the plan addresses them.

| Defect | Root cause | Planned resolution |
|---|---|---|
| Broken image tiles and `/media/...` 500 errors | `sqlite3` connections are created in one threadpool thread and used/closed in another; default `check_same_thread=True` | Open per-request connections with `check_same_thread=False`; never share one connection across requests or background jobs |
| Scores and ratings stay 0 after Analyze | GUI Analyze job only calls `analyze_library`; grouping/events/scoring are not run | Add a unified `scan` job that runs analyze, grouping/events and scoring |
| "Apply" returns a FastAPI 422 JSON document | Empty optional form fields are submitted as `event_id=`, `date_from=`, etc.; route expects `int`/`date` | Parse all filter values as strings and tolerate empty values; omit empty fields client-side as a fallback; add a browser-friendly validation/error response |
| `Top N 200` selects only 12 photos | `max_per_day=5`; 108 of the sample photos share the same capture day | Keep quotas but expose them in the GUI and explain "12 of 200 selected because of caps"; make day/cluster/group caps configurable |
| Library contains `.venv`, `htmlcov` and tool images | `input.root` is `.` and `find_images` scans the whole repository | Add safe default excludes, hide tool directories, show the active root, and let the user select the library folder at GUI startup |
| Blur is reported as `none (0.00)` everywhere | The Pixabay samples are mostly sharp; only a few images are classified as blur. The score is corpus-relative and the blur gate uses normalized sharpness, so shallow depth of field can be penalised | Add subject/saliency-aware sharpness, treat intentional bokeh as a positive/neutral signal, and gate only on actual motion/defocus blur |
| Selection cannot be carried across filtered pages | No selection mechanism exists | Add browser-local checkbox state, select-all-filtered, clear, and export-selected by IDs |
| Export requires CLI knowledge | No export control on the library page | Add an export form with target path, mode, scope and background job status |

---

## 4. Architecture and Decisions

### 4.1 Settled decisions

| Area | Decision | Rationale |
|---|---|---|
| SQLite access | Per-request connection, `check_same_thread=False`, no cross-thread connection reuse | FastAPI runs sync endpoints in a threadpool; SQLite otherwise rejects cross-thread use |
| Background jobs | Each job opens its own repository connection and closes it in `finally` | Avoids sharing a connection with request handlers |
| Library root | GUI setup screen when no valid root is selected; root change only when no job is active | User requested folder selection at GUI start; changing root mid-job would make results ambiguous |
| Scan safety | Skip hidden/tool directories by default: `.git`, `.venv`, `venv`, `htmlcov`, `__pycache__`, caches, `node_modules`, `.idea`, `.vscode`, `dist`, `build`, `.image-triage`, `selected`, `previews` | Prevents repository/tool images from polluting the library |
| Freshness detection | Compare filesystem paths against DB paths; use file mtime vs `analyzed_at` for changed files; expose new/missing/changed counts | No schema migration required; a manual full scan still recomputes digests |
| Unified scan | One `scan` job = analyze + group/events + score; optional separate `select` job | Matches the user's workflow: scan first, then filter/curate |
| Auto-scan | Empty library auto-starts a scan; stale library shows a banner and scan button | User chose "auto when empty, suggest when stale" |
| Filters | Multi-value filters encoded as comma-separated query values, parsed server-side into lists; repository uses `IN` clauses | Robust against empty fields and works with plain HTML forms |
| Selection | Browser-local `localStorage` state; checkboxes per tile; "select all filtered" fetches all matching IDs; selection survives filtering/pagination | User explicitly wanted ephemeral checkboxes and opt-out, not a server-side shortlist |
| Export scope | `selected` (checkbox IDs) and `filtered` (all photos matching current filters, across all pages) | User clarified that "all" means the current filtered view |
| Export target | User-supplied path; default `export_YYYY-MM-DD_HH-MM` under the server's working directory; reject output inside the library root | Prevents accidental rescanning of exported copies |
| Scoring | Subject/saliency-aware sharpness; bokeh as positive/neutral; blur gate only for motion/defocus with confidence | Avoids punishing intentional shallow depth of field |
| Versioning | Bump `METRIC_VERSION` / `SCORING_VERSION` and analysis signature so existing photos are recomputed once | Required to make the new sharpness score effective |

### 4.2 GUI request/settings model

- `create_app(settings)` stores the initial settings on `app.state.settings`.
- Routes and the repository dependency read `request.app.state.settings`, not a captured `settings` closure.
- A setup route validates a directory and replaces `app.state.settings` with a copy whose `input.root` points at the selected directory.
- The state database remains `<root>/.image-triage/triage.db`; switching roots therefore switches state databases without deleting old data.
- Background jobs capture a settings snapshot when started; root changes are rejected while a job is pending/running.

### 4.3 Scan status model

The GUI computes a lightweight status before rendering the library:

- `files`: number of supported image files under the selected root after exclusions.
- `stored`: number of photo rows in the current database.
- `new`: files not present in the database.
- `missing`: database paths no longer present on disk.
- `changed`: common paths whose file mtime is newer than `analyzed_at`.
- `empty`: `stored == 0` and `files > 0`.
- `current`: `new == missing == changed == 0` and `stored > 0`.
- `stale`: any of `new`, `missing`, `changed` is non-zero.

A manual "full scan" always recomputes digests and reuses unchanged analyses through the existing signature cache.

### 4.4 Selection and export flow

1. The library page renders a checkbox on every tile.
2. JavaScript loads selection IDs from `localStorage`, applies them to visible checkboxes and shows a selected count.
3. Changing a checkbox updates `localStorage`.
4. "Select all filtered" calls `GET /api/photo-ids?<current filters>` and stores the returned IDs.
5. "Clear selection" empties the stored IDs.
6. Export form submits:
   - `scope=selected` plus hidden `photo_ids`, or
   - `scope=filtered` plus the current filter query string;
   - `output` path and `mode`.
7. The server starts an export job, stores it in the existing `jobs` table and reports progress/result.
8. Export selected with no selection, or filtered export with no matches, fails with a clear message rather than an empty export.

### 4.5 Filter model

The library filter object contains:

- free-text `q` over path;
- `rating` (multi-select 1-5);
- `event_id` (multi-select);
- `group_id` (multi-select);
- `label` (multi-select detection labels);
- `blur` (none/defocus/motion/unknown);
- `flags` (blurry, etc.);
- `camera_make`, `camera_model` (multi-select where available);
- `date_from`, `date_to`;
- `score_min`, `score_max`;
- `sharpness_min`, `aesthetic_min`, `subject_min`;
- `sort` and `order` (score, rating, sharpness, taken, path, event, group);
- `page`.

Empty values are ignored. Invalid values produce a user-friendly message, not a raw 422 JSON document.

### 4.6 Sharpness and bokeh model

- Compute a global high-percentile tile sharpness as today.
- Additionally compute subject-region sharpness from YOLO detection boxes when available; fall back to a saliency/high-gradient ROI when no detection exists.
- Combine global and subject sharpness so a sharp subject in a shallow-depth-of-field image is not dominated by a soft background.
- Add a bokeh signal based on background softness versus subject sharpness. Bokeh is neutral-to-positive, not a blur defect.
- Blur gate:
  - motion blur with sufficient confidence -> gate;
  - defocus blur with sufficient confidence -> gate;
  - low global sharpness alone -> do not gate;
  - `blur_kind == none` -> no blur penalty.
- Persist the new components in metrics/report and expose them in the photo detail and tile tooltip.

---

## 5. Phases and Work Packages

Status markers: `[ ]` pending, `[-]` in progress, `[x]` completed, `[~]` deferred/blocked.

### Phase 1 - Runtime Stabilisation and Library Root

**Status:** `[x]` completed (commits `4352109`, `a033fc8`; issue #15; CI run 43268588370 green)

**Objective:** make the GUI reliably serve images and operate on an explicitly selected library root.

- [x] P1-W01: Fix SQLite thread affinity by opening per-request connections with `check_same_thread=False`; keep one connection per request and one per background job. Add a regression test that uses a connection from a different thread than the one that created it.
- [x] P1-W02: Verify `/media/{id}` under the live ASGI server and concurrent requests; handle missing files and invalid IDs with 404 responses. Add cache headers for previews.
- [x] P1-W03: Add safe scan exclusions for hidden and tool directories. Extend `find_images`/scanning so repository, virtualenv, coverage, cache and IDE directories are skipped by default.
- [x] P1-W04: Add a GUI setup screen with a server-side folder-path form. Show the active root, file count and state-DB path. Validate the directory and update `app.state.settings` without deleting existing state.
- [x] P1-W05: Make route settings dynamic (`request.app.state.settings`) and reject root changes while a scan/select/export job is active.
- [x] P1-W06: Add tests for media, setup/root switching, exclusions and the no-active-job guard.

**Acceptance criteria**

- `/media/{id}` returns 200 under the live server and concurrent requests.
- The GUI never scans `.venv`, `.git`, `htmlcov`, caches or IDE directories by default.
- The user can select a library folder at startup and see the active root and DB path.
- No request shares a SQLite connection across threads.

**Phase gate:** Image serving and library-root selection work before workflow changes begin.

### Phase 2 - Sharpness, Bokeh and Blur Gate

**Status:** `[x]` completed (commits `5c33779`; CI green)

**Objective:** make the quality score respect intentional subject/background separation and stop misclassifying shallow depth of field as blur.

- [x] P2-W01: Add subject/saliency-aware sharpness computation using detection boxes and a saliency fallback.
- [x] P2-W02: Add a bokeh signal from background softness versus subject sharpness; treat it as neutral/positive.
- [x] P2-W03: Change the blur gate so only motion/defocus blur with sufficient confidence is penalised; low global sharpness alone no longer halves the score.
- [x] P2-W04: Update `Metrics`, scoring breakdown, report and GUI labels to expose sharpness, subject sharpness, bokeh and blur confidence.
- [x] P2-W05: Bump `METRIC_VERSION`, `SCORING_VERSION` and the analysis signature so existing libraries are recomputed once on the next scan.
- [x] P2-W06: Add synthetic regression tests for sharp subject/blurred background, motion blur, defocus blur and a fully sharp control image.

**Acceptance criteria**

- A sharp subject with a deliberately blurred background scores better than a uniformly soft image with the same subject.
- A shallow-depth-of-field image is not marked blurry solely because background tiles are soft.
- Actual motion/defocus blur still receives the blur gate and a low rating.
- The new metric values are persisted and visible in the report and GUI.

**Phase gate:** The scoring change is deterministic and covered by tests before the scan workflow is rebuilt.

### Phase 3 - Unified Scan and Library Freshness

**Status:** `[x]` completed (commit `a351ab8`; CI green)


**Objective:** make the GUI scan the library in one understandable action and make empty/stale state visible.

- [x] P3-W01: Add a library-status function returning files, stored, new, missing, changed, empty, current and stale counts.
- [x] P3-W02: Add a `scan` job that runs analyze, grouping/events and scoring in one background job with progress reporting.
- [x] P3-W03: Add safe reconciliation: remove DB rows for paths missing after a completed scan, and report what was removed.
- [x] P3-W04: Auto-start a scan when the library is empty; show a stale-library banner with new/changed/missing counts and a "Scan library" button when stale.
- [x] P3-W05: Show scan progress on the library page or a dedicated activity page; prevent duplicate concurrent scans with a job guard.
- [x] P3-W06: Rename the confusing Jobs page to Activity and separate scan, select and export history; keep manual controls but make the primary workflow scan-first.
- [x] P3-W07: Add tests for empty auto-scan, stale banner, current library, missing-file reconciliation and scan job completion.

**Acceptance criteria**

- Opening the GUI with an empty library starts a scan automatically.
- Opening the GUI with new/changed/missing files shows a clear banner and scan action.
- After a scan, scores and ratings are populated without running a separate select job.
- A second scan reuses unchanged analyses and reports reused counts.
- Duplicate scan requests do not start parallel scans.

**Phase gate:** The GUI can take a library from empty to scored/filterable in one workflow.

### Phase 4 - Library Filters, Sorting and Flat Tile View

**Status:** `[x]` completed (commit `cb5f1e9`; CI green)


**Objective:** provide a flat, filterable tile view with all relevant metadata and multi-select filters.

- [x] P4-W01: Define a typed filter object covering rating, event, group, label, blur, flags, camera, date range, score/sharpness/aesthetic/subject ranges, search, sort and order.
- [x] P4-W02: Extend repository filtering with `IN` clauses for multi-value filters and add the missing sort options; keep count/list queries consistent.
- [x] P4-W03: Rebuild the filter form with multi-select controls, Apply/Reset, active-filter chips and a visible result count.
- [x] P4-W04: Render a flat responsive tile grid with image, path, rating, score, sharpness, blur, composition, aesthetic, subject, event, group, capture time, dimensions and flags.
- [x] P4-W05: Make empty optional query values safe server-side and client-side; ensure pagination and sort links preserve all active filters.
- [x] P4-W06: Add tests for multi-select rating (4 and 5), combined filters, empty fields, sorting and pagination.

**Acceptance criteria**

- Selecting rating 4 and 5 together returns both sets.
- Applying filters updates the tile grid and shows the number of matching photos.
- Empty `event_id`, `date_from`, `date_to` and `min_score` fields do not produce a 422 JSON response.
- Pagination and sorting preserve every active filter.
- Each tile shows the metadata needed to judge a photo without opening it.

**Phase gate:** The library is usable as the main browsing and curation surface.

### Phase 5 - Selection, Export and Job UX

**Status:** `[x]` completed (commit `87521b3`; CI green)


**Objective:** let the user curate a temporary selection and export it or the current filtered view.

- [x] P5-W01: Add browser-local selection state (`localStorage`), a checkbox per tile, selected count, clear action and stale-ID handling.
- [x] P5-W02: Add `GET /api/photo-ids` returning all IDs matching the current filters for "select all filtered".
- [x] P5-W03: Add an export toolbar/form with target path, default timestamped path, copy/hardlink/symlink mode, and scope `selected` or `filtered`.
- [x] P5-W04: Implement selected export by IDs and filtered export by re-running the filter query across all pages; validate that the output directory is not inside the library root.
- [x] P5-W05: Run exports as background jobs with progress/result and show status on the library or activity page.
- [x] P5-W06: Handle empty selection, no matching filtered photos, invalid output paths and missing source files with clear messages.
- [x] P5-W07: Add tests for the photo-ids API, selected export, filtered export across pages, default output naming, output validation and job completion.

**Acceptance criteria**

- Checkboxes survive filtering and pagination within the browser session.
- "Select all filtered" selects every matching photo across all pages; individual opt-out works.
- "Export selected" exports exactly the checked photos.
- "Export all" exports every photo in the current filtered view, not only the current page.
- Export uses the requested target directory and never modifies source files.
- Export failures are visible and actionable.

**Phase gate:** The GUI supports the full curate-and-export workflow without CLI commands.

### Phase 6 - Documentation, End-to-End Verification and Release

**Status:** `[x]` completed (commits `3c9968a`; CI green)


**Objective:** document the new workflow and prove it works on real sample data.

- [x] P6-W01: Update `../../usage/gui.md` with the setup screen, scan workflow, filters, selection, export and activity page.
- [x] P6-W02: Update `../../getting-started/install.md` and any generated README content through `make syncdocs` where required.
- [x] P6-W03: Run `make fmt`, `make lint`, `make test`, `make deptry`, `mkdocs build`, wheel build and entry-point checks.
- [x] P6-W04: Perform a manual end-to-end walkthrough on `../../../images/pixabay`: empty scan, stale scan, multi-select filters, select-all/opt-out, selected export and filtered export.
- [x] P6-W05: Verify bokeh handling with the provided lion image and synthetic blur fixtures.
- [x] P6-W06: Commit, push, open/close the tracking issue and confirm CI is green.

**Acceptance criteria**

- Documentation matches the actual GUI workflow and commands.
- All automated checks pass.
- The manual walkthrough covers every new workflow.
- The tracking issue is closed with the verified commit and CI status.

**Final phase gate:** The GUI workflow is complete only when the code, tests, documentation and manual walkthrough agree.

---

## 6. Acceptance Criteria and Verification Expectations

### 6.1 Global acceptance criteria

1. All three GUI launch paths start the same application.
2. Media tiles load reliably under the live server and concurrent requests.
3. Empty libraries auto-scan; stale libraries show a visible scan prompt.
4. Scanning updates analysis, grouping, events, scores and ratings in one job.
5. Filters support multi-value metadata selections and preserve state across pagination.
6. The library root is selected in the GUI and tool directories are excluded.
7. Selection and export work from the library page without CLI commands.
8. Selected and filtered exports produce the correct files in the chosen directory.
9. Bokeh-aware sharpness passes synthetic regression tests.
10. Tests, Ruff, deptry, mkdocs, wheel build and CI pass.

### 6.2 Verification matrix

- **Runtime:** live `uvicorn`/TestClient media requests, concurrent requests, setup/root switching.
- **Scan:** empty auto-scan, stale banner, current state, missing-file reconciliation, duplicate-job guard.
- **Filters:** rating 4+5, event/group/label multi-select, date/score ranges, empty fields, sorting, pagination.
- **Selection/export:** checkbox persistence, select-all-filtered, opt-out, selected export, filtered export across pages, default path, invalid output.
- **Scoring:** synthetic sharp subject/blurred background, motion blur, defocus blur, sharp control.
- **Quality gates:** `make fmt`, `make lint`, `make test`, `make deptry`, `mkdocs build`, wheel/entry-point checks.

### 6.3 Test data

- Existing Pixabay sample set under `../../../images/pixabay`.
- Synthetic images for bokeh, motion blur, defocus blur and sharp control.
- Temporary libraries for empty, stale, missing and changed-file states.
- No network access in tests.

---

## 7. Dependencies, Risks and Open Questions

### 7.1 Dependencies

- Existing FastAPI, Jinja, htmx, Pillow, OpenCV, NumPy and SQLite stack.
- No new runtime dependency is planned.
- Existing YOLO model remains optional; bokeh fallback must work without detections.

### 7.2 Risks and mitigations

| Risk | Mitigation |
|---|---|
| `check_same_thread=False` allows unsafe concurrent use of one connection | One connection per request/job; never share a connection; add a cross-thread test |
| SQLite write contention between scan/export jobs and page requests | WAL mode, busy timeout and a single scan/export job guard |
| Auto-scan starts multiple times from multiple tabs | Check for an active scan job before starting; show existing progress |
| Root change while a job is running | Reject root changes while a job is pending/running |
| `mtime`-based stale detection misses same-mtime changes | Manual/full scan recomputes digests; status is advisory, not a guarantee |
| Browser-local selection is lost when storage is cleared | Document this as intentional; export before clearing or use a persistent list later |
| Exporting a very large filtered library blocks the request | Run export as a background job with progress and result |
| Exporting into the library root causes rescan loops | Reject output paths inside the library root |
| Bokeh heuristics are subjective | Keep bokeh neutral/positive, expose components and do not let it dominate the score |
| Existing libraries need recomputation after metric bump | The scan reuses unchanged analyses but recomputes when the metric/signature changes; document the one-time cost |

### 7.3 Assumptions

- The user will select a real photo library root; the repository root is not a valid default photo library.
- The Pixabay sample set is sufficient for most tests; the lion image is used for a manual bokeh check.
- The GUI remains single-user and localhost-only.
- "Export all" means the current filtered view, as clarified by the user.
- Selection is intentionally ephemeral and browser-local, as clarified by the user.

### 7.4 Open questions

1. Should the GUI persist the last selected library root across server restarts, or ask again on each start?
2. Should "select all filtered" replace the current selection or add to it? Current plan: replace, because the user wants to opt out after filtering.
3. Should export reject output inside the library root, or only warn? Current plan: reject.
4. Should the old Jobs page remain as a read-only activity log, or be replaced by a simpler scan/status page? Current plan: rename to Activity and keep history.
5. Is a full deep scan (recompute all digests) needed on every stale check, or is mtime enough? Current plan: mtime for status, full scan on demand.

---

## 8. Progress / Handoff

_Append a dated entry at each handoff: completed work, current state, next work package, issue, commits, push/CI status, blockers and decisions._

- 2026-11-12: Plan v2 created from the GUI defect report and user workflow decisions. No implementation started.
- 2026-11-12 (Phase 1 complete): Fixed SQLite thread affinity (`check_same_thread=False`, per-request connections), media cache headers and 404s, safe scan exclusions for tool/cache/VCS directories, and the `/setup` library-root screen with a no-active-job guard. Tests: 51 passed, Ruff clean. Commits `4352109` and `a033fc8` pushed; CI run 43268588370 green. Issue #15 open (reused/created for the phase, to be closed with the phase-close commit). Next: Phase 2 (sharpness, bokeh and blur gate).
- 2026-11-12 (Phases 2-6 complete): Subject/saliency-aware sharpness with a bokeh signal, blur gate limited to real motion/defocus blur, schema v2 migration, unified scan job with freshness detection and auto-scan, multi-select metadata filters with sorting and a flat tile view, ephemeral browser selection with select-all-filtered, selected and filtered export to a user-chosen directory, docs and end-to-end verification.

  Verification: 68 tests pass, Ruff and deptry clean, `mkdocs build` succeeds, wheel installs with all three entry points. End-to-end walkthrough on `../../../images/pixabay` (110 photos): auto-scan, no false stale banner, rating 4+3 = 106 of 110, opt-out selection, 105-file selected export, 47-file filtered export matching the 47 rating-4 photos, both guards returning 400, blank filters returning 200, and add/delete reconciliation removing exactly the deleted file. Bokeh on the real lion image: 0.849 whole-frame, 0.588 subject box, `none` blur; the same frame blurred scores bokeh 0.0 and `defocus`.

  Commits `4352109`, `a033fc8`, `ec1b63c`, `5c33779`, `a351ab8`, `cb5f1e9`, `87521b3`, `3c9968a`; all pushed and CI green. Issue #15 closed. Next: none; v2 plan complete.
