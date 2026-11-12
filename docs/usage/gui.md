# Web GUI

The local GUI is a FastAPI application with server-rendered Jinja templates and htmx. It binds
to `127.0.0.1:8765` by default and has no authentication; it is intended for a single local user.

```bash
uv sync
uv run python -m image_triage.gui
# or: uv run image-triage gui --host 127.0.0.1 --port 8765
# or, after installation: image-triage-gui
```

The GUI reads the same SQLite state store as the CLI. On first start it asks for the photo
library folder; the state database lives in `<library>/.image-triage/triage.db`, so switching
folders also switches to that folder's own analysis history.

## Pages

- **Setup** - choose the library folder. Shows the active root, the number of images found and
  the state database path. A change is rejected while a job is running. Hidden and tool
  directories (`.git`, `.venv`, `htmlcov`, caches, IDE folders) are never scanned.
- **Library** - flat grid of every analyzed photo. An empty library is scanned automatically;
  when files were added, changed or removed the page shows a stale-library banner with a
  **Scan library** button. Filter by search, rating, event, group, label, blur, camera make and
  model (all multi-select), capture-date range, score/sharpness/aesthetic/subject ranges; sort by
  capture time, score, rating, sharpness, bokeh, aesthetic or subject in either direction, and
  page through the result with the active filters preserved. Every tile shows score, rating,
  global and subject sharpness, bokeh, blur, group, event and capture time.
- **Photo detail** - image, global and subject sharpness, bokeh, blur, composition breakdown,
  detections, similar shots, the current soft rating/keep/reject override and a form to change it.
- **Compare** - side-by-side view of similar shots with their metric tables.
- **Events** - timeline and a lightweight GPS scatter plot (no external map tiles).
- **Activity** - start scan/analyze/select/export jobs, poll their status and inspect results.
  A **scan** runs analysis, grouping, event detection and scoring in one step, so scores and
  ratings are available without a separate select job.

## Selecting and exporting

- Tick the checkbox on a tile to select it. The selection lives in `localStorage`, so it
  survives filtering and pagination within the browser session; it is deliberately not stored
  on the server.
- **Select all filtered** replaces the selection with every photo matching the current filters,
  across all pages. Individual checkboxes can then be unticked to opt out.
- **Clear** empties the selection.
- **Export selected** exports exactly the ticked photos. **Export all filtered** exports every
  photo matching the current filters, not just the visible page.
- The export form takes a target directory, defaulting to `export_YYYY-MM-DD_HH-MM` under the
  server's working directory, and a mode (`copy`, `hardlink` or `symlink`). The target must be
  outside the library root so exported copies are never re-analyzed.
- Exports run as background jobs and report progress on the Activity page.

## Notes

- Media is served from the original files or the selected-photo WebP previews, with a long
  cache lifetime. The server checks that every requested path stays inside the input root.
- Sharpness is measured on the subject region when detections exist, with a saliency window as
  fallback. Intentional bokeh is reported separately and is not treated as a blur defect; the
  score is only gated for actual motion or defocus blur with sufficient confidence.
- Overrides are soft signals stored in SQLite; they do not modify originals and are available to
  future selection runs.
- The library page selection is ephemeral by design: clearing browser storage or using another
  browser starts a fresh selection.
- Job execution uses a small background worker and the `jobs` table; the GUI never blocks the CLI.
- The GUI has no authentication and should not be bound to a public interface.
