#!/bin/bash
# Runs the full suite from the repo folder, with the test venv in $BB_VENV
# (default ~/.venv; it needs requirements_test.txt installed).
cd "$(dirname "$0")"
venv="${BB_VENV:-$HOME/.venv}"
exec "${venv/#\~/$HOME}/bin/python" -m pytest -q -p no:cacheprovider "$@"
