#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then
    PATH="$PWD/.venv/bin:$PATH"
    export PATH
    exec .venv/bin/python serve.py
fi
exec python3 serve.py
