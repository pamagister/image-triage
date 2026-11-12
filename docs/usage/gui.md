# Web GUI

The local GUI is a FastAPI application with server-rendered Jinja templates and htmx. It binds
to `127.0.0.1:8765` by default and has no authentication; it is intended for a single local user.

```bash
uv sync
uv run python -m image_triage.gui
# or: uv run image-triage gui --host 127.0.0.1 --port 8765
# or, after installation: image-triage-gui
```

The GUI reads the same SQLite state store as the CLI. Run `analyze` and `score` (or a full
`run`) first, then open `http://127.0.0.1:8765`.

## Pages

- **Library** - paginated grid with search, rating, event, label, capture-date and minimum-score
  filters plus sorting; pagination and sort links preserve the active filters.
- **Photo detail** - image, metrics, composition breakdown, detections, similar shots, the current
  soft rating/keep/reject override and a form to change it.
- **Compare** - side-by-side view of similar shots with their metric tables.
- **Events** - timeline and a lightweight GPS scatter plot (no external map tiles).
- **Jobs** - start analyze/select/export jobs, poll their status and inspect results. Analysis
  jobs report progress and the page refreshes while work is active.

## Notes

- Media is served from the original files or the selected-photo WebP previews. The server checks
  that every requested path stays inside the input root.
- Overrides are soft signals stored in SQLite; they do not modify originals and are available to
  future selection runs.
- Export jobs use the newest stored selection and fail clearly when no selection exists.
- Job execution uses a small background worker and the `jobs` table; the GUI never blocks the CLI.
- The GUI has no authentication and should not be bound to a public interface.
