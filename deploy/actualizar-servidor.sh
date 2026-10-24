#!/usr/bin/env bash
# Publishes on the server the version of main that is already on GitHub. Run it on the Mac, from the project folder:
#   bash deploy/actualizar-servidor.sh            # all tests (about 5 minutes) and update
#   bash deploy/actualizar-servidor.sh --rapido   # without the browser tests
# Asks for the server password (sudo of jcm) once. Works from anywhere with Tailscale active.
set -euo pipefail
TARGET=jcm@agserver;FAST=0
die(){ printf '\nError: %s\n' "$*" >&2; exit 1; }
for arg in "$@"; do
    case "$arg" in
        --rapido) FAST=1;;
        -h|--help) sed -n '2,6p' "$0";exit 0;;
        *@*) TARGET=$arg;;
        *) die "Opción desconocida: $arg";;
    esac
done
ROOT=$(cd "$(dirname "$0")/.." && pwd);cd "$ROOT"
LOG=$(mktemp -d)/pruebas;mkdir -p "$LOG"

echo '==> ¿Está todo publicado en GitHub?'
git fetch -q origin main
[ -z "$(git status --porcelain)" ] || die 'Hay cambios sin commit. Haz commit y push antes de actualizar el servidor.'
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die 'Lo que tienes en el Mac no coincide con main en GitHub. Sube los cambios (push) o actualiza tu copia.'
NEW=$(git rev-parse --short origin/main)

echo '==> Versión del servidor'
CURRENT=$(ssh -o ConnectTimeout=10 "$TARGET" 'git -c safe.directory=/opt/adg-finance -C /opt/adg-finance rev-parse HEAD') || die "No se puede conectar con $TARGET. ¿Está Tailscale activo?"
if [ "$CURRENT" = "$(git rev-parse origin/main)" ]; then echo "El servidor ya tiene la versión $NEW. No hay nada que actualizar.";exit 0;fi
git cat-file -e "$CURRENT" 2>/dev/null || die "El servidor tiene una versión ($CURRENT) que no está en tu copia: actualiza tu copia con git pull."
echo "Servidor: $(git log -1 --format='%h · %s' "$CURRENT")"
echo "Nueva:    $(git log -1 --format='%h · %s' origin/main)"
echo 'Cambios que se instalarán:';git log --format='  · %h %s' "$CURRENT..origin/main"

# Fiscal version: a new version needs the producer's declaración responsable before the first real submission.
version_at(){ git show "$1:backend/verifactu_xml.py" | python3 -I -c "import re,sys;print(re.search(r\"'version':'([^']+)'\",sys.stdin.read())[1])"; }
OLD_FISCAL=$(version_at "$CURRENT");NEW_FISCAL=$(version_at origin/main)
if [ "$OLD_FISCAL" != "$NEW_FISCAL" ]; then
    echo;echo "ATENCIÓN: cambia la versión fiscal del programa ($OLD_FISCAL → $NEW_FISCAL)."
    echo 'Antes de actualizar, la declaración responsable que cubre la nueva versión debe estar firmada y guardada'
    echo '(VERI*FACTU · pruebas → Productor del programa). Los registros reales la llevarán desde el primer envío.'
    read -r -p '¿Está guardada la declaración de la nueva versión? (s/N) ' answer;[ "$answer" = s ] || [ "$answer" = S ] || die 'Actualización cancelada.'
fi

echo;echo '==> Pruebas en el Mac'
npm test >"$LOG/js.txt" 2>&1 || { tail -30 "$LOG/js.txt";die 'Fallan las pruebas de JavaScript.'; }
echo '  JavaScript: correctas'
sh scripts/test-backend.sh >"$LOG/backend.txt" 2>&1 || { grep -E '^(FAIL|ERROR)' -A12 "$LOG/backend.txt" | head -60;die 'Fallan las pruebas del servidor (backend).'; }
echo "  Servidor: $(grep -E '^Ran ' "$LOG/backend.txt") correctas"
if [ "$FAST" = 0 ]; then
    sh scripts/test-browser.sh >"$LOG/navegador.txt" 2>&1 || { tail -30 "$LOG/navegador.txt";die 'Fallan las pruebas de navegador.'; }
    echo "  Navegador: $(grep -c '^PASS' "$LOG/navegador.txt") bloques correctos"
else echo '  Navegador: omitidas (--rapido)';fi

echo;read -r -p "¿Actualizar el servidor $TARGET a la versión $NEW? (s/N) " answer
[ "$answer" = s ] || [ "$answer" = S ] || die 'Actualización cancelada.'
scp -q deploy/actualizar.sh deploy/install-ubuntu.sh "$TARGET:/tmp/"
echo '==> Actualización en el servidor (pedirá la contraseña de sudo)'
ssh -t "$TARGET" 'sudo bash /tmp/actualizar.sh; status=$?; rm -f /tmp/actualizar.sh /tmp/install-ubuntu.sh; exit $status'
