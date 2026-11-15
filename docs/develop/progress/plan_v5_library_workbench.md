# Image Triage v5 - Library Workbench and Curation Workflow

**Status:** `[ ]` planned
**Created:** 2026-11-15
**Supersedes:** the GUI workflow parts of v2-v4. The v3/v4 data model, multi-root scanning and central appdata layout remain authoritative.
**Target:** turn the GUI into a workflow-centric curation workbench with a left filter sidebar, a persistent browser-local selection, bulk accepted/rejected decisions, group-aware review, best-N selection, a non-intrusive copy-only export drawer, and a useful Events timeline.

## 1. Objective and desired outcome

The current GUI is tool-centric (Library, Events, Activity, Settings) and exposes implementation details instead of the user's curation workflow. Version 5 restructures the GUI around one outcome:

> Select the right photos from a filtered scope, compare similar shots, persist decisions, and export the result without losing work.

Desired outcome:

1. A single Library workbench with a left sidebar for folder navigation and filters.
2. A browser-local selection that survives filtering, pagination, folder changes, root changes and reloads.
3. Explicit bulk actions: select all filtered, de-select all filtered, clear with confirmation, accept selected, reject selected.
4. A selection review panel that shows all selected photos across roots/folders, scoped by root/folder.
5. Persisted accepted/rejected status with badges, filters and bulk actions.
6. A quick "Best N" control with an editable N and configurable criteria/weights in Settings.
7. Group-aware review: filter similar shots by group size and compare/select the best variant.
8. A copy-only export drawer with a user-friendly default target and accepted/filtered/selected scopes.
9. A useful Events timeline instead of a developer-oriented table.
10. A curated Settings page with an Advanced section, not a 1:1 copy of `config.md`.

## 2. Scope, constraints and explicit non-goals

### 2.1 In scope

- GUI information architecture and layout.
- Filter model: metric ranges, group size, status, presets, filter visibility.
- Browser-local selection: add/remove/clear semantics, review panel, bulk actions.
- Persisted accepted/rejected status using the existing `overrides.keep` signal.
- Best-N selection reusing `selection/select.py`.
- Similar-shot/group review and compare enhancements.
- Copy-only export drawer and default export path.
- Events timeline and read-only job history.
- Settings reorganization and filter visibility.
- Tests, documentation, `make syncdocs`, CI.

### 2.2 Constraints

- Local-first, single-user, no authentication.
- Originals are never modified or deleted.
- Keep FastAPI + Jinja + htmx; no SPA rewrite, no Node build step.
- Selection stays in `localStorage`; no server-side shortlist.
- Accepted/rejected stays content-level in SQLite.
- `make fmt`, `make lint`, `make test`, `make syncdocs`, `mkdocs build` must pass.
- `config.yaml` and `docs/usage/config.md` remain generated; never edit them directly.

### 2.3 Explicit non-goals

- No server-side shortlist or multi-user selection.
- No named selection sets in this iteration.
- No visual clustering of similar photos in the grid.
- No RAW re-rendering, cloud, auto-delete or XMP writing.
- No full 1:1 parity with every `config.md` setting.
- No keyboard-shortcut system in this iteration.

## 3. Architecture and decisions

### 3.1 Settled product decisions

| Area | Decision |
|---|---|
| Selection lifetime | Browser-local `localStorage`, set of **location ids**. |
| Selection unit | Location. |
| Select all filtered | **Add** to the current selection (union). |
| De-select all filtered | Remove only the currently filtered location ids. |
| Clear selection | Clear all, with a confirmation dialog. |
| Selected-only view | Client-side **selection review panel** with root/folder scope. |
| Accepted/rejected | Content-level status in SQLite; reuse `overrides.keep` (`1` accepted, `0` rejected, `NULL` undecided). |
| Best-N | Quick control with editable N; criteria/weights in Settings; reuse `select_photos`; return final location ids. |
| Best-of-group | Separate quick action; best photo per similarity group in scope. |
| Similar shots | Group-size filter (`2+`, `3+`, `5+`) plus per-group Compare. |
| Filter UI | Left sidebar with **Folders** and **Filters** tabs. |
| Filter controls | Dual-thumb range sliders plus numeric readouts; checkboxes for rating/status/group size. |
| Presets | Good, Blurry, Low quality, Similar, Accepted, Rejected, Hide rejected. |
| Export | Copy-only in the GUI; drawer/dialog. |
| Default export target | `~/Bilder/image-triage/export_YYYY-MM-DD_HH-MM`, then `~/Images/...`, then `~/image-triage/...`. |
| Export scopes | Selected, filtered, accepted. |
| Events | Keep and turn into a timeline. |
| Activity/Jobs | Read-only job history; no manual start. Main navigation: Library, Events, Settings. |
| Default view | Folder view; flat tiles second. |
| Settings | Curated sections plus Advanced. |

