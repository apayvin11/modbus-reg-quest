#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
.venv/bin/python -m pip install -r requirements-release.txt
exec .venv/bin/python scripts/package.py --format bundle "$@"
