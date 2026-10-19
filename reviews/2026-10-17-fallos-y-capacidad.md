# Revisión de fallos y capacidad · 17 de octubre de 2026

Se revisó la aplicación local y se corrigieron los errores encontrados mediante pruebas adversas reproducibles. Todas las altas, importaciones, cobros, restauraciones y caídas deliberadas de estas pruebas utilizaron directorios temporales y servidores separados. No se cargaron datos de prueba en la empresa del usuario.

## Hosting y requisitos propuestos

Punto de partida estimado para esta pequeña empresa: un único VPS en la Unión Europea, Linux LTS, 2 vCPU, 4 GB de RAM y 40 GB de SSD persistente. Python 3.10 o posterior, SQLite y justificantes en disco local, Caddy para HTTPS y un servicio que reinicie la aplicación tras un fallo. No se necesitan Node ni las herramientas de pruebas para ejecutar la aplicación.

Elegiría [OVHcloud VPS-1](https://www.ovhcloud.com/es-es/vps/): ofrece esos recursos desde 3,81 €/mes sin IVA. VPS-2 ofrece 4 vCPU, 8 GB y 75 GB desde 7,21 €/mes sin IVA. Son precios de partida consultados el 17/10/2026: comprobar región, permanencia, disponibilidad e impuestos al contratar. Reservaría aproximadamente 10–20 €/mes de infraestructura, incluyendo margen para dominio y copia externa; es una estimación propia, sin mantenimiento humano. La copia diaria del proveedor, con las últimas 24 horas, no sustituye una copia externa con retención.

Requisitos operativos: dominio propio, HTTPS, SSH restringido, API únicamente en loopback, actualizaciones, alertas de espacio y memoria, copias diarias externas cifradas con al menos 30 días de retención y un ensayo de restauración. Las copias deben incluir las cuentas y los justificantes, además de la facturación. No copiar únicamente `finance.sqlite` con la aplicación escribiendo en WAL: usar la API de backup de SQLite o detener el servicio.

**Pendiente antes de publicar:** adaptar la API a un motor WSGI/ASGI de producción. El actual `serve.py` utiliza `http.server`; la [documentación de Python](https://docs.python.org/3/library/http.server.html) lo desaconseja expresamente para producción. Caddy delante no elimina este requisito. Los ejemplos de `deploy/` sirven para ensayar el traslado en privado; se ha aclarado esta limitación en su guía y en el servicio de ejemplo. No se ha contratado ni publicado ningún servidor.

## Errores comprobados y corregidos

- Una copia automática fallida podía devolver un error después de que la escritura financiera ya estuviera confirmada. Ahora distingue el guardado correcto de la copia fallida, devuelve un aviso persistente y permite descargar una copia. Las copias diarias dañadas se vuelven a generar y se comprueba su integridad.
- Una respuesta HTTP perdida podía hacer que un nuevo intento registrase dos anticipos. Los comandos llevan un identificador de operación, confirmado en la misma transacción que el dinero. El reintento del mismo formulario conserva ese identificador; cambiar sus parámetros reutilizando el identificador se rechaza.
- Los reintentos de concurrencia del navegador se agotaban con cinco usuarios guardando a la vez. Se reprodujo el fallo con cinco navegadores desde la misma revisión: dos quedaban bloqueados. Con los reintentos limitados y espera variable, los cinco guardan y emiten. Los cambios incompatibles sobre la misma factura siguen bloqueándose para revisión.
- Se podían alterar campos de facturas emitidas mediante el guardado genérico del administrador. Ahora se rechazan esos cambios: renumeración y rectificación conservan sus operaciones específicas y su historial.
- Una restauración manipulada podía contener devoluciones superiores a lo cobrado de ese pago o repartos excesivos ocultos por anulaciones posteriores. Se valida la cronología de cada ingreso y cada familia de rectificativas, además del saldo actual.
- JSON con estructura incorrecta, colecciones nulas, cuerpos HTTP truncados y ZIP dañados provocaban errores internos o validaciones insuficientes. Ahora se rechazan de forma controlada, incluyendo claves JSON repetidas, valores no finitos, profundidad excesiva, CRC erróneo, archivos repetidos y justificantes ausentes o de formato inválido.
- Un fallo de metadatos tras subir un justificante dejaba un archivo huérfano. Un fallo de restauración podía dejar archivos nuevos. Ambas operaciones limpian sus archivos nuevos al fallar y preservan los originales.
- Un cliente lento podía retener el bloqueo global de datos durante el envío de una respuesta. Los envíos se realizan después de liberar ese bloqueo; se establecen tiempos de espera y un máximo de 32 conexiones activas, con rechazo temporal del exceso.
- El aviso para descargar trabajo sin guardar podía desaparecer al cambiar de vista. Ahora permanece y la descarga contiene el texto pendiente en memoria. La recuperación de un usuario normal se identifica como parcial y se impide usarla para sustituir toda la empresa.
- Las previsualizaciones y las copias diarias crecían sin una retención acotada. Se conservan 3 previsualizaciones de restauración, 20 de importación y 14 copias SQLite diarias; las copias manuales previas a cambios quedan fuera de esa limpieza.
- La validación repetía barridos de toda la empresa por cada fecha. Ahora agrupa movimientos por ingreso y familia. En la muestra local de 1.000 facturas sin cobros pasó de aproximadamente 1,91 s a 0,010 s. Los saldos optimizados se contrastan con un cálculo independiente en 320 escenarios de fechas.

## Pruebas finales

Comandos ejecutados sobre la versión final:

```sh
npm test
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm run test:browser
```

Resultado: **26 pruebas JavaScript y 57 pruebas Python aprobadas**, además de toda la batería de navegador. Python incluye 20 pruebas de fallos con múltiples subcasos y dos pruebas adicionales de consistencia financiera. Los errores 400/403/408/409/500/503 inyectados intencionadamente son parte de las comprobaciones; no son fallos de la batería.

Tras verificar una copia SQLite previa, se reinició la aplicación local con las correcciones. La revisión y el hash del estado financiero, así como el número de cuentas, permanecieron idénticos antes y después del reinicio; SQLite pasó `integrity_check`. La API financiera, el ejemplo privado y la firma siguen rechazando las solicitudes sin sesión. No se creó ninguna cuenta de prueba en la instalación real.

El navegador cubre creación, validación, emisión, PDF, plantilla, clientes, móvil, análisis, pago parcial, varios pagos por factura, cobros compartidos, anticipos, importación revisada y sin duplicados, justificantes, ZIP y restauración, renumeración, usuarios y permisos, cambio de contraseña, revocación, cierre entre pestañas, respuestas perdidas y recuperación de trabajo sin conexión. Se añadió una prueba que fuerza cinco usuarios a guardar desde la misma revisión y emitir con números distintos.

Prueba adicional de volumen y caída, ejecutada con datos ficticios:

```sh
python3 tests/stress-server.py
```

| Histórico sintético | Cobros | Lectores simultáneos | Peticiones | Mediana de lectura | Percentil 95 | Errores |
|---|---:|---:|---:|---:|---:|---:|
| 100 facturas | 67 | 10 | 40 | 16,6 ms | 18,3 ms | 0 |
| 1.000 facturas | 667 | 10 | 40 | 107,4 ms | 134,6 ms | 0 |
| 5.000 facturas | 3.334 | 10 | 40 | 618,6 ms | 630,4 ms | 0 |

Cinco clientes API emitieron 50 facturas en 1,52 s, sin pérdidas y con 50 números distintos. Hubo 131 conflictos de revisión controlados y reintentados por el cliente de carga; no se presentan como escrituras sin contención. La prueba independiente con cinco navegadores verifica los reintentos reales de la interfaz.

Se terminó a la fuerza el proceso de prueba después de escribir dentro de una transacción y antes de confirmarla. Tras reiniciar, se conservaron íntegros la revisión y el estado anteriores y `PRAGMA integrity_check` devolvió `ok`. El máximo RSS observado de los procesos hijos del ensayo fue 313,7 MiB; no equivale al consumo total del sistema ni incluye el proxy.

Resultados numéricos completos: [2026-10-17-capacidad.json](2026-10-17-capacidad.json).

## Límites de la conclusión

Las medidas son del Mac local, con historiales ficticios y solicitudes API; no garantizan la capacidad del futuro VPS ni miden la interacción completa del navegador con 5.000 filas. La aplicación guarda el estado financiero completo y mantiene un solo proceso con SQLite. Si crecen el histórico o la concurrencia, habrá que medir y considerar paginación y almacenamiento por registros antes de añadir réplicas.

Una batería de pruebas no demuestra la ausencia de todos los errores ni sustituye una auditoría independiente. Antes de producción quedan el motor HTTP, el despliegue HTTPS, las copias externas, la observabilidad y repetir las pruebas en el servidor elegido. La aplicación sigue en modo de emisión de prueba; esta revisión no añade integración fiscal ni habilita por sí misma facturación con validez fiscal.
