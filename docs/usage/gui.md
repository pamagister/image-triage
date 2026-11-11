# Web GUI

The local GUI is a FastAPI application with server-rendered Jinja templates and htmx. It binds
to `127.0.0.1:8765` by default and has no authentication; it is intended for a single local user.

```bash
uv sync --extra gui
uv run image-triage gui
# or: image-triage gui --host 127.0.0.1 --port 8765
```

The GUI reads the same SQLite state store as the CLI. Run `analyze` or `score` first, then open
`http://127.0.0.1:8765`.

## Pages

- **Library** - paginated grid with search, rating, event, label and sort filters.
- **Photo detail** - image, metrics, composition breakdown, detections, similar shots and a
  soft rating/keep/reject override form.
- **Compare** - side-by-side view of similar shots with their metric tables.
- **Events** - timeline and a lightweight GPS scatter plot (no external map tiles).
- **Jobs** - start analyze/select/export jobs, poll their status and inspect results.

## Notes

- Media is served from the original files or the selected-photo WebP previews. The server checks
  that every requested path stays inside the input root.
- Overrides are soft signals stored in SQLite; they do not modify originals and are available to
  future selection runs.
- Job execution uses a small background worker and the `jobs` table; the GUI never blocks the CLI.
- The GUI has no authentication and should not be bound to a public interface.