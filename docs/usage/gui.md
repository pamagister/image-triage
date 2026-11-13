# Web GUI

The local GUI is a FastAPI application with server-rendered Jinja templates and htmx. It binds
to `127.0.0.1:8765` by default and has no authentication; it is intended for a single local user.

```bash
uv sync
uv run python -m image_triage.gui
# or: uv run image-triage gui --host 127.0.0.1 --port 8765
# or, after installation: image-triage-gui
```

The GUI and CLI share one central state store under the user's application data directory:

- Linux: `~/.local/share/image-triage/triage.db` (data), `~/.config/image-triage/config.yaml`
  (configuration), `~/.cache/image-triage` (derived previews and run outputs)
- macOS: `~/Library/Application Support/image-triage` and `~/Library/Caches/image-triage`
- Windows: `%LOCALAPPDATA%\image-triage` and `%APPDATA%\image-triage`

Set `IMAGE_TRIAGE_DATA_DIR`, `IMAGE_TRIAGE_CONFIG_DIR` or `IMAGE_TRIAGE_CACHE_DIR` to override
the locations. Old per-library `<library>/.image-triage/triage.db` files are left untouched and
are not imported.

## Pages

- **Setup** - switch the single legacy library folder. Multi-root libraries are managed on the
  Settings page.
- **Settings** - manage watched roots, excluded directory names, default view and tile metadata,
  export defaults, blur calibration, rating thresholds and analysis toggles. Settings are written
  atomically to the central YAML configuration and shared with the CLI. Changes are rejected
  while a job is active.
- **Library** - flat grid of every available photo location, or a folder tree with photo counts.
  An empty library is scanned automatically; when files were added, changed or removed the page
  shows a stale-library banner with a **Scan library** button. Filter by search, root, folder,
  rating, event, group, label, blur, camera make and model (all multi-select), capture-date
  range, score/sharpness/aesthetic/subject ranges; sort by capture time, score, rating, sharpness,
  bokeh, aesthetic or subject in either direction, and page through the result with the active
  filters preserved. The first tile line is the file name; the full path is below it. Optional
  metadata fields are selected in Settings (default: score, rating, date).
- **Folder view** - the left tree lists only folders that contain matching photos, with counts
  that respect the active filters. Each folder row has a checkbox that selects all descendant
  locations; a partially selected folder is shown as indeterminate.
- **Photo detail** - image, global and subject sharpness, bokeh, blur, composition breakdown,
  detections, similar shots, the current soft rating/keep/reject override and a form to change it.
- **Compare** - side-by-side view of similar shots with their metric tables.
- **Events** - timeline and a lightweight GPS scatter plot (no external map tiles).
- **Activity** - start scan/analyze/select/export jobs, poll their status and inspect results.
  A **scan** runs analysis, grouping, event detection and scoring in one step, so scores and
  ratings are available without a separate select job.

## Selecting and exporting

- Tick the checkbox on a tile to select it. The selection unit is the location, so the same
  image in two watched folders can be selected independently. The selection lives in
  `localStorage`, so it survives filtering and pagination within the browser session; it is
  deliberately not stored on the server.
- **Select all filtered** replaces the selection with every photo matching the current filters,
  across all pages. Individual checkboxes can then be unticked to opt out.
- **Clear** empties the selection.
- **Export selected** exports exactly the ticked photos. **Export all filtered** exports every
  photo matching the current filters, not just the visible page.
- The export form takes a target directory, defaulting to a timestamped folder under the central
  data directory, and a mode (`copy`, `hardlink` or `symlink`). The default layout is flat; a
  folder-tree layout is optional. Flat collisions are resolved with `_1`, `_2` suffixes.
- Optional **Re-render** writes JPEGs at the configured maximum long edge and quality (default
  85), preserving EXIF and ICC. Re-rendering forces copy mode. RAW files are copied or linked
  unchanged.
- The target must be outside every watched root so exported copies are never re-analyzed.
- Exports run as background jobs and report progress on the Activity page.

## Notes

- Media is served from the original files or from digest-keyed WebP previews in the central
  cache, with a long cache lifetime. The server checks that every requested path stays inside a
  watched root.
- Sharpness is measured on the subject region when detections exist, with a saliency window as
  fallback. `blur_score` is an absolute 0..1 value (0 = tack sharp, 1 = unusable) derived from
  the subject detail; it is meaningful for every photo. `blur_kind` and `blur_confidence` remain
  for defect classification. Intentional bokeh is reported separately and is not treated as a
  blur defect; the score is only gated for actual motion or defocus blur with sufficient
  confidence.
- Overrides are soft signals stored in SQLite; they do not modify originals and are available to
  future selection runs.
- The library page selection is ephemeral by design: clearing browser storage or using another
  browser starts a fresh selection.
- Job execution uses a small background worker and the `jobs` table; the GUI never blocks the CLI.
- The GUI has no authentication and should not be bound to a public interface.
