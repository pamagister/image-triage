"""Module entry point for ``python -m image_triage``."""

import sys

from image_triage.cli.app import main

if __name__ == "__main__":
    sys.exit(main())
