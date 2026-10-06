# Command Line Interface

Command line options for image_triage

```bash
python -m image_triage [OPTIONS] input
```

## Options

| Option                | Type | Description                                       | Default    | Choices       |
|-----------------------|------|---------------------------------------------------|------------|---------------|
| `input`               | str  | Path to input (file or folder)                    | *required* | -             |
| `--output`            | str  | Path to output destination                        | *required* | -             |
| `--min_dist`          | int  | Maximum distance between two waypoints            | 25         | -             |
| `--extract_waypoints` | bool | Extract starting points of each track as waypoint | True       | [True, False] |
| `--elevation`         | bool | Include elevation data in waypoints               | True       | [True, False] |


## Examples


### 1. Basic usage

```bash
python -m image_triage input
```

### 2. With verbose logging

```bash
python -m image_triage -v input
python -m image_triage --verbose input
```

### 3. With quiet mode

```bash
python -m image_triage -q input
python -m image_triage --quiet input
```

### 4. With min_dist parameter

```bash
python -m image_triage --min_dist 25 input
```

### 5. With extract_waypoints parameter

```bash
python -m image_triage --extract_waypoints True input
```

### 6. With elevation parameter

```bash
python -m image_triage --elevation True input
```