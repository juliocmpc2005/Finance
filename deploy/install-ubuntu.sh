#!/usr/bin/env bash
# Instala o actualiza arquitecturadeguardia Finance en Ubuntu Server 24.04 LTS.
#
# Uso, como root en el servidor:
#   bash install-ubuntu.sh                                           # sin dominio: acceso por túnel SSH
#   bash install-ubuntu.sh --domain finance.empresa.es --cloudflare  # Cloudflare Tunnel: sin abrir puertos
#   bash install-ubuntu.sh --domain finance.empresa.es               # Caddy: abre 80/443 en este equipo
#
# Volver a ejecutarlo actualiza el código desde GitHub, las dependencias y reinicia el servicio.
# El dominio y el modo se recuerdan en /etc/default/adg-finance; --no-domain vuelve al acceso por SSH.
# El token del túnel se pide sin mostrarlo (o se lee de CLOUDFLARE_TUNNEL_TOKEN); solo hace falta la primera vez.
# --commit SHA instala esa versión exacta de la rama (para volver atrás); no se recuerda.
# Guía completa: deploy/GUIA-SERVIDOR.md
set -euo pipefail

REPO=git@github.com:juliocmpc2005/Finance.git
BRANCH=main
APP=/opt/adg-finance
DATA=/var/lib/adg-finance
SERVICE=adg-finance
SETTINGS=/etc/default/adg-finance
KEY=/root/.ssh/adg-finance-deploy
NODE_MAJOR=24
# Huella publicada por GitHub de su clave ed25519: evita aceptar un servidor suplantado en la primera conexión.
GITHUB_ED25519=SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU

step(){ printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die(){ printf '\nError: %s\n' "$*" >&2; exit 1; }

DOMAIN='';MODE='';COMMIT=''
[ -f "$SETTINGS" ] && . "$SETTINGS"
while [ $# -gt 0 ]; do
    case "$1" in
        --domain) DOMAIN=${2:-};shift 2;;
        --cloudflare) MODE=cloudflare;shift;;
        --caddy) MODE=caddy;shift;;
        --no-domain) DOMAIN='';MODE=local;shift;;
        --branch) BRANCH=${2:-};shift 2;;
        --repo) REPO=${2:-};shift 2;;
        --commit) COMMIT=${2:-};shift 2;;
        -h|--help) sed -n '2,14p' "$0";exit 0;;
        *) die "Opción desconocida: $1 (usa --help)";;
    esac
done
# local: solo túnel SSH · caddy: HTTPS en este equipo (puertos 80/443) · cloudflare: Cloudflare Tunnel, sin puertos abiertos.
if [ -z "$DOMAIN" ] && { [ "$MODE" = cloudflare ] || [ "$MODE" = caddy ]; };then die "--$MODE necesita también --domain, por ejemplo --domain finance.empresa.es";fi
if [ -z "$DOMAIN" ];then MODE=local;elif [ -z "$MODE" ] || [ "$MODE" = local ];then MODE=caddy;fi
# --commit installs one exact version of the branch (deploy/actualizar.sh uses it to go back); it is not remembered.
if [ -n "$COMMIT" ] && ! printf '%s' "$COMMIT" | grep -Eq '^[0-9a-f]{7,40}$'; then die "El commit «${COMMIT}» no es válido."; fi
if [ -n "$DOMAIN" ] && ! printf '%s' "$DOMAIN" | grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'; then
    die "El dominio «${DOMAIN}» no es válido. Escríbelo sin https:// ni barras, por ejemplo finance.empresa.es"
fi

[ "$(id -u)" = 0 ] || die 'Ejecuta el script como root (sudo bash install-ubuntu.sh).'
. /etc/os-release
[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ] || die "Este script es para Ubuntu Server 24.04 LTS (detectado: ${PRETTY_NAME:-desconocido})."

step 'Paquetes del sistema y actualizaciones de seguridad automáticas'
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q git python3 python3-venv curl ca-certificates gnupg ufw unattended-upgrades sqlite3
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

step "Node.js $NODE_MAJOR LTS (repositorio oficial de NodeSource)"
if ! node --version 2>/dev/null | grep -q "^v$NODE_MAJOR\."; then
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
    apt-get update -q && apt-get install -y -q nodejs
