# JSON for agents

Image Triage is designed to be driven by scripts and coding agents. Human-readable logs go to
stderr; machine-readable data goes to stdout.

## Output modes

- `--json` on a command prints one JSON document.
- `analyze --ndjson` prints one compact JSON object per line: `start`, `photo`, `progress`,
  `error` and `summary` events.
- Errors are printed to stderr as JSON when the command supports `--json`:
  `{"error": {"type": "...", "message": "...", "exit_code": 3, "details": {}}}`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 2 | usage or configuration error |
| 3 | input error (missing/unreadable library) |
| 4 | model or provider missing |
| 5 | partial failure (only with `--strict`) |
| 6 | internal error |

## Examples

Analyze a library and stream progress:

```bash
image-triage analyze --input ~/Photos/2025 --ndjson
```

Run the full pipeline and parse the summary:

```bash
image-triage run --input ~/Photos/2025 --output best --top-n 200 --json
```

Validate the produced report against the published schema:

```bash
image-triage schema report --output report.schema.json
check-jsonschema --schemafile report.schema.json best/report.json
```

## Schemas

`image-triage schema` publishes three documents:

- `report` - `report.json` produced by `run`/`report`.
- `plan` - the JSON file written by `plan`.
- `ndjson` - one progress event emitted by `analyze --ndjson`.

All schemas are JSON Schema draft 2020-12.

## Stability

JSON field names, exit codes and schema versions are stable within a major release. The report
contains `schema_version`, `tool_version`, `config_hash`, `model_hashes` and `selection_version`
so a consumer can detect changes. Reports omit GPS unless `report.include_gps` or
`report --include-gps` is enabled.