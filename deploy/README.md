# Preparación para un servidor futuro

La aplicación funciona ahora en el equipo local. Estos archivos son ejemplos de configuración; no se ha contratado un servidor, conectado un dominio ni publicado datos.

**Antes de publicar hay que sustituir el motor HTTP de desarrollo.** `serve.py` usa `http.server`, que [Python desaconseja para producción](https://docs.python.org/3/library/http.server.html). Se han probado y reforzado sus controles para uso local, pero poner Caddy delante no convierte ese motor en un servidor de producción. Debe adaptarse la API a WSGI/ASGI y ejecutarse con un servidor de producción; el servicio de ejemplo actual sirve únicamente para ensayar el traslado en un entorno privado. No constituye un despliegue público terminado.

La misma base de datos puede usarse en un único servidor de la empresa, con cuentas individuales desde varios ordenadores. La API deberá escuchar en `127.0.0.1:4173`; Caddy recibirá HTTPS y enviará las solicitudes a ese puerto local. `ADG_PUBLIC_ORIGIN` declara el origen HTTPS permitido y activa la cookie de sesión `Secure` para ese dominio. Se mantienen las comprobaciones de origen y permisos en cada solicitud.

## Dimensionamiento inicial

Para esta empresa, el punto de partida estimado es un VPS en la Unión Europea con 2 vCPU, 4 GB de RAM y 40 GB de SSD persistente, Linux LTS y un único proceso de aplicación. SQLite y el directorio de justificantes deben residir en disco local persistente; la aplicación actual no es un sitio estático ni está preparada para réplicas simultáneas. La conservación de documentos requiere también Node.js LTS y Playwright. Para los PDF debe estar instalado Chrome/Chromium; se generan en el propio servidor, con un máximo de dos trabajos simultáneos.

OVHcloud anuncia [VPS-1 desde 3,81 €/mes sin IVA](https://www.ovhcloud.com/es-es/vps/) con esos recursos; VPS-2 ofrece 4 vCPU, 8 GB y 75 GB desde 7,21 €/mes sin IVA. Precios consultados el 17/10/2026, sujetos a región, disponibilidad y contratación. Un presupuesto orientativo de 10–20 €/mes para VPS, dominio y copia externa deja margen; no incluye trabajo de administración. El proveedor incluye una copia diaria con las últimas 24 horas: no sustituye una copia externa con retención y restauración ensayada.

Abrir solamente HTTP/HTTPS para Caddy y restringir SSH. Mantener la API y SQLite fuera del acceso directo a Internet. Configurar actualizaciones, reinicio del servicio, alertas de espacio/memoria y una copia diaria externa cifrada del estado y los justificantes, con retención de al menos 30 días. La copia SQLite debe generarse con su API de backup o con la aplicación detenida; no copiar solamente el archivo principal mientras hay escrituras WAL. Conservar y ensayar también la recuperación de las cuentas.

Las pruebas sintéticas en el Mac local incluyeron 5.000 facturas y 3.334 cobros, 10 lectores concurrentes y una terminación forzada durante una escritura. No son una medición del VPS: al contratarlo hay que repetir la carga con el motor de producción y comprobar memoria, latencia, copias, restauración y permisos desde fuera de la oficina. El informe está en [reviews/2026-10-17-fallos-y-capacidad.md](../reviews/2026-10-17-fallos-y-capacidad.md).

## Cuando exista el servidor

1. Completar la adaptación a un servidor HTTP de producción y sus pruebas de permisos, concurrencia y recuperación. Instalar Python 3.10 o posterior, Node.js LTS y Caddy, crear el usuario de servicio `adg-finance` y los directorios `/opt/adg-finance` y `/var/lib/adg-finance`, con acceso a los datos únicamente para el usuario de servicio.
2. Copiar el código a `/opt/adg-finance`, sin `node_modules`, pruebas, previsualizaciones ni datos de ejemplo privados ajenos a la empresa. Conservar `backend/template-example.json`, que se sirve únicamente a administradores del emisor original, y el directorio `scripts/` con el generador de documentos. Ejecutar `npm ci --omit=dev` e instalar Chromium con `PLAYWRIGHT_BROWSERS_PATH=/opt/adg-finance/browsers npx playwright install --with-deps chromium`; la ruta debe ser legible por el usuario de servicio. También se puede configurar `CHROME_PATH` con una instalación de Chrome compatible.
3. Para trasladar también las cuentas: detener la aplicación original y copiar **todo** su directorio `data/` al nuevo `/var/lib/adg-finance`, incluidos SQLite, sus archivos auxiliares si existen y los justificantes. Guardar una copia previa. La copia ZIP descargable de facturación conserva los datos financieros; los usuarios se conservan por separado en SQLite y no se sustituyen al restaurar ese ZIP.
4. En el servidor, ejecutar `ADG_DATA_DIR=/var/lib/adg-finance python3 /opt/adg-finance/manage_users.py revoke-sessions` con el usuario de servicio. Las personas volverán a entrar con sus cuentas existentes.
5. Adaptar el dominio en ambos archivos de ejemplo. Apuntar su DNS al servidor y permitir HTTPS para Caddy. Mantener el puerto Python accesible únicamente desde el propio servidor.
6. Actualizar `ExecStart` al motor de producción verificado antes de instalar el servicio y la configuración de Caddy. Caddy obtiene y renueva los certificados cuando el dominio y la conectividad están preparados. Las cuentas, facturas, cobros y permisos siguen funcionando en el mismo origen.
7. Verificar acceso de administrador y usuario normal desde dos equipos y configurar una copia externa del directorio de datos, con acceso restringido. La copia diaria local de SQLite contiene también las cuentas, los emisores, los accesos y los documentos conservados; los justificantes se copian junto con `data/attachments/`.

Para una instalación vacía, crear el primer administrador desde el propio servidor mediante un túnel SSH: `ssh -L 4173:127.0.0.1:4173 usuario@servidor` y abrir `http://localhost:4173` en el ordenador del administrador. El alta inicial se restringe al acceso local. Después las demás cuentas se crean en Usuarios.

La referencia de Excel de Downloads es una comodidad del equipo actual. En el servidor se importa el Excel seleccionando el archivo desde el navegador.

Referencias de configuración: [proxy inverso de Caddy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [HTTPS automático](https://caddyserver.com/docs/automatic-https).

## Adaptador experimental VERI*FACTU

Instalar Python con soporte de entornos virtuales y ejecutar `sh scripts/setup-verifactu.sh` en el directorio del programa. Para ensayos privados, utilizar `.venv/bin/python` al arrancar el servidor; el ejemplo de servicio refleja ese intérprete. Conservar el directorio `backend/verifactu_specs/` con los esquemas fijados. El adaptador continúa limitado a preproducción aunque se configure un dominio HTTPS.

La recuperación completa requiere también `ADG_DATA_DIR/vf-secrets/master.key`, además de SQLite y justificantes. Esa clave permite abrir los certificados cifrados: debe formar parte de la copia externa cifrada y restringida del directorio de datos; no se incluye en el ZIP financiero por emisor. Ver [alcance y pruebas](../reviews/2026-10-19-verifactu-experimental.md).
