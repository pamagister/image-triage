# Configuration Parameters

These parameters are available to configure the behavior of your application.
Parameters marked as CLI parameters can also be set via the command line interface.

## Configuration File Reference

The actual configuration is stored in [`config.yaml`](../../config.yaml). You can:

- Edit the configuration file directly using your text editor
- Use the `--config` command-line option to specify a custom config file

## Category "app" {#app}

| Name                   | Type | Description                                 | Default    | Choices                                                                                                                                               |
|------------------------|------|---------------------------------------------|------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| date_format            | str  | Date format to use                          | '%Y-%m-%d' | -                                                                                                                                                     |
| log_level              | str  | Logging level for the application           | 'INFO'     | ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']                                                                                                     |
| log_file_max_size      | int  | Maximum log file size in MB before rotation | 2          | -                                                                                                                                                     |
| enable_file_logging    | bool | Enable logging to file                      | True       | [True, False]                                                                                                                                         |
| enable_console_logging | bool | Enable logging to console                   | True       | [True, False]                                                                                                                                         |
| theme                  | str  | GUI theme setting supported by ttkbootstrap | 'darkly'   | ['cosmo', 'flatly', 'litera', 'minty', 'lumen', 'sandstone', 'yeti', 'pulse', 'united', 'darkly', 'superhero', 'solar', 'cyborg', 'vapor', 'simplex'] |

## Category "general" {#general}

| Name    | Type | Description                                              | Default               | Choices       |
|---------|------|----------------------------------------------------------|-----------------------|---------------|
| input   | Path | Folder with photos (searched recursively)                | PosixPath('.')        | -             |
| output  | Path | Folder the selected photos are exported to               | PosixPath('selected') | -             |
| dry_run | bool | Only analyze and report, do not write metadata or export | False                 | [True, False] |

## Category "selection" {#selection}

| Name          | Type  | Description                                                                                                          | Default | Choices                         |
|---------------|-------|----------------------------------------------------------------------------------------------------------------------|---------|---------------------------------|
| top_n         | int   | Export the N most relevant photos: best of each motif, spread over all subfolders (0 = export by min_rating instead) | 0       | -                               |
| min_rating    | int   | Export photos with at least this many stars (if top_n is 0)                                                          | 4       | [1, 2, 3, 4, 5]                 |
| max_per_group | int   | Number of best photos per similarity group that can get 3-5 stars                                                    | 1       | -                               |
| export_mode   | str   | How photos are placed in the output folder                                                                           | 'copy'  | ['copy', 'hardlink', 'symlink'] |
| diversity     | float | Top N: penalty for photos whose content resembles already selected ones (0 = rank by score only)                     | 0.5     | -                               |

## Category "similarity" {#similarity}

| Name                     | Type  | Description                                                                                                                      | Default | Choices |
|--------------------------|-------|----------------------------------------------------------------------------------------------------------------------------------|---------|---------|
| max_hash_distance        | int   | Max. differing pHash bits (of 64) for two photos to count as similar                                                             | 20      | -       |
| max_time_gap_s           | float | Max. seconds between two shots to be compared for similarity                                                                     | 10.0    | -       |
| min_embedding_similarity | float | Shots taken close together also count as similar if their content embeddings (object model) have at least this cosine similarity | 0.97    | -       |

## Category "scoring" {#scoring}

| Name                | Type  | Description                                                             | Default                                                           | Choices |
|---------------------|-------|-------------------------------------------------------------------------|-------------------------------------------------------------------|---------|
| sharpness_weight    | float | Weight of sharpness in the quality score                                | 0.6                                                               | -       |
| exposure_weight     | float | Weight of exposure in the quality score                                 | 0.2                                                               | -       |
| object_weight       | float | Weight of a large, clearly detected subject in the score (object model) | 0.2                                                               | -       |
| subject_classes     | str   | Comma-separated object classes that count as subject                    | 'person,bird,cat,dog,horse,sheep,cow,elephant,bear,zebra,giraffe' | -       |
| sharpness_reference | float | Sharpness value (Laplacian variance) that counts as fully sharp         | 250.0                                                             | -       |
| blur_threshold      | float | Photos below this sharpness are rated as blurry (1 star)                | 30.0                                                              | -       |
| min_score_5         | float | Min. score (0-1) of a group's best photo for 5 stars                    | 0.75                                                              | -       |
| min_score_4         | float | Min. score (0-1) of a group's best photo for 4 stars (else 3)           | 0.5                                                               | -       |

## Category "models" {#models}

| Name            | Type  | Description                                                       | Default                            | Choices       |
|-----------------|-------|-------------------------------------------------------------------|------------------------------------|---------------|
| enabled         | bool  | Detect objects (YOLO) for scoring, content diversity and keywords | True                               | [True, False] |
| object_detector | Path  | YOLO26 ONNX model file                                            | PosixPath('res/yolo/yolo26n.onnx') | -             |
| confidence      | float | Min. confidence (0-1) of an object detection                      | 0.5                                | -             |

## Category "metadata" {#metadata}

| Name             | Type | Description                                                                     | Default    | Choices       |
|------------------|------|---------------------------------------------------------------------------------|------------|---------------|
| write_xmp_rating | bool | Write the star rating as XMP Rating into the image files                        | True       | [True, False] |
| write_keywords   | bool | Write detected objects as XMP keywords (dc:subject), existing keywords are kept | True       | [True, False] |
| sidecar_for_raw  | bool | Also write the rating to an .xmp sidecar of a RAW file with the same name       | True       | [True, False] |
| exiftool_path    | str  | ExifTool executable (name on PATH or full path)                                 | 'exiftool' | -             |

