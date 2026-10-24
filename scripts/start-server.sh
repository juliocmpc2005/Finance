#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# npm start runs the Mac development copy: test data, port 4174 and nothing leaves the machine
# (no AEAT, no real e-mail). The real server runs serve.py through systemd with its own settings.
: "${ADG_DATA_DIR:=$PWD/data-pruebas}"
: "${ADG_PORT:=4174}"
: "${ADG_VERIFACTU_NETWORK:=off}"
: "${ADG_MAIL_NETWORK:=off}"
: "${ADG_COPIA_PRUEBAS:=1}"
export ADG_DATA_DIR ADG_PORT ADG_VERIFACTU_NETWORK ADG_MAIL_NETWORK ADG_COPIA_PRUEBAS
echo "Copia de pruebas · datos en $ADG_DATA_DIR · sin AEAT ni correo real · http://localhost:$ADG_PORT"
if [ -x .venv/bin/python ]; then
    PATH="$PWD/.venv/bin:$PATH"
    export PATH
    exec .venv/bin/python serve.py
fi
exec python3 serve.py
