#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# The browser tests start serve.py with python3: use the project environment, which has Waitress.
if [ -x .venv/bin/python ]; then
    PATH="$PWD/.venv/bin:$PATH"
    export PATH
fi
node tests/run-browser.mjs
node tests/analysis-browser.mjs
node tests/all-invoices-browser.mjs
node tests/invoice-number-browser.mjs
node tests/users-browser.mjs
node tests/resilience-browser.mjs
node tests/concurrent-browser.mjs
node tests/emitters-browser.mjs
node tests/invoice-emitter-browser.mjs
node tests/verifactu-browser.mjs
node tests/examples-browser.mjs
node tests/retention-browser.mjs
node tests/series-browser.mjs
node tests/security-browser.mjs
node tests/mail-browser.mjs
node tests/removal-browser.mjs
