# Configuration

Configuration precedence is **CLI options > `IMAGE_TRIAGE_*` environment variables > project `image-triage.yaml` > central appdata `config.yaml` > defaults**. Nested environment variables use `__`, for example `IMAGE_TRIAGE_SCORING__SHARPNESS_WEIGHT=0.5`.

Generate a starter file with `image-triage config init`, inspect the effective values with `image-triage config show`, and validate them with `image-triage config validate`.

The generated `config.yaml` contains the same defaults.

## "app" {#app}

| Name | Type | Default |
|---|---|---|
| log_level | str | `"INFO"` |
| max_workers | UnionType[int, NoneType] | `null` |
| strict | bool | `false` |

## "storage" {#storage}

| Name | Type | Default |
|---|---|---|
| config_dir | UnionType[Path, NoneType] | `null` |
| data_dir | UnionType[Path, NoneType] | `null` |
| cache_dir | UnionType[Path, NoneType] | `null` |

## "input" {#input}

| Name | Type | Default |
|---|---|---|
| root | Path | `.` |
| roots | list[Path] | `[]` |
| disabled_roots | list[Path] | `[]` |
| db_path | UnionType[Path, NoneType] | `null` |
| cache_dir | UnionType[Path, NoneType] | `null` |
| exclude | list[str] | `[".image-triage", "selected", "previews"]` |
| follow_symlinks | bool | `false` |

## "analysis" {#analysis}

| Name | Type | Default |
|---|---|---|
| preview_size | int | `1024` |
| draft | bool | `true` |
| batch_size | int | `4` |
| yolo_enabled | bool | `true` |
| yolo_confidence | float | `0.5` |
| aesthetic_enabled | bool | `true` |
| save_embeddings | bool | `true` |

## "scoring" {#scoring}

| Name | Type | Default |
|---|---|---|
| sharpness_weight | float | `0.45` |
| composition_weight | float | `0.25` |
| aesthetic_weight | float | `0.15` |
| subject_weight | float | `0.15` |
| min_score_5 | float | `0.75` |
| min_score_4 | float | `0.45` |
| sharpness_percentile | float | `90.0` |
| subject_classes | list[str] | `["person", "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "car", "bicycle", "motorcycle", "airplane", "boat"]` |

## "similarity" {#similarity}

| Name | Type | Default |
|---|---|---|
| max_hash_distance | int | `12` |
| max_time_gap_s | float | `10.0` |
| min_embedding_similarity | float | `0.97` |
| event_gap_s | float | `14400` |
| gps_jump_km | float | `50.0` |

## "selection" {#selection}

| Name | Type | Default |
|---|---|---|
| top_n | int | `200` |
| diversity | float | `0.5` |
| max_per_group | int | `1` |
| max_per_day | int | `5` |
| max_per_cluster | int | `3` |
| event_quota | str | `"sainte_lague"` |
| profiles_dir | Path | `profiles` |
| profile | str | `"best200"` |

## "models" {#models}

| Name | Type | Default |
|---|---|---|
| enabled | bool | `true` |
| yolo_path | Path | `res/yolo/yolo26n.onnx` |
| aesthetic_path | Path | `res/aesthetic/aesthetic.onnx` |
| registry_path | Path | `res/models/registry.json` |
| provider | str | `"CPUExecutionProvider"` |
| auto_download | bool | `false` |

## "report" {#report}

| Name | Type | Default |
|---|---|---|
| include_gps | bool | `false` |
| previews | bool | `true` |
| preview_max_side | int | `1600` |
| webp_quality | int | `80` |
| csv_columns | UnionType[list[str], NoneType] | `null` |
| export_mode | str | `"copy"` |

## "export" {#export}

| Name | Type | Default |
|---|---|---|
| mode | str | `"copy"` |
| layout | str | `"flat"` |
| rerender | bool | `false` |
| max_long_edge | UnionType[int, NoneType] | `null` |
| jpeg_quality | int | `85` |
| destination | UnionType[Path, NoneType] | `null` |

## "blur" {#blur}

| Name | Type | Default |
|---|---|---|
| sharp_reference | float | `120.0` |
| blur_reference | float | `5.0` |
| floor | float | `0.02` |

## "gui" {#gui}

| Name | Type | Default |
|---|---|---|
| host | str | `"127.0.0.1"` |
| port | int | `8765` |
| reload | bool | `false` |
| default_view | str | `"flat"` |
| tile_fields | list[str] | `["score", "rating", "taken"]` |
