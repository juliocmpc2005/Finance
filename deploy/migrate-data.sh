#!/usr/bin/env bash
# Traslada los datos de este equipo (cuentas, facturas, justificantes, documentos y claves) al servidor.
#
# Uso, en el Mac, con la aplicación local detenida y el servidor ya instalado con install-ubuntu.sh:
#   bash deploy/migrate-data.sh usuario@servidor
#
# Copia SQLite con su API de copia (consistente aunque haya WAL), conserva en el servidor una copia de
# los datos que hubiera, cierra todas las sesiones y comprueba que la aplicación arranca.
set -euo pipefail

TARGET=${1:-}
[ -n "$TARGET" ] || { echo 'Uso: bash deploy/migrate-data.sh usuario@servidor' >&2;exit 1; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE=${ADG_DATA_DIR:-$ROOT/data}
[ -f "$SOURCE/finance.sqlite" ] || { echo "No hay datos en $SOURCE." >&2;exit 1; }
if lsof -nP -iTCP:"${ADG_PORT:-4173}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo 'La aplicación local sigue en marcha. Detenla (Ctrl+C en su terminal) para que no cambien los datos durante el traslado.' >&2;exit 1
fi

WORK=$(mktemp -d);trap 'rm -rf "$WORK"' EXIT
mkdir "$WORK/data"
echo '==> Copia consistente de SQLite'
python3 -I - "$SOURCE/finance.sqlite" "$WORK/data/finance.sqlite" <<'EOF'
import sqlite3,sys
from contextlib import closing
with closing(sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True)) as source,closing(sqlite3.connect(sys.argv[2])) as target:
    source.backup(target)
    if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':sys.exit('La copia de SQLite no supera la comprobación de integridad.')
EOF
rsync -a --exclude 'finance.sqlite' --exclude 'finance.sqlite-*' "$SOURCE/" "$WORK/data/"
[ -f "$WORK/data/vf-secrets/master.key" ] || echo 'Aviso: no hay clave de servidor (vf-secrets/master.key); los certificados y contraseñas cifradas no se podrán leer.'
COPYFILE_DISABLE=1 tar --no-xattrs -C "$WORK" -czf "$WORK/adg-data.tgz" data
du -h "$WORK/adg-data.tgz" | awk '{print "    Paquete: "$1}'

cat > "$WORK/adg-restore.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
DATA=/var/lib/adg-finance;SERVICE=adg-finance;STAMP=$(date +%Y%m%d-%H%M%S)
cd /
[ -x /opt/adg-finance/.venv/bin/python ] || { echo 'Instala primero el servidor con install-ubuntu.sh.' >&2;exit 1; }
systemctl stop "$SERVICE"
if [ -n "$(ls -A "$DATA" 2>/dev/null)" ];then mv "$DATA" "$DATA.antes-$STAMP";echo "    Datos anteriores conservados en $DATA.antes-$STAMP";fi
install -d -m 0700 -o "$SERVICE" -g "$SERVICE" "$DATA"
tar -C "$DATA" --strip-components=1 --no-same-owner -xzf /tmp/adg-data.tgz
chown -R "$SERVICE:$SERVICE" "$DATA";chmod -R go-rwx "$DATA"
sudo -u "$SERVICE" env ADG_DATA_DIR="$DATA" /opt/adg-finance/.venv/bin/python /opt/adg-finance/manage_users.py revoke-sessions
systemctl start "$SERVICE"
for _ in $(seq 60);do curl -fs http://127.0.0.1:4173/api/auth/session >/dev/null && break;sleep 0.5;done
curl -fs http://127.0.0.1:4173/api/auth/session >/dev/null || { journalctl -u "$SERVICE" -n 40 --no-pager;exit 1; }
rm -f /tmp/adg-data.tgz /tmp/adg-restore.sh
echo '    La aplicación del servidor responde con los datos trasladados.'
EOF

echo "==> Envío a $TARGET"
scp -q "$WORK/adg-data.tgz" "$WORK/adg-restore.sh" "$TARGET:/tmp/"
echo '==> Restauración en el servidor (puede pedir la contraseña de sudo)'
ssh -t "$TARGET" 'sudo bash /tmp/adg-restore.sh'
echo
echo 'Traslado completado. Todas las sesiones se han cerrado: cada persona vuelve a entrar con su cuenta.'
echo 'A partir de ahora trabaja solo en el servidor; los datos de este Mac ya no se sincronizan con él.'
