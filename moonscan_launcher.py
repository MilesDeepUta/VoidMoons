"""
Entry point for the PyInstaller build.

`moonscan/__main__.py` uses a relative import (`from .app import main`) which
is correct for `python -m moonscan` but breaks inside a PyInstaller single-file
bundle because there's no parent package at that point. This file is a thin
shim that imports `moonscan.app` absolutely and runs it.
"""
import sys

from moonscan.app import main

if __name__ == "__main__":
    sys.exit(main())
