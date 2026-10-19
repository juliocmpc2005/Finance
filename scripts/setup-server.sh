#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# Project environment: Waitress (HTTP server) and the VERI*FACTU dependencies.
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
