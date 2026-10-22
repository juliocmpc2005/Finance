# Guía del servidor de la oficina

Plan acordado el 22/10/2026 para llevar arquitecturadeguardia Finance del Mac a un servidor propio en la oficina, accesible desde fuera con un subdominio de la web de la empresa. Recoge las decisiones, sus motivos y los pasos. Los detalles técnicos de la instalación están en [README.md](README.md) (esta misma carpeta).

## Resumen de decisiones

| Tema | Decisión | Motivo |
|---|---|---|
| Sistema | **Ubuntu Server 24.04 LTS**, sin escritorio | Estable, soporte hasta 2029, Playwright/Chromium con soporte oficial |
| Equipo | Intel i3 de 5.ª/6.ª generación, **12 GB de RAM**, **SSD** | Suficiente con margen (ver «El equipo») |
| Acceso desde fuera | **Cloudflare Tunnel** | Sin abrir puertos ni depender de la IP de Orange |
| Dirección | Un **subdominio** del dominio de la web, p. ej. `finance.tudominio.es` | La web sigue funcionando igual en `tudominio.es` |
| Código | Se descarga de **GitHub** (`juliocmpc2005/Finance`, rama `main`) con una clave de solo lectura | Actualizar es publicar en GitHub y volver a ejecutar el script |
| Datos | Se **trasladan los del Mac** (cuentas, facturas, justificantes, claves) | Se sigue trabajando con lo que ya hay |
| Coste añadido | **0 €** | Ver «Costes» |

## Por qué Ubuntu Server 24.04 LTS

La aplicación necesita Python 3.10+, Node.js LTS, **Chromium (Playwright) para generar los PDF**, systemd y, opcionalmente, Caddy.

- **Playwright da soporte oficial a Ubuntu y Debian**: `npx playwright install --with-deps chromium` instala el navegador y todas sus librerías. Es la pieza más delicada.
- Python 3.12 incluido; `cryptography` y `lxml` (VERI*FACTU) se instalan precompilados.
- Actualizaciones de seguridad automáticas (`unattended-upgrades`) que **no cambian versiones**, solo corrigen fallos.
- Alternativa igual de válida: **Debian 13**.

Descartadas:

- **Arch Linux (y derivadas)**: es *rolling release*. Un `pacman -Syu` puede subir Python de versión y dejar inservible el entorno `.venv` (el servicio no arrancaría), o actualizar Chromium y romper los PDF sin aviso. No conviene actualizarlo sin supervisión y Playwright no lo soporta oficialmente. Es excelente como equipo de trabajo, no para un servidor que debe funcionar solo.
- **Ubuntu 26.04**: también LTS, pero más reciente; Playwright tarda unos meses en dar soporte oficial a cada versión nueva (no comprobado para 26.04).
- **Alpine**: Chromium de Playwright no funciona en Alpine.
- **Rocky / Alma / RHEL**: funcionan, pero hay que buscar a mano las dependencias de Chromium.

## El equipo

Intel i3 de 5.ª o 6.ª generación (2 núcleos / 4 hilos), 12 GB de RAM y SSD: **va sobrado**.

- Consumo aproximado: Ubuntu Server ~500 MB, la aplicación 100–200 MB y cada Chromium que genera un PDF 200–300 MB (máximo dos a la vez). Quedan más de 10 GB libres.
- El SSD es lo más importante para SQLite y las copias diarias.
- Instalar la edición **Server, sin escritorio**.
- Antes de instalar, revisar la salud del disco (es un equipo de 2015–2016): `sudo apt install smartmontools && sudo smartctl -a /dev/sda` (o `/dev/nvme0`).
- Recomendado: un **SAI** pequeño para evitar apagados bruscos por cortes de luz.
- En el router, **reservar una IP fija** para el servidor dentro de la oficina (por ejemplo `192.168.1.10`), para administrarlo siempre en la misma dirección.

## Red: dominio, subdominio y Cloudflare

### La web y la aplicación con el mismo dominio

Un dominio admite todos los subdominios que se quieran, **sin coste**. Solo hay que añadir un registro DNS; los de la web no se tocan.

| Dirección | Destino |
|---|---|
| `tudominio.es`, `www.tudominio.es` | La página web, donde esté alojada ahora (sin cambios) |
| `finance.tudominio.es` | El servidor de la oficina, a través del túnel |

(No confundir con la sección «Subdominios» de algunos alojamientos, que sirve para crear otra web alojada allí y puede tener límites. Aquí solo hace falta un registro DNS.)

### Por qué Cloudflare Tunnel

La conexión de **Orange** suele tener IP pública **dinámica** (puede cambiar al reiniciar el router), y algunas conexiones están detrás de CG-NAT, donde abrir puertos no funciona. Con Cloudflare Tunnel el servidor **sale** a conectarse con Cloudflare:

```
Usuario → https://finance.tudominio.es → Cloudflare → (túnel cifrado) → servidor de la oficina
```

- No se abren puertos en el router.
- No hace falta DNS dinámico: si la IP cambia, el túnel se reconecta solo. Funciona también con CG-NAT.
- La IP de la oficina no se publica y Cloudflare filtra ataques antes de que lleguen.

**Requisito:** Cloudflare debe gestionar el **DNS** del dominio. No se cambia de registrador ni se deja de pagar el dominio donde está: solo se cambian sus **servidores de nombres** (nameservers). Cloudflare copia los registros existentes al dar de alta el dominio; **antes de cambiar los nameservers hay que comprobar que están todos**, en especial los de la web (A/CNAME de `@` y `www`) y los **MX del correo**, si el dominio tiene correo.

A tener en cuenta:

| Punto | Detalle |
|---|---|
| Cloudflare ve el tráfico | Descifra las conexiones en su red, por lo que técnicamente ve los datos en tránsito. Es habitual y Cloudflare actúa como encargado del tratamiento (RGPD), pero es un tercero. |
| Subidas de hasta 100 MB | Límite del plan gratuito. Solo afectaría a restaurar una copia ZIP muy grande (la actual ronda 22 MB). |
| Dependencia | Si Cloudflare falla (poco frecuente), no se entra desde fuera; en la oficina se puede seguir por túnel SSH. |

### Costes

| Concepto | Coste |
|---|---|
| Subdominio | 0 € (incluido en el dominio que ya se paga) |
| Cloudflare: DNS, Tunnel, HTTPS y protección | 0 € (plan Free) |
| Cloudflare Access (capa extra opcional) | 0 € hasta 50 usuarios |
| Ubuntu Server | 0 € |
| Dominio y alojamiento de la web | Lo mismo que ahora, en el proveedor actual |

Al darse de alta en Cloudflare Zero Trust a veces se pide elegir plan o una tarjeta aunque se elija el gratuito; no cobra mientras se mantenga el plan Free.

### Alternativas que se valoraron

- **Abrir puertos 80/443 en el router + Caddy** (`install-ubuntu.sh --domain … --caddy`): requiere que Orange no use CG-NAT (comparar la IP WAN del router con la de ifconfig.me) y DNS dinámico (p. ej. DuckDNS con un CNAME `finance` → `nombre.duckdns.org`). Expone la IP de la oficina. Puede fallar el acceso desde dentro si el router no hace *NAT loopback*.
- **Tailscale**: red privada gratuita; cada equipo instala Tailscale. Muy seguro, pero no hay dirección pública.

## Paso a paso

### 1. Cloudflare: dominio

1. Crear una cuenta gratuita en cloudflare.com y **añadir el dominio** (plan Free).
2. Revisar la lista de registros DNS importados: web (`@`, `www`) y correo (`MX`, y los `TXT` de SPF/DKIM si existen). Añadir los que falten comparando con el panel del proveedor actual.
3. En el panel del **registrador** del dominio, sustituir los servidores de nombres por los dos que indica Cloudflare.
4. Esperar a que Cloudflare marque el dominio como **Activo** (minutos u horas) y comprobar que la web y el correo siguen funcionando.

### 2. Cloudflare: túnel

1. Cloudflare → **Zero Trust → Networks → Tunnels → Create a tunnel** → tipo **Cloudflared**. Nombre, por ejemplo, `oficina`.
2. En la pantalla de instalación aparece un comando con `--token` seguido de una cadena larga: **copiar solo esa cadena** (el token). No instalar nada todavía.
3. En **Public Hostname** (o *Published application routes*): subdominio `finance`, dominio `tudominio.es`, servicio **HTTP**, URL **`127.0.0.1:4173`**.

### 3. Instalar Ubuntu Server en el equipo

**Se borra todo el disco del equipo**: copiar antes lo que se quiera conservar.

