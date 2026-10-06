# Installation


## 🐍 PyPI

### Install the package from PyPI

Download from [PyPI](https://pypi.org/):

```bash
pip install image-triage
```

### Run CLI from command line
```bash
image-triage [OPTIONS] path/to/file
```

### Run GUI from command line
```bash
image-triage-gui
```

## 🔽 Executable

Download the latest executable:

- [⬇️ Download for Windows](https://github.com/pamagister/image-triage/releases/latest/download/installer-win.zip)
- [⬇️ Download for macOS](https://github.com/pamagister/image-triage/releases/latest/download/package-macos.zip)


## 👩🏼‍💻 Run from source

### Clone the repository

```bash
git clone
```

### Navigate to the project directory

```bash
cd image-triage
```

### Install dependencies

```bash
uv venv
uv pip install -e .[dev,docs]
```


### Run with CLI from source

```bash
python -m image_triage.cli [OPTIONS] path/to/file
```


### Run with GUI from source

```bash
python -m image_triage.gui
```

