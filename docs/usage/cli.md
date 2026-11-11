# Command Line Interface

All commands support `--config` to point at a YAML file. Human logs go to stderr; machine-readable output goes to stdout with `--json` where available. `analyze --ndjson` streams one JSON object per progress event.

For development from a source checkout, use `python -m image_triage` instead of `image-triage`.

## Commands

### `doctor`

```text
Usage: python -m image_triage doctor [OPTIONS]                                                     
                                                                                                    
 Check Python, database, models, ONNX providers and sample images.                                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          <bool>  Emit machine-readable JSON.                                              │
│ --config        <path>  YAML config file.                                                        │
│ --help          <bool>  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `schema`

```text
Usage: python -m image_triage schema [OPTIONS] [schema_name]                                       
                                                                                                    
 Print a versioned JSON Schema used by the CLI.                                                     
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   schema_name      <str>  report, plan or ndjson. [default: report]                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --output        <path>  Write schema to a file.                                                  │
│ --help          <bool>  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `scan`

```text
Usage: python -m image_triage scan [OPTIONS]                                                       
                                                                                                    
 Recursively find images and print capture time, dimensions and GPS presence.                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input         <path>  Photo library root.                                                      │
│ --json          <bool>  Emit JSON.                                                               │
│ --config        <path>  YAML config file.                                                        │
│ --help          <bool>  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `analyze`

```text
Usage: python -m image_triage analyze [OPTIONS]                                                    
                                                                                                    
 Analyze sharpness, blur, composition, subjects and aesthetics for every photo.                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input         <path>  Photo library root.                                                      │
│ --json          <bool>  Emit a JSON summary.                                                     │
│ --ndjson        <bool>  Emit progress as NDJSON.                                                 │
│ --strict        <bool>  Fail on per-file analysis errors.                                        │
│ --config        <path>  YAML config file.                                                        │
│ --help          <bool>  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `score`

```text
Usage: python -m image_triage score [OPTIONS]                                                      
                                                                                                    
 Group, detect events, score and rate all analyzed photos.                                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input         <path>  Photo library root.                                                      │
│ --json          <bool>  Emit JSON.                                                               │
│ --config        <path>  YAML config file.                                                        │
│ --help          <bool>  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `select`

```text
Usage: python -m image_triage select [OPTIONS]                                                     
                                                                                                    
 Group, score and select photos using the active profile.                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input          <path>  Photo library root.                                                     │
│ --top-n          <int>   Maximum selected photos.                                                │
│ --profile        <str>   Selection profile.                                                      │
│ --json           <bool>  Emit JSON.                                                              │
│ --config         <path>  YAML config file.                                                       │
│ --help           <bool>  Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plan`

```text
Usage: python -m image_triage plan [OPTIONS]                                                       
                                                                                                    
 Compute a selection and write it as reviewable JSON without exporting.                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input          <path>  Photo library root.                                                     │
│ --output         <path>  Plan JSON file. [default: plan.json]                                    │
│ --top-n          <int>   Maximum selected photos.                                                │
│ --profile        <str>   Selection profile.                                                      │
│ --json           <bool>  Also print the plan as JSON.                                            │
│ --config         <path>  YAML config file.                                                       │
│ --help           <bool>  Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `apply`

```text
Usage: python -m image_triage apply [OPTIONS]                                                      
                                                                                                    
 Read a plan and export its selected originals.                                                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input         <path>  Photo library root.                                                      │
│ --plan          <path>  Selection plan JSON.                                                     │
│ --output        <path>  Export root.                                                             │
│ --mode          <str>   copy, hardlink or symlink.                                               │
│ --json          <bool>  Emit JSON.                                                               │
│ --config        <path>  YAML config file.                                                        │
│ --help          <bool>  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `export`

```text
Usage: python -m image_triage export [OPTIONS]                                                     
                                                                                                    
 Export selected originals, preserving their paths relative to the input root.                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input         <path>  Photo library root.                                                      │
│ --output        <path>  Export root. [default: selected]                                         │
│ --mode          <str>   copy, hardlink or symlink.                                               │
│ --run-id        <str>   Selection run id.                                                        │
│ --json          <bool>  Emit JSON.                                                               │
│ --config        <path>  YAML config file.                                                        │
│ --help          <bool>  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `report`

```text
Usage: python -m image_triage report [OPTIONS]                                                     
                                                                                                    
 Write a versioned JSON report or a stable CSV summary.                                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input              <path>  Photo library root.                                                 │
│ --output             <path>  Report file.                                                        │
│ --format             <str>   json or csv. [default: json]                                        │
│ --run-id             <str>   Selection run id.                                                   │
│ --include-gps        <bool>  Include GPS coordinates.                                            │
│ --json               <bool>  Print the report to stdout.                                         │
│ --config             <path>  YAML config file.                                                   │
│ --help               <bool>  Show this message and exit.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `run`

```text
Usage: python -m image_triage run [OPTIONS]                                                        
                                                                                                    
 Analyze, group, score, select, report and export in one deterministic pass.                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input                     <path>  Photo library root.                                          │
│ --output                    <path>  Output root. [default: selected]                             │
│ --top-n                     <int>   Maximum selected photos.                                     │
│ --profile                   <str>   Selection profile.                                           │
│ --export     --no-export    <bool>  Export selected originals. [default: export]                 │
│ --json                      <bool>  Emit a JSON summary.                                         │
│ --strict                    <bool>  Fail on per-file analysis errors.                            │
│ --config                    <path>  YAML config file.                                            │
│ --help                      <bool>  Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `benchmark`

```text
Usage: python -m image_triage benchmark [OPTIONS]                                                  
                                                                                                    
 Detect ONNX providers and measure analysis stages on sample photos.                                
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --input         <path>  Sample library root.                                                     │
│ --limit         <int>   Number of sample photos. [default: 20]                                   │
│ --json          <bool>  Emit JSON.                                                               │
│ --config        <path>  YAML config file.                                                        │
│ --help          <bool>  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `config`

```text
Usage: python -m image_triage config [OPTIONS] COMMAND [ARGS]...                                   
                                                                                                    
 Manage the YAML configuration.                                                                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help        <bool>  Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Write a documented default configuration file.                                         │
│ show      Print the effective merged configuration.                                              │
│ validate  Validate weights, paths, profiles and model files.                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `models`

```text
Usage: python -m image_triage models [OPTIONS] COMMAND [ARGS]...                                   
                                                                                                    
 Install and inspect ONNX models.                                                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help        <bool>  Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ install  Install a model, verify its checksum and record its license.                            │
│ list     List known models, installed paths and licenses.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```
