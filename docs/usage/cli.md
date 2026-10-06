# Command Line Interface

Command line options for image-triage

```bash
image-triage [OPTIONS] input
```

For development from a source checkout, the equivalent module invocation is:

```bash
python -m image_triage [OPTIONS] input
```

## Options

| Option               | Type | Description                                                                                                          | Default               | Choices                         |
|----------------------|------|----------------------------------------------------------------------------------------------------------------------|-----------------------|---------------------------------|
| --config             | str  | Path to configuration file                                                                                           | -                     | -                               |
| -v, --verbose        | bool | Enable debug logging                                                                                                 | False                 | [True, False]                   |
| -q, --quiet          | bool | Show warnings and errors only                                                                                        | False                 | [True, False]                   |
| `--input`            | Path | Folder with photos (searched recursively)                                                                            | PosixPath('.')        | -                               |
| `--output`           | Path | Folder the selected photos are exported to                                                                           | PosixPath('selected') | -                               |
| `--dry-run`          | bool | Only analyze and report, do not write metadata or export                                                             | False                 | [True, False]                   |
| `--top-n`            | int  | Export the N most relevant photos: best of each motif, spread over all subfolders (0 = export by min_rating instead) | 0                     | -                               |
| `--min-rating`       | int  | Export photos with at least this many stars (if top_n is 0)                                                          | 4                     | [1, 2, 3, 4, 5]                 |
| `--max-per-group`    | int  | Number of best photos per similarity group that can get 3-5 stars                                                    | 1                     | -                               |
| `--export-mode`      | str  | How photos are placed in the output folder                                                                           | 'copy'                | ['copy', 'hardlink', 'symlink'] |
| `--models-enabled`   | bool | Detect objects (YOLO) for scoring, content diversity and keywords                                                    | True                  | [True, False]                   |
| `--write-xmp-rating` | bool | Write the star rating as XMP Rating into the image files (disabled by default)                                       | False                 | [True, False]                   |
| `--write-keywords`   | bool | Write detected objects as XMP keywords (dc:subject), existing keywords are kept (disabled by default)                | False                 | [True, False]                   |


## Examples


### 1. Basic usage

```bash
image-triage input
```

### 2. With verbose logging

```bash
image-triage -v input
image-triage --verbose input
```

### 3. With quiet mode

```bash
image-triage -q input
image-triage --quiet input
```

### 4. With input parameter

```bash
image-triage --input . input
```

### 5. With output parameter

```bash
image-triage --output selected input
```

### 6. With dry_run parameter

```bash
image-triage --dry-run True input
```

### Developer usage

```bash
python -m image_triage --help
python -m image_triage input
```
