#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then
    PATH="$PWD/.venv/bin:$PATH"
    export PATH
fi
exec python3 -m unittest discover -s tests -p 'test_*.py' -v