### 3.2 Selection model

- Storage key `image-triage:selected`, value: array of location ids.
- On load, apply selection to checkboxes and show the count.
- "Select all filtered": `GET /api/photo-ids?<query>` then union.
- "De-select all filtered": same endpoint then remove.
- "Clear": confirm, then empty.
- The review panel fetches `POST /api/photos` with all selected ids and renders thumbnails, scoped by root/folder.
- Stale ids are pruned when the panel fetches summaries.

### 3.3 Accepted/rejected

- `overrides.keep = 1` accepted, `0` rejected, `NULL` undecided.
- Add `Photo.keep`, select it in `_CONTENT_SELECT` / `_LOCATION_SELECT`.
- Fix `Repository.set_override()` partial updates.
- Add `Repository.set_status(photo_ids, status)` preserving `rating`.
- Add `status` and `hide_rejected` filters.
- Status badges on tiles and photo detail.
- Bulk actions for selected and filtered scopes.

### 3.4 Filter model

- New ranges: sharpness, bokeh, blur, composition, aesthetic, subject, exposure (min/max).
- New: `group_size_min/max`, `status`, `hide_rejected`.
- New sort keys: blur, group, event.
- Sidebar presets and active filter chips.
- Filter visibility from `gui.filters.visible`.

### 3.5 Best-N and groups

- `POST /api/select-best` with query, n, add/replace, existing ids, include-rejected.
- Server returns final ids and summary.
- `POST /api/select-group-best` returns best location per group.
- `GET /compare/group/{group_id}` and compare actions.
- Large sets run as background jobs.

### 3.6 Export

- Drawer with selected/filtered/accepted scopes.
- Copy-only; remove mode selector from GUI.
- Default path helper in `appdata.default_export_root()`.
- Background job with status.

### 3.7 Events and Jobs

- Events timeline with event cards and representative thumbnails.
- Jobs read-only; header job status; no manual start.
- Main navigation: Library, Events, Settings.

## 4. Phases and work packages

### Phase 0 - Bug fixes and quick wins

**Status:** `[x]`

- [x] P0-W01: Fix `parse_photo_query` so `event_id`/`group_id` stay lists; remove them from `NUMBER_KEYS`; normalize multi-value keys.
- [x] P0-W02: Keep the folder tree complete by excluding `root` from `tree_filters`.
- [x] P0-W03: `group_options()` returns only groups with `member_count >= 2`.
- [x] P0-W04: Change the default view to `folders`; update generated config/docs/tests.
- [x] P0-W05: Selection semantics: select all filtered adds; add de-select all filtered; clear confirms.
- [x] P0-W06: Fix `set_override()` partial updates so setting `keep` does not clear `rating`.
- [x] P0-W07: Update docs for the fixed behavior.

**Acceptance criteria**

- Event and group filters return 200.
- Folder navigation never hides the other roots.
- Groups with one photo are not offered.
- The library opens in folder view.
- Select-all adds; de-select-filtered removes; clear confirms.
- Setting accepted/rejected preserves an existing rating override.

**Phase gate:** no 500s in the main filter flows; selection semantics match the agreed model.

### Phase 1 - Filter sidebar and filter model

**Status:** `[-]`

