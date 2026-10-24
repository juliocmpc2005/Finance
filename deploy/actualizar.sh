#!/usr/bin/env bash
# Runs on the server as root; deploy/actualizar-servidor.sh (on the Mac) sends it with install-ubuntu.sh and starts it.
# 1. Consistent copy of the database. 2. Update to the main branch published on GitHub. 3. Checks: the service is
# active, the application answers and generates a PDF. If a check fails, the previous version is installed again.
# The database copy is kept: restoring it is a manual decision, because it would discard what was saved since.
set -euo pipefail
APP=/opt/adg-finance;DATA=/var/lib/adg-finance;SERVICE=adg-finance;STAMP=$(date +%Y%m%d-%H%M%S)
INSTALLER="$(cd "$(dirname "$0")" && pwd)/install-ubuntu.sh"
step(){ printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die(){ printf '\nError: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die 'Ejecuta con sudo.'
[ -d "$APP/.git" ] || die 'No hay instalación en /opt/adg-finance: usa install-ubuntu.sh.'
[ -f "$INSTALLER" ] || die "Falta $INSTALLER."
cd /
version(){ git -c safe.directory="$APP" -C "$APP" rev-parse --short HEAD; }
PREVIOUS=$(version)

check(){
    for _ in $(seq 60);do curl -fs http://127.0.0.1:4173/api/auth/session >/dev/null && break;sleep 1;done
    systemctl is-active -q "$SERVICE" && curl -fs http://127.0.0.1:4173/api/auth/session >/dev/null || return 1
    sudo -u adg-finance env PLAYWRIGHT_BROWSERS_PATH="$APP/browsers" PATH=/usr/bin:/bin "$APP/.venv/bin/python" -c "
import sys;sys.path.insert(0,'$APP')
from backend import documents
assert documents.generate_pdf('<!doctype html><p>Comprobación de la actualización</p>').startswith(b'%PDF-')" >/dev/null 2>&1
}

step "Copia de la base de datos (versión actual $PREVIOUS)"
COPY="$DATA/backups/antes-actualizar-$STAMP-$PREVIOUS.sqlite"
sudo -u adg-finance "$APP/.venv/bin/python" -I - "$DATA/finance.sqlite" "$COPY" <<'PY'
import sqlite3,sys
from contextlib import closing
with closing(sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True)) as source,closing(sqlite3.connect(sys.argv[2])) as target:
    source.backup(target)
    if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':sys.exit('La copia no supera la comprobación de integridad.')
PY
echo "Copia: $COPY"

step 'Actualización a la versión publicada en main'
if bash "$INSTALLER" && check; then
    step "Listo: $PREVIOUS → $(version)"
    echo 'La aplicación responde y genera PDF.'
    echo "Copia previa de la base de datos: $COPY"
    exit 0
fi

step "La comprobación ha fallado: vuelta a la versión anterior ($PREVIOUS)"
if bash "$INSTALLER" --commit "$PREVIOUS" && check; then
    echo "Restaurada la versión $PREVIOUS: la aplicación vuelve a responder. Los datos no se han tocado."
    echo "Copia de la base de datos de antes de actualizar: $COPY"
    echo "Revisa el fallo con: journalctl -u $SERVICE -n 100"
    exit 1
fi
echo "ATENCIÓN: tampoco responde la versión anterior. Revisa: journalctl -u $SERVICE -n 100" >&2
echo "Copia de la base de datos de antes de actualizar: $COPY" >&2
exit 2