fi
node --version

step 'Caddy (repositorio oficial)'
if ! command -v caddy >/dev/null; then
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q && apt-get install -y -q caddy
fi

step 'Usuario de servicio y directorios'
id "$SERVICE" >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$SERVICE"
install -d -m 0755 -o root -g root "$APP"
install -d -m 0700 -o "$SERVICE" -g "$SERVICE" "$DATA"

step 'Acceso de solo lectura al repositorio de GitHub'
install -d -m 0700 /root/.ssh
[ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N '' -C "adg-finance@$(hostname)" -f "$KEY"
if ! ssh-keygen -F github.com -f /root/.ssh/known_hosts >/dev/null 2>&1; then
    scanned=$(mktemp);ssh-keyscan -t ed25519 github.com 2>/dev/null > "$scanned"
    [ "$(ssh-keygen -lf "$scanned" | awk '{print $2}')" = "$GITHUB_ED25519" ] || { rm -f "$scanned";die 'La clave recibida de github.com no coincide con la publicada por GitHub. No se continúa.'; }
    cat "$scanned" >> /root/.ssh/known_hosts;rm -f "$scanned"
fi
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes"
if ! git ls-remote "$REPO" "$BRANCH" >/dev/null 2>&1; then
    cat <<EOF

El servidor todavía no puede leer el repositorio. Añade esta clave pública en GitHub:
  $REPO → Settings → Deploy keys → Add deploy key
  Título: servidor $(hostname) · deja SIN marcar «Allow write access»

$(cat "$KEY.pub")

Después vuelve a ejecutar este mismo comando.
EOF
    exit 2
fi

step "Código ($BRANCH)"
if [ -d "$APP/.git" ]; then
    # El servidor no guarda cambios propios: siempre refleja la rama publicada.
    git -C "$APP" fetch -q origin "$BRANCH"
    git -C "$APP" checkout -q -B "$BRANCH" "origin/$BRANCH"
    git -C "$APP" reset -q --hard "origin/$BRANCH"
else
    git clone -q --branch "$BRANCH" "$REPO" "$APP"
fi
if [ -n "$COMMIT" ]; then
    git -C "$APP" merge-base --is-ancestor "$COMMIT" "origin/$BRANCH" 2>/dev/null || die "El commit ${COMMIT} no pertenece a la rama ${BRANCH}."
    git -C "$APP" reset -q --hard "$COMMIT"
fi
git -C "$APP" log -1 --format='Versión: %h · %ci · %s'

step 'Dependencias: Python (Waitress, VERI*FACTU), Node y Chromium para los PDF'
cd "$APP"
sh scripts/setup-server.sh
npm ci --omit=dev --no-audit --no-fund
PLAYWRIGHT_BROWSERS_PATH="$APP/browsers" npx playwright install --with-deps chromium
chmod -R a+rX "$APP"

step 'Servicio systemd'
if [ -n "$DOMAIN" ]; then
    sed "s#^Environment=ADG_PUBLIC_ORIGIN=.*#Environment=ADG_PUBLIC_ORIGIN=https://$DOMAIN#" deploy/adg-finance.service.example > /etc/systemd/system/$SERVICE.service
else
    # Sin dominio solo se admite el acceso local (túnel SSH).
    sed '/^Environment=ADG_PUBLIC_ORIGIN=/d' deploy/adg-finance.service.example > /etc/systemd/system/$SERVICE.service
fi
printf 'DOMAIN=%s\nMODE=%s\nBRANCH=%s\nREPO=%s\n' "$DOMAIN" "$MODE" "$BRANCH" "$REPO" > "$SETTINGS"
systemctl daemon-reload
systemctl enable -q "$SERVICE"
systemctl restart "$SERVICE"
for _ in $(seq 60);do curl -fs http://127.0.0.1:4173/api/auth/session >/dev/null && break;sleep 0.5;done
curl -fs http://127.0.0.1:4173/api/auth/session >/dev/null || { journalctl -u "$SERVICE" -n 40 --no-pager;die 'La aplicación no responde. Revisa el registro anterior.'; }
echo 'La aplicación responde en 127.0.0.1:4173.'

TUNNEL_UNIT=/etc/systemd/system/cloudflared.service
if [ "$MODE" = cloudflare ]; then
    step 'Cloudflare Tunnel'
    if ! command -v cloudflared >/dev/null; then
        install -d -m 0755 /usr/share/keyrings
        curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
        echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' > /etc/apt/sources.list.d/cloudflared.list
        apt-get update -q && apt-get install -y -q cloudflared
    fi
    TOKEN=${CLOUDFLARE_TUNNEL_TOKEN:-}
    if [ -f "$TUNNEL_UNIT" ] && [ -z "$TOKEN" ]; then
        echo 'El túnel ya está instalado: se conserva su token.'
    else
        if [ -z "$TOKEN" ] && [ -t 0 ];then read -rsp 'Pega el token del túnel (Cloudflare → Zero Trust → Networks → Tunnels) y pulsa Intro: ' TOKEN;echo;fi
        [ -n "$TOKEN" ] || die 'Falta el token del túnel de Cloudflare. Ver deploy/GUIA-SERVIDOR.md.'
        printf '%s' "$TOKEN" | grep -Eq '^[A-Za-z0-9+/=_-]{40,}$' || die 'El token no parece válido: copia solo la cadena larga que aparece tras «--token» en Cloudflare.'
        [ -f "$TUNNEL_UNIT" ] && cloudflared service uninstall >/dev/null 2>&1 || true
        cloudflared service install "$TOKEN" >/dev/null
        # La unidad contiene el token: solo root la puede leer.
        chmod 600 "$TUNNEL_UNIT";systemctl daemon-reload
    fi
    systemctl enable -q --now cloudflared;systemctl restart cloudflared
    for _ in $(seq 30);do systemctl is-active -q cloudflared && break;sleep 1;done
    systemctl is-active -q cloudflared || { journalctl -u cloudflared -n 30 --no-pager;die 'El túnel de Cloudflare no arranca. Revisa el token.'; }
    echo 'Túnel de Cloudflare activo.'
elif [ -f "$TUNNEL_UNIT" ]; then
    step 'Retirar Cloudflare Tunnel'
    cloudflared service uninstall >/dev/null 2>&1 || true
fi

step 'Caddy y cortafuegos'
for port in $(sshd -T 2>/dev/null | awk '/^port /{print $2}');do ufw allow "$port/tcp" >/dev/null;done
ufw allow OpenSSH >/dev/null
if [ "$MODE" = caddy ]; then
    sed "s#^finance\.empresa\.es {#$DOMAIN {#" deploy/Caddyfile.example > /etc/caddy/Caddyfile
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
    ufw allow 80/tcp >/dev/null;ufw allow 443/tcp >/dev/null
    systemctl enable -q --now caddy;systemctl reload caddy
else
    # Con Cloudflare Tunnel la conexión sale del servidor: no hace falta ningún puerto de entrada.
    ufw delete allow 80/tcp >/dev/null 2>&1 || true;ufw delete allow 443/tcp >/dev/null 2>&1 || true
    systemctl disable -q --now caddy 2>/dev/null || true
fi
ufw --force enable >/dev/null
ufw status | sed 's/^/  /'

step 'Listo'
if [ "$MODE" = cloudflare ]; then
    echo "En Cloudflare, el túnel debe tener el nombre público $DOMAIN → servicio HTTP 127.0.0.1:4173."
    echo "Después abre https://$DOMAIN"
elif [ "$MODE" = caddy ]; then
    echo "Abre https://$DOMAIN (el DNS del dominio debe apuntar a este servidor para que Caddy obtenga el certificado)."
else
    echo 'La aplicación no está expuesta a Internet. Desde tu ordenador:'
    echo "  ssh -L 4173:127.0.0.1:4173 USUARIO@$(hostname -I | awk '{print $1}')"
    echo '  y abre http://localhost:4173'
fi
[ -f "$DATA/finance.sqlite" ] || echo 'Instalación sin datos: traslada los del Mac con deploy/migrate-data.sh o crea el primer administrador por el túnel.'