- [x] P1-W01: Add `gui.filters` settings (visible groups, hide-rejected default).
- [x] P1-W02: Extend the query parser and repository with metric min/max ranges.
- [x] P1-W03: Add `group_size_min/max` and blur/group sorting.
- [x] P1-W04: Build the left sidebar with Folders and Filters tabs.
- [x] P1-W05: Build filter groups with dual-thumb range sliders and numeric readouts.
- [x] P1-W06: Add presets and active filter chips.
- [x] P1-W07: Add Settings controls for filter visibility and update docs.

**Acceptance criteria**

- The filter UI is a left sidebar, not a top form.
- All agreed metrics have min/max controls.
- Presets apply within the current root/folder scope.
- Active filters are visible and individually removable.
- The folder tree remains complete and usable.
- Filter visibility is configurable in Settings.

**Phase gate:** the filter sidebar is usable and the old top filter form is gone.

### Phase 2 - Selection review and accepted/rejected

**Status:** `[ ]`

- [ ] P2-W01: Add `Photo.keep` to the model and SELECTs; render accepted/rejected badges.
- [ ] P2-W02: Add `POST /api/photos` returning lightweight summaries for location ids; prune missing ids.
- [ ] P2-W03: Add `POST /api/status` for selected ids or a filter query; support accepted/rejected/none.
- [ ] P2-W04: Add `status` and `hide_rejected` filters.
- [ ] P2-W05: Build the selection tray with count, add/remove/clear, accept/reject, export.
- [ ] P2-W06: Build the selection review panel with thumbnails, scope, remove, accept/reject and export.
- [ ] P2-W07: Add accept/reject all filtered with confirmation in the sidebar.
- [ ] P2-W08: Update docs.

**Acceptance criteria**

- The selection survives reloads, filters, pagination, folder changes and root switches in the same browser.
- Select-all adds; de-select-all-filtered removes only filtered ids; clear asks for confirmation.
- The review panel shows all selected photos across roots/folders and can be scoped.
- Accepted/rejected are persisted, badged, filterable and bulk-actionable.
- `hide_rejected` works.

**Phase gate:** the user can curate and persist decisions without losing the working selection.

### Phase 3 - Best N and group review

**Status:** `[ ]`

- [ ] P3-W01: Add `POST /api/select-best` with query, n, add/replace, existing ids, include-rejected.
- [ ] P3-W02: Add the quick best-N control with editable N and add/replace toggle.
- [ ] P3-W03: Add Selection settings (default N, diversity, max/day, max/cluster, max/group, event quota, include rejected, prefer accepted).
- [ ] P3-W04: Add "select best of each group" and `/compare/group/{group_id}`.
- [ ] P3-W05: Enhance compare with select best, select all, accept best, reject others.
- [ ] P3-W06: Run best-N as a background job for large filtered sets.
- [ ] P3-W07: Update docs.

**Acceptance criteria**

- The quick control selects N photos from the current filtered scope and reports caps.
- Add mode adds N new photos; replace mode replaces the selection.
- Rejected photos are excluded by default.
- Best-of-group selects exactly one photo per group.
- Compare can select/accept the best and reject the rest.
- Large selections complete as background jobs with visible status.

**Phase gate:** the user can go from a filtered set to a curated selection in one or two clicks.

### Phase 4 - Export

**Status:** `[ ]`

- [ ] P4-W01: Change `appdata.default_export_root()` to the home image directory logic.
- [ ] P4-W02: Add the export drawer/dialog with selected/filtered/accepted scopes.
- [ ] P4-W03: Force copy mode in the GUI; remove the mode selector.
- [ ] P4-W04: Add accepted scope to the export job.
- [ ] P4-W05: Add tests for the default path, copy-only behavior, accepted scope and drawer markup.
- [ ] P4-W06: Update docs.

**Acceptance criteria**

- The default target is `~/Bilder/image-triage/export_<stamp>` (or `~/Images`, or `~/image-triage`).
- The GUI never creates symlinks or hard links.
- Export can use selected, filtered or accepted photos.
- The export form does not disturb browsing/selection.
- Export runs as a background job with visible status.

**Phase gate:** export is a drawer, not a page, and always copies.

### Phase 5 - Events, Jobs and Settings

**Status:** `[ ]`

