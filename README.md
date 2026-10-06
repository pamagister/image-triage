<!-- This README.md is auto-generated from docs/index.md -->

# Welcome to image-triage

A feature-rich Python project template with auto-generated CLI, GUI and parameterized configuration.

[![Github CI Status](https://github.com/pamagister/image-triage/actions/workflows/main.yml/badge.svg)](https://github.com/pamagister/image-triage/actions)
[![GitHub release](https://img.shields.io/github/v/release/pamagister/image-triage)](https://github.com/pamagister/image-triage/releases)
[![Read the Docs](https://readthedocs.org/projects/image-triage/badge/?version=stable)](https://image-triage.readthedocs.io/en/stable/)
[![License](https://img.shields.io/github/license/pamagister/image-triage)](https://github.com/pamagister/image-triage/blob/main/LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/pamagister/image-triage)](https://github.com/pamagister/image-triage/issues)
[![PyPI](https://img.shields.io/pypi/v/image-triage)](https://pypi.org/project/image-triage/)
[![Downloads](https://pepy.tech/badge/image-triage)](https://pepy.tech/project/image-triage/)


This template provides a solid foundation for your next Python project, incorporating best practices for testing, automation, and distribution. It streamlines the development process with a comprehensive set of pre-configured tools and workflows, allowing you to focus on writing code.

---

## How to use this template

Getting started on developing your own project based on this template

> **DO NOT FORK** 
> This project is meant to be used from **[Use this template](https://github.com/pamagister/image-triage/generate)** feature.

---

1. **Create a new repository using GitHub template**  
   Click on **[Use this template](https://github.com/pamagister/image-triage/generate)**.

2. **Give a name to your project**  
   For example: `my-python-project`  
   *(Hyphens may be used as project name; they are converted during renaming internally to underscores for packages.)*

3. **Set write permissions**  
   Go to: `Repository -> Settings -> Actions -> General -> Workflow permissions`  
   Select: `Read and write permissions`, then click **Save**.

4. **Trigger rename workflow**  
   Navigate to `Actions` tab → Select **Rename Action** → Run workflow on the `main` branch.

5. **Wait for the workflow to finish**

6. **Clone the repository**  
   Run:  
   ```bash
   git clone [your-github-url]
   ```

7. **Open the project in your IDE**

8. **Install dependencies and create virtual environment**
   Run:

   ```bash
   make install
   ```

9. **Configure your IDE**
   Set `.venv` as the local Python virtual environment.

10. **Adjust project metadata**
    Modify `pyproject.toml` (e.g., project description, authors, license, etc.)

11. **Clean up template scripts**
    Delete the files:

    * `rename_project.yml`
    * `rename_project.sh`

12. **Format your codebase**
    Run:

    ```bash
    make fmt
    ```

    This will auto-format your files and reorder imports (based on any name changes).

13. **Enable pre-commit hooks**
    Run:

    ```bash
    uv run pre-commit install
    ```

14. **Add repository to ReadTheDocs**
    Visit: [https://app.readthedocs.org/dashboard/import/](https://app.readthedocs.org/dashboard/import/)

15. **Configure PyPI publishing**

    * Generate a **PyPI API token** from your PyPI account.
    * Go to **GitHub → Settings → Secrets and variables → Actions**.
    * Add the secret as `PYPI_API_TOKEN`.
    * The token probably starts with "pypi-..."

16. **Release your first version**
    Run:

    ```bash
    make release
    ```
    
---

## Feature overview

* 📦 **Package Management:** Utilizes [uv](https://docs.astral.sh/uv/getting-started/), an extremely fast Python package manager, with dependencies managed in `pyproject.toml`.
* ✅ **Code Formatting and Linting:** Pre-commit hook with the [RUFF auto-formatter](https://docs.astral.sh/ruff/) to ensure consistent code style.
* 🧪 **Testing:** Unit testing framework with [pytest](https://docs.pytest.org/en/latest/).
* 📊 **Code coverage reports** using [codecov](https://about.codecov.io/sign-up/)
* 🔄 **CI/CD:**  [GitHub Actions](https://github.com/features/actions) for automated builds (Windows, macOS), unit tests, and code checks.
* 💾 **Automated Builds:** GitHub pipeline for automatically building a Windows executable and a macOS installer.
* 💬 **Parameter-Driven Automation:**
    * Automatic generation of a configuration file from parameter definitions.
    * Automatic generation of a Command-Line Interface (CLI) from the same parameters.
    * Automatic generation of CLI API documentation.
    * Automatic generation of change log using **gitchangelog** to keep a HISTORY.md file up to date.
* 📃 **Documentation:** Configuration for publishing documentation on [Read the Docs](https://about.readthedocs.com/) using [mkdocs](https://www.mkdocs.org/) .
* 🖼️ **Minimalist GUI:** Comes with a basic GUI based on [tkinker](https://tkdocs.com/tutorial/index.html) that includes an auto-generated settings menu based on your defined parameters.
* 🖥️ **Workflow Automation:** A `Makefile` is included to simplify and automate common development tasks.
* 🛳️ **Release pipeline:** Automated releases unsing the Makefile `make release` command, which creates a new tag and pushes it to the remote repo. The `release` pipeline will automatically create a new release on GitHub and trigger a release on  [PyPI](https://pypi.org.
    * **[setuptools](https://pypi.org/project/setuptools/)** is used to package the project and manage dependencies.
    * **[setuptools-scm](https://pypi.org/project/setuptools-scm/)** is used to automatically generate the `_version.py` file from the `pyproject.toml` file.

---

## Installation

Get an impression of how your own project could be installed and look like.

Download from [PyPI](https://pypi.org/).

💾 For more installation options see [install](docs/getting-started/install.md).

```bash
pip install image-triage
```

Run GUI from command line

```bash
image-triage-gui
```

Run application from command line using CLI

```bash
python -m image_triage.cli [OPTIONS] path/to/file
```

```bash
image-triage-cli [OPTIONS] path/to/file
```

---

## Troubleshooting

### Problems with release pipeline

If you get this error below:
```bash
/home/runner/work/_temp/xxxx_xxx.sh: line 1: .github/release_message.sh: Permission denied
```

You have to run these commands in your IDE Terminal or the git bash and then push the changes.
```bash
git update-index --chmod=+x ./.github/release_message.sh
```