1. **Descargar** Ubuntu Server 24.04.x LTS (`.iso`, ~3 GB) desde ubuntu.com/download/server (versión *Server*, no *Desktop*).
2. **Crear el USB** (4 GB o más, se borra) en el Mac con **balenaEtcher** (etcher.balena.io): *Flash from file* → el `.iso` → *Select target* → el USB (comprobar que no es otro disco) → *Flash*.
3. **Arrancar desde el USB**: conectar USB, **cable de red**, monitor y teclado. Al encender, pulsar la tecla del menú de arranque (**F12** Dell/Lenovo, **F9** HP, **F11** o **Esc**; si no, entrar en la BIOS con **F2**/**Supr** y poner el USB primero). Elegir la opción **UEFI** del USB → *Try or Install Ubuntu Server*. No hace falta desactivar Secure Boot.
4. **Instalador**:

| Pantalla | Elección |
|---|---|
| Idioma / teclado | Español / Spanish |
| Tipo | **Ubuntu Server** (no *minimized*) |
| Red | DHCP con cable; **apuntar la IP** (`192.168.1.x`) |
| Proxy / mirror | Vacío / el propuesto |
| Almacenamiento | **Use an entire disk** (el SSD) con **LVM**. En el resumen, si `ubuntu-lv` no ocupa todo el disco (queda *free space*): `ubuntu-lv` → *Edit* → tamaño máximo → *Save*. *Done* → *Continue* (borra el disco) |
| Perfil | Nombre del servidor `finance-oficina`, un usuario (p. ej. `julio`) y una contraseña larga |
| Ubuntu Pro | *Skip for now* |
| SSH | **Install OpenSSH server** · *Import SSH identity* → **from GitHub** → `juliocmpc2005` (entrar desde el Mac con la misma clave que GitHub, sin contraseña) |
| Featured snaps | Ninguno |

5. Al terminar: *Reboot Now* y **quitar el USB**.
6. En el servidor, ver la IP con `ip -4 a` y **reservarla en el router** (Livebox de Orange, `192.168.1.1`, sección DHCP/IP estática), por ejemplo `192.168.1.10`.
7. Desde el Mac: `ssh julio@192.168.1.10` (a partir de aquí ya no hacen falta monitor ni teclado).
8. Actualizar y revisar el disco:

```sh
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y smartmontools && sudo smartctl -H /dev/sda   # o /dev/nvme0; debe decir PASSED
```

### 4. Publicar la versión en GitHub

El servidor instala la rama `main` publicada en GitHub, no los cambios del Mac: antes de instalar o actualizar, hacer commit y `git push` de lo que se quiera llevar al servidor.

### 5. Instalar

Desde la carpeta del proyecto en el Mac:

```sh
scp deploy/install-ubuntu.sh usuario@192.168.1.10:
ssh -t usuario@192.168.1.10 sudo bash install-ubuntu.sh --domain finance.tudominio.es --cloudflare
```

- La primera vez muestra una **clave pública**: añadirla en GitHub → repositorio → **Settings → Deploy keys → Add deploy key**, **sin** marcar «Allow write access», y repetir el comando.
- Después pide el **token del túnel** (no se ve al pegarlo). Solo se pide la primera vez.
- Hace falta `ssh -t` para que pueda pedir el token.
- El script deja: actualizaciones automáticas de seguridad, Node.js 24, usuario `adg-finance`, código en `/opt/adg-finance`, datos en `/var/lib/adg-finance` (solo accesibles para la aplicación), Chromium para los PDF, servicio `adg-finance`, servicio `cloudflared` y cortafuegos con **solo SSH** abierto.

### 6. Trasladar los datos del Mac

1. Detener la aplicación del Mac (`Ctrl+C` en la terminal de `npm start`).
2. Ejecutar en el Mac: `bash deploy/migrate-data.sh usuario@192.168.1.10`

Copia SQLite de forma consistente (comprueba su integridad), justificantes, documentos, copias diarias y `vf-secrets/master.key` (clave que protege el certificado de VERI*FACTU y la contraseña del correo). Si el servidor ya tenía datos, los conserva en `/var/lib/adg-finance.antes-FECHA`. Cierra todas las sesiones: cada persona vuelve a entrar con su cuenta. **A partir de ahí se trabaja solo en el servidor**; el Mac deja de estar sincronizado.

### 7. Comprobar

- Abrir `https://finance.tudominio.es` desde la oficina y desde fuera (por ejemplo, el móvil con datos).
- Entrar como administrador y como usuario normal.
- Descargar el PDF de una factura (prueba Chromium).
- En Configuración → Correo de envío, **Probar conexión** y enviar una factura a un correo propio.
- Ver «Pendiente» para la comprobación del límite de intentos de acceso.

### 8. Opcional: Cloudflare Access

Zero Trust → **Access → Applications → Add an application → Self-hosted** con `finance.tudominio.es` y una política que permita los correos de la empresa. Antes de ver la pantalla de acceso, cada persona confirma su correo con un código. Gratis hasta 50 usuarios.

## Uso diario y mantenimiento

| Tarea | Cómo |
|---|---|
| Actualizar la aplicación | Publicar los cambios en `main` de GitHub y ejecutar en el servidor `sudo bash /opt/adg-finance/deploy/install-ubuntu.sh` (recuerda dominio y modo) |
| Reiniciar la aplicación | `sudo systemctl restart adg-finance` |
| Ver el registro | `journalctl -u adg-finance -n 100` · túnel: `journalctl -u cloudflared -n 100` |
| Estado | `systemctl status adg-finance cloudflared` |
| Entrar sin Internet / sin Cloudflare | Desde un equipo de la oficina: `ssh -L 4173:127.0.0.1:4173 usuario@192.168.1.10` y abrir `http://localhost:4173` |
| Volver a abrir puertos con Caddy | `install-ubuntu.sh --domain finance.tudominio.es --caddy` (retira el túnel) |
| Cerrar el acceso externo | `install-ubuntu.sh --no-domain` |

Ubuntu instala solo las actualizaciones de seguridad. Algunas (kernel) necesitan reiniciar: revisar de vez en cuando si existe `/var/run/reboot-required` y reiniciar fuera de horario.

**Después de cualquier cambio de código hay que reiniciar el servicio** (el script lo hace). En el Mac pasa lo mismo con `npm start`: un servidor arrancado antes de un cambio no conoce las rutas nuevas y muestra «Ruta no encontrada».

## Copias de seguridad

Lo que ya hace la aplicación:

- Copia diaria de SQLite en `/var/lib/adg-finance/backups/` (últimas 14), con comprobación de integridad.
- Configuración → **Descargar copia**: ZIP por emisor con facturas, cobros, justificantes y documentos.

**Lo que falta y es imprescindible en un equipo de oficina:** una **copia diaria fuera del servidor** (disco externo rotatorio o almacenamiento en la nube cifrado), con al menos 30 días de retención, que incluya todo `/var/lib/adg-finance` — SQLite, `attachments/` y **`vf-secrets/master.key`** (sin ella no se pueden leer el certificado de VERI*FACTU ni la contraseña del correo). Ensayar la restauración. Sin esto, un fallo de disco, un robo o un incendio supondrían perderlo todo.

## Correo de envío con Gmail

1. myaccount.google.com → **Seguridad** → activar la **Verificación en dos pasos**.
2. myaccount.google.com/apppasswords → crear una **contraseña de aplicación** (nombre «Facturas») y copiar las 16 letras **sin espacios**.
3. En la aplicación, Configuración → **Correo de envío**:

| Campo | Valor |
|---|---|
| Servidor SMTP | `smtp.gmail.com` |
| Seguridad | SSL/TLS |
| Puerto | 465 |
| Usuario | la dirección completa |
| Contraseña | la contraseña de aplicación |
| Correo del remitente | la misma dirección |

4. **Guardar correo** → **Probar conexión** → enviar una factura a un correo propio.

Errores habituales: «ha rechazado el usuario o la contraseña» → se usó la contraseña normal o se copiaron los espacios. Sin opción de contraseñas de aplicación → falta la verificación en dos pasos (o la cuenta de Google Workspace lo tiene desactivado). Límite aproximado de Gmail: 500 correos al día.

## Funciones añadidas en esta etapa

Detalle en el [README principal](../README.md):

- **Enviar por correo** las facturas emitidas, con el PDF conservado, desde la cuenta SMTP de cada emisor; registro de envíos.
- **Eliminar** borradores y facturas de ejemplo; **anular** facturas emitidas (solo administradores), que se conservan en la pestaña «Anuladas». VERI*FACTU no se puede eliminar ni anular.
- El **número de una factura anulada queda libre**: si era la última de su serie, la siguiente factura lo reutiliza; si era intermedia, se puede asignar a mano. Conviene confirmarlo con la gestoría si la factura ya llegó al cliente (la numeración debe ser correlativa y única).
- VERI*FACTU · pruebas: un alta ya anulada o subsanada deja de ofrecer «Subsanar» y «Anular» y muestra «Anulado el …».

## Pendiente

- [x] Unir la rama `correo-anulaciones-despliegue` a `main` y subirla a GitHub (hecho el 22/10/2026: commits `0fd8069` y `30b5366`; `node_modules` ya no se versiona).
- [ ] **Probar `install-ubuntu.sh` en un Ubuntu 24.04 real**: solo se ha comprobado la sintaxis y la lógica de opciones; el empaquetado de `migrate-data.sh` sí se probó con los datos reales (sin enviarlos).
- [ ] **Comprobar a través de Cloudflare** que el límite de intentos de acceso se aplica a cada persona y no a toda la oficina: la aplicación toma la IP de la cabecera `X-Forwarded-For` de las conexiones locales, que Cloudflare debería enviar a través del túnel. Prueba: varios intentos fallidos desde el móvil no deben bloquear el acceso desde la oficina.
- [ ] Configurar la **copia externa** diaria y ensayar una restauración.
- [ ] Decidir el **formato del número en la factura** («2026-59» en lugar de «ADG-4T-2026-59»): quedaron abiertas cuatro dudas — mostrar la serie en pequeño o no, formato de las rectificativas («R-2026-01»), qué referencia pedir para la transferencia y si se aplica solo a facturas nuevas. La serie debe constar en la factura según el Reglamento de facturación (art. 6.1.a).
- [ ] Opcionales comentados: «des-anular» una factura; ocultar el puerto en la configuración del correo (deducirlo de la seguridad).