- [ ] P5-W01: Turn Events into a timeline with cards and representative thumbnails.
- [ ] P5-W02: Remove the manual job-start form; make Jobs read-only; add a header job status indicator.
- [ ] P5-W03: Reorganize Settings into Library, Filters, Selection, Export, Scoring, Analysis and Advanced.
- [ ] P5-W04: Add "rescan required" hints for analysis/scoring changes.
- [ ] P5-W05: Update docs and run `make syncdocs`.

**Acceptance criteria**

- Events is a useful timeline and event links open the filtered library.
- Jobs are read-only and reachable from the header.
- Settings are curated, with an Advanced section.
- Documentation matches the GUI.

**Phase gate:** the navigation reflects the workflow, not the database.

### Phase 6 - Verification and release

**Status:** `[ ]`

- [ ] P6-W01: Run `make fmt`, `make lint`, `make test`, `make syncdocs`, `mkdocs build` and the wheel/entry-point checks.
- [ ] P6-W02: Manual end-to-end walkthrough with at least two roots.
- [ ] P6-W03: Update README/docs, commit, push, confirm CI and close the tracking issue.

**Acceptance criteria**

- All checks pass.
- The manual walkthrough covers every new workflow.
- Documentation and generated config agree with the implementation.

## 5. Verification expectations

- **Bugs:** event/group filters, folder-tree root visibility, group options, select-all semantics, partial override updates.
- **Filters:** every metric min/max, group size, status, hide rejected, presets, filter visibility.
- **Selection:** persistence, add/remove/clear, review panel scope, stale-id pruning, bulk status.
- **Best-N:** caps, rejected exclusion, add/replace, large-set background job.
- **Groups:** group-size filter, compare route, best-of-group, accept best/reject rest.
- **Export:** default path, copy-only, accepted scope, drawer markup, background job.
- **Navigation:** Events timeline, read-only Jobs, Settings sections.
- **Quality gates:** `make fmt`, `make lint`, `make test`, `make syncdocs`, `mkdocs build`, wheel/entry-point checks.

## 6. Risks and open questions

### 6.1 Risks and mitigations

| Risk | Mitigation |
|---|---|
| localStorage is cleared or browser changes | Document it; offer export/accept as the durable path. |
| localStorage holds stale location ids | The review panel fetches summaries and prunes missing ids. |
| Best-N is O(N^2) in the MMR loop | Run as a background job above a threshold. |
| Too many filters overwhelm the sidebar | Filter visibility settings, collapsed advanced groups, presets. |
| Dual-range sliders are hard to make accessible | Two labeled range inputs with keyboard support and numeric readouts. |
| `overrides.keep` affects scoring | Accepted +0.05 / rejected -0.10 is the existing soft-signal behavior. |
| Accepted/rejected is content-level while selection is location-level | Document it; dedupe photo ids for status updates. |
| Changing the default view/export path surprises existing users | Document the change; `export.destination` remains an override. |
| Settings changes require generated docs | Run `make syncdocs` and verify. |

### 6.2 Assumptions

1. Selection stays localStorage; no server-side shortlist.
2. "Selected only" is the review panel, not a server-side grid filter.
3. Accepted/rejected reuses `overrides.keep`.
4. Best-N add mode adds N new photos; replace mode ends with N total.
5. Activity is replaced by a read-only Jobs page; main navigation is Library, Events, Settings.
6. Export supports accepted as a third scope.
7. Keyboard shortcuts and named selection sets are deferred.

### 6.3 Open questions

1. Should the Events timeline offer "select best N from this event" directly?
2. Should the selection review panel be pinned open on wide screens, or only as a drawer?
3. Should "reject others" in compare require a confirmation above a threshold?

## 7. Progress / Handoff

- 2026-11-15: Phase 0 complete. Fixed event/group filter parsing, kept the folder tree complete under a root scope, hid single-photo groups, changed the default view to folders, made select-all add with de-select/clear confirmation, and preserved rating on partial keep updates. Tests: 107 passed; Ruff clean. Commit `9fc70b7`, CI run `43770223757` green. Issue #21 closed. Existing issue #17 referenced. Next: Phase 1 (filter sidebar and filter model).
