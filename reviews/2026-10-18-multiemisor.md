# Empresas, autónomos y plantillas · 18/10/2026

Se implementó el plan de varios emisores, accesos por usuario y diseños genéricos. VERI*FACTU queda fuera de esta ampliación. La aplicación conserva el modo de emisión de prueba.

## Funcionamiento

- Selector de empresa/autónomo en el menú lateral y sobre el contenido en móvil. Cada pestaña conserva su emisor y lo identifica en cada petición; cambiar de perfil espera al guardado del borrador.
- Perfil fiscal independiente, numeración por año y serie, clientes, facturas, cobros, anticipos, justificantes, importaciones, revisiones e historial por emisor.
- Cuenta principal para crear, archivar y reactivar emisores y gestionar usuarios. Los demás usuarios tienen rol normal o administrador por emisor. El usuario normal ve sus propios documentos; el administrador consulta los de todo ese perfil. Los administradores de un perfil no gestionan las cuentas de otros perfiles.
- Análisis, periodos, estados de cobro, pagos parciales, transferencias agrupadas y exportaciones se limitan al emisor seleccionado y a los permisos de la persona.
- Copia explícita de fichas de clientes entre perfiles donde se tenga administración, con identificadores nuevos, sin copiar documentos ni cobros y sin sobrescribir una ficha ya existente con el mismo NIF.
- Archivo reversible de emisores. La cuenta principal conserva su consulta y sus copias; se desactiva la edición mientras está archivado.
- Diseños genéricos Clásico, Minimalista y Compacto para empresas y autónomos. Configuración por emisor de diseño predeterminado, logo, color, notas, pie, importe en letras y firma propia opcional. Selección adicional por borrador.
- Retención configurable por perfil y factura. Cálculo decimal sobre la base, total neto coherente en factura, PDF y cobros. La configuración del programa no determina qué tratamiento fiscal corresponde a una operación.
- Al emitir se congela la versión de plantilla y se conserva una representación imprimible con estilos e imágenes incorporados. La primera descarga genera y guarda el PDF; las siguientes reutilizan los mismos bytes. La renumeración conserva ambas versiones. Las copias ZIP incluyen representaciones y PDF ya generados, y comprueban emisor, vínculos de documentos y justificantes antes de restaurar.

## Conservación del histórico y plantilla original

Antes del trabajo se guardó una copia del código y una copia verificada de SQLite. Antes de activar la versión se generó otra copia completa. El arranque también incorpora una copia automática previa al primer cambio de esquema.

Se activó la ampliación en localhost y se verificó que la revisión, el hash del estado financiero, las 17 facturas, los 3 cobros y el número de cuentas permanecían idénticos antes y después. SQLite pasó `integrity_check`. Los nuevos datos de perfiles y permisos se añadieron sin reescribir el estado original. No se crearon cuentas ni emisores de prueba en la instalación real.

La plantilla original se contrastó con el código anterior utilizando una factura ficticia reproducible: el HTML coincide exactamente. Los estilos previos se conservan como prefijo idéntico del archivo CSS y las imágenes originales no se sustituyeron. Se mantiene una prueba con ese HTML de referencia en `tests/fixtures/adg-original.html`, sin datos fiscales reales.

## Verificación

Comprobaciones ejecutadas:

```sh
npm test
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm run test:browser
python3 tests/stress-server.py /tmp/adg-multi-capacidad.json
```

La batería de JavaScript aprobó sus 30 pruebas y la batería completa de servidor aprobó 81 pruebas. La suite de navegador completa pasó, incluyendo duplicación de facturas y conservación de documentos. La prueba específica de emisores validó también la consulta de perfiles archivados y su reactivación. Las 22 pruebas de fallos incluyen errores al capturar el documento y al guardar la caché del PDF; comprueban que se conserva el estado financiero.

Las pruebas nuevas cubren aislamiento por emisor, roles distintos por cuenta, peticiones directas no autorizadas, documentos ajenos, permisos revocados, independencia de revisiones y números, retenciones, captura atómica del documento, conservación de versiones, PDF de varias páginas, texto escapado y traslado de un ZIP con PDF a una instalación temporal nueva con el mismo NIF. También se probó la migración de una base antigua con cuentas existentes: conserva contraseñas, responsables, revisión y cuerpo del estado.

Todas las operaciones de prueba, importaciones, cobros, archivos de emisores y terminaciones forzadas utilizaron bases temporales en puertos distintos. Las capturas de revisión visual utilizaron emisores ficticios.

## Capacidad medida

Resultados sintéticos en el Mac local, con la nueva conservación de documentos activa:

| Facturas | Cobros | Lectores simultáneos | Peticiones | Mediana de lectura | Percentil 95 | Errores |
|---|---:|---:|---:|---:|---:|---:|
| 100 | 67 | 10 | 40 | 40,0 ms | 48,4 ms | 0 |
| 1.000 | 667 | 10 | 40 | 126,4 ms | 171,9 ms | 0 |
| 5.000 | 3.334 | 10 | 40 | 712,5 ms | 837,9 ms | 0 |

Cinco usuarios emitieron 50 facturas con 50 números únicos en 5,19 s. Se reintentaron 176 conflictos de revisión controlados; no se perdió ninguna factura. La prueba independiente de cinco navegadores comprueba los reintentos reales de la interfaz. El ensayo de volumen utilizó datos sencillos, sin logos de gran tamaño.

Se terminó a la fuerza un servidor temporal durante una transacción no confirmada. Tras reiniciar, el estado anterior se mantuvo completo y SQLite devolvió integridad `ok`. El máximo RSS observado de los procesos hijos fue 268,5 MiB; no mide el consumo total del sistema ni garantiza capacidad en el VPS.

Datos del ensayo: [2026-10-18-capacidad.json](2026-10-18-capacidad.json).

## Ejecución y límites

La aplicación utiliza Python y SQLite. La conservación de documentos requiere Node.js LTS; la descarga de PDF utiliza Playwright y Chrome/Chromium en el servidor. Playwright es ahora una dependencia de ejecución. Hay un máximo de dos generaciones PDF simultáneas. La guía y el servicio de ejemplo documentan la ruta del navegador en Linux.

Continúa funcionando en [localhost:4173](http://localhost:4173). El despliegue público sigue pendiente de sustituir el motor HTTP de desarrollo, configurar HTTPS y copias externas y repetir las pruebas en el servidor elegido. Las medidas locales no sustituyen esas comprobaciones.
