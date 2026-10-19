# arquitecturadeguardia Finance

Aplicación local para preparar facturas y gestionar su análisis y cobro. Interfaz HTML/CSS/JavaScript y servidor Python con SQLite; no necesita servicios externos para guardar datos.

## Arrancar

```sh
npm start
```

Abrir http://localhost:4173. Requiere Python 3.10 o posterior y Node.js LTS. Ejecutar `npm install` para instalar Playwright, utilizado para conservar los PDF. En este Mac utiliza Google Chrome; en otro equipo se puede indicar `CHROME_PATH` o instalar Chromium con `npx playwright install chromium`. Los PDF se preparan en el servidor y no envían datos a servicios externos.

## Empresas, autónomos y usuarios

La instalación admite varios emisores independientes. El selector **Empresa / autónomo** cambia el contexto de Facturas, Clientes, Análisis y Configuración. En móvil aparece encima del contenido. Cada factura pertenece al emisor seleccionado y conserva el usuario responsable, creador y emisor material. Los clientes, series de numeración, cobros, anticipos, justificantes, importaciones e historial son independientes por perfil. Dos emisores pueden tener el mismo número de factura; dentro de un emisor sigue siendo único.

La primera cuenta administradora es la **cuenta principal** y gestiona los emisores y los accesos en Usuarios. En una instalación anterior, el primer administrador activo pasa a ser la cuenta principal y las cuentas existentes conservan su acceso al emisor original. Al abrir una instalación sin usuarios, el titular crea su administrador: no existe contraseña predeterminada.

- **Cuenta principal:** acceso a todos los emisores, creación y archivo de perfiles, gestión de usuarios y permisos.
- **Administrador de un emisor:** consulta y gestiona toda la facturación, clientes, configuración, cobros, importaciones y copias de ese perfil.
- **Usuario normal de un emisor:** crea, consulta, renumera, duplica y rectifica sus propias facturas y gestiona sus cobros, anticipos y análisis. Comparte el directorio de clientes de ese perfil y puede crear o editar sus propias fichas.
- Un usuario puede ser administrador en un emisor y normal en otro. Únicamente aparecen los emisores asignados. La gestión global de cuentas y contraseñas permanece reservada a la cuenta principal.
- El emisor de cada petición se comprueba en el servidor, también para documentos PDF, justificantes, importaciones, restauraciones, auditoría y exportaciones. La selección se mantiene por pestaña: otra pestaña no puede cambiar el destino de un guardado pendiente.
- Cambiar de emisor desde el menú lateral guarda el borrador y espera a que termine. Si falla la escritura, conserva la opción de descargar los cambios y bloquea el cambio para evitar pérdidas.
- En **Nueva factura → Emitiendo como**, el selector traslada el mismo borrador al emisor elegido y continúa su edición. Conserva conceptos, importes, retención, fecha, notas y responsable; aplica la plantilla predeterminada del destino y reutiliza su cliente por NIF o copia la ficha si no existe. La numeración se asigna al emitir en el destino. El traslado es atómico, registra ambos históricos y admite reintentos sin duplicados. Solo permite emisores asignados y activos; las facturas emitidas y las rectificativas conservan su emisor. El responsable necesita acceso al destino.
- **Gestionar emisores** permite crear una empresa o autónomo con su NIF y datos fiscales. Archivar conserva el histórico y lo deja en consulta para la cuenta principal; reactivar recupera sus accesos anteriores. Un NIF identifica un único perfil, también entre los archivados.
- En Clientes, un administrador con acceso a otro perfil puede copiar expresamente una ficha al otro emisor. Se copia únicamente el contacto, con un identificador nuevo. Los cambios posteriores son independientes y no se trasladan facturas ni cobros.

Las transferencias compartidas entre usuarios mantienen las restricciones anteriores: cada usuario normal recibe únicamente la parte aplicada a sus facturas. Las transferencias pueden pagar varias facturas y clientes dentro del mismo emisor. No se permiten repartos de un cobro entre emisores distintos.

**Usuarios → Crear usuario** permite asignar, para cada empresa o autónomo, Sin acceso, Usuario normal o Administrador. Las cuentas nuevas utilizan contraseña temporal y deben elegir una personal. Cambiar accesos, rol, correo, contraseña o estado revoca las sesiones afectadas. Desactivar conserva sus documentos. La cuenta principal no puede desactivarse ni perder su rol mediante la interfaz.

**Mi cuenta** permite cambiar la contraseña y cerrar sesión. Las contraseñas admiten frases de 15 a 128 caracteres y se guardan con scrypt y sal individual. Las sesiones utilizan cookies HttpOnly/SameSite y el servidor conserva únicamente su hash; duran como máximo 12 horas y caducan tras dos horas sin solicitudes de la aplicación. Los accesos fallidos tienen límite de intentos. La cookie añade Secure en el dominio HTTPS configurado. Las facturas y credenciales no se guardan en localStorage. Cerrar sesión retira los datos de otras pestañas del navegador.

Para recuperar la contraseña desde el equipo de los datos:

```sh
python3 manage_users.py reset-password correo@empresa.es
```

Pide una nueva contraseña temporal de forma interactiva, revoca sesiones y conserva la desactivación de las cuentas desactivadas. El servidor futuro sigue pendiente de la adaptación HTTP de producción descrita en [deploy/README.md](deploy/README.md).

## Cambiar el número de una factura

Facturas → menú de tres puntos → **Editar número de factura**. También está disponible dentro de la factura y en el botón del lápiz de Análisis. Permite cambiar el identificador completo después de emitir, incluidas letras, año y cifras; se refleja en los listados, exportaciones y nuevos PDF. Los PDF ya descargados no se modifican.

Los cobros, saldos y rectificativas conservan sus vínculos. Los cambios de número quedan registrados con fecha, número anterior y nuevo, visibles en el diálogo y en Análisis → Historial. Se bloquean números usados por otras facturas, incluidos equivalentes históricos como `02-2026` y `F-2026-002`. La numeración automática no reutiliza números anteriores y una nueva importación reconoce las facturas renumeradas. Duplicar una factura crea un borrador sin heredar su historial de números.

## Análisis

- Resumen por año, trimestre, mes o intervalo, con fecha de corte y filtro de cliente.
- Facturación, cobrado aplicado, ajustes y pendiente por periodo y total.
- Los ingresos bancarios se agrupan por fecha de ingreso, independientemente de la emisión.
- Pestaña «Todas» con pagadas, no pagadas y parcialmente pagadas; columnas de concepto y pagos asociados, con enlaces al detalle.
- Nombre opcional para cada pago; los anteriores se identifican por referencia o pagador.
- Pago parcial desde «Cobrar»: seleccionar «Pago parcial» e introducir el importe recibido; el resto queda pendiente.
- Pendientes agrupables por cliente y selección de varias facturas para cobrar conjuntamente.
- Una transferencia puede pagar facturas de varios clientes; una factura puede recibir varios pagos.
- Anticipos y sobrantes quedan disponibles para aplicar después o devolver.
- Diferencias de hasta 0,02 € generan un ajuste identificado; las mayores requieren clasificación explícita.
- Ajustes de confirming, compensaciones, devoluciones y anulaciones con motivo.
- Historial de cobros en cada factura, justificantes PDF/PNG/JPG y exportaciones CSV.
- Las rectificativas por sustitución actualizan la factura original y mantienen sus cobros. Se atribuyen al periodo de la factura original y se explican en Análisis. No constituyen una implementación fiscal de rectificaciones.
- Los ejemplos iniciales se excluyen del análisis salvo que se active «Incluir ejemplos».

## Importar el histórico

Análisis → Importar Excel → Revisar «AA ingresos ADG 2026.xlsx», o seleccionar otro archivo.

El Excel se lee como datos: no se ejecutan fórmulas, macros ni instrucciones incluidas en documentos. La vista previa permite elegir hoja y filas, corregir datos y marcar incidencias revisadas. Cada cobro propuesto se selecciona y confirma por separado. La importación se realiza únicamente al confirmar en pantalla.

Se conservan números, totales históricos, procedencia de las filas y anotaciones originales. Se contrastan números equivalentes como `02-2026` y `F-2026-002` para evitar duplicados. Las transferencias ya incorporadas se reconocen sin depender del nombre o del hash del archivo. Si una factura existente tiene datos distintos se bloquea la importación para revisarla. La numeración nueva continúa después de los números históricos.

Las hojas auxiliares no se combinan automáticamente con la principal. Un cobro sin fecha no se considera confirmado. Los gastos de confirming no se descuentan de la deuda sin una clasificación explícita. Los clientes importados sin datos fiscales completos deben completarse antes de emitir nuevas facturas.

## Datos y copias

- Base de datos: `data/finance.sqlite`. Se conserva el historial de operaciones y las últimas 200 versiones completas del estado por emisor. Las tablas originales se mantienen para arquitecturadeguardia; los perfiles nuevos utilizan estados independientes. Los usuarios, membresías y documentos conservados comparten la base de datos con comprobaciones de emisor en cada operación.
- Justificantes: `data/attachments/`.
- Copia diaria de SQLite: `data/backups/`. Se comprueba su integridad y se conservan las últimas 14 copias diarias; las copias manuales previas a cambios no se borran con esta retención. Incluye las cuentas, el estado y los registros de justificantes; los archivos de los justificantes permanecen en `data/attachments/`. Una copia local no protege frente a la pérdida del equipo.
- Configuración → Descargar copia genera un ZIP del emisor seleccionado con la facturación, sus justificantes y los documentos conservados, incluidos los PDF ya generados. Lleva un identificador de emisor y comprueba el NIF antes de restaurar. Los usuarios y contraseñas permanecen en las tablas de acceso de SQLite; restaurar este ZIP conserva las cuentas actuales. Los responsables desconocidos o sin acceso a ese perfil se asignan al administrador que restaura. Para trasladar una copia a una instalación nueva se crea el perfil con el mismo NIF y se revisa la restauración.
- Configuración → Restaurar copia admite ZIP y JSON anteriores, muestra un resumen y exige confirmación. Antes de sustituir los datos conserva una copia local previa.
- Los datos de facturación permanecen en la base de datos del servidor; el navegador mantiene la sesión de trabajo en memoria y permite descargar los cambios si falla el guardado. Se comprueba la revisión y se combinan cambios independientes para evitar sobrescrituras.
- Si falla la copia automática después de guardar, se informa de que los cambios sí están guardados y se mantiene un aviso para descargar una copia. Si falla la escritura, permanece la opción de descargar los cambios sin guardar. Una recuperación de un usuario normal se identifica como parcial y no puede restaurarse como si fuera toda la empresa.
- Los comandos financieros llevan un identificador persistente de operación: una respuesta perdida y el reintento de ese mismo cobro no crean dos ingresos. Los conflictos independientes tienen reintentos limitados con espera variable; los cambios incompatibles siguen exigiendo revisión.
- Los documentos emitidos no se pueden alterar mediante el guardado genérico de borradores. La renumeración y las rectificaciones siguen sus operaciones específicas con historial. Las restauraciones comprueban estructura, saldos históricos y justificantes antes de sustituir el estado.
- La primera apertura del administrador puede trasladar los datos antiguos del navegador si todavía no existe estado en el servidor. Después se retiran las antiguas copias del navegador.
- El servidor escucha solo en 127.0.0.1 y protege las operaciones contra solicitudes de otros orígenes.

Para trasladar la facturación a otra instalación se puede utilizar el ZIP. Para trasladar también las cuentas, detener el servidor y copiar todo `data/`, incluidos SQLite y los justificantes, según la guía de despliegue. La base de datos y los datos privados están excluidos de Git. La instalación funciona en local y admite un origen HTTPS configurado para el servidor futuro.

## Plantillas de facturas

**Configuración → Plantillas de factura** ofrece Clásico, Minimalista y Compacto para empresas y autónomos. Cada perfil elige un diseño predeterminado; cada borrador puede seleccionar otro. Los diseños genéricos admiten logo, color, nota, texto al pie, importe en letras y firma propia opcional. La plantilla **arquitecturadeguardia · Original** conserva exactamente su composición anterior y sus imágenes; las opciones de los diseños genéricos no cambian esos elementos.

El perfil permite definir una retención predeterminada y ajustar el porcentaje en cada borrador. Se calcula sobre la base y se descuenta del importe a cobrar; PDF, listado, Análisis y reparto de cobros utilizan ese mismo importe neto. La configuración no decide por sí sola qué tratamiento fiscal corresponde a una operación.

Al emitir se conservan los datos y la versión de plantilla y se archiva una representación imprimible independiente, con estilos e imágenes incorporados. **Descargar PDF conservado** genera el PDF en el servidor la primera vez y reutiliza después los mismos bytes. Cambiar el nombre, logo, IBAN o diseño predeterminado no modifica ese documento. La renumeración genera otra versión y **Documentos anteriores** permite descargar las previas. Para documentos históricos sin archivo previo, la primera descarga conserva su representación disponible sin modificar el estado financiero. Los históricos importados siguen identificados como representaciones de datos, no sustituyen el original.


Logo y firma originales extraídos del Word facilitado por el usuario, datos fiscales y bancarios confirmados, honorarios y total calculado automáticamente en letras. La muestra está en Configuración y en http://localhost:4173/?view=template. No consume numeración ni se incorpora al listado.

Los registros históricos importados se identifican como tales; la vista generada no sustituye el documento original. La emisión del programa sigue siendo de prueba: no hay conexión fiscal con la AEAT, certificación de un sistema de facturación ni envío de correo.

## Verificación

```sh
npm test
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/run-browser.mjs
npm run test:browser
```

Las pruebas de navegador necesitan Google Chrome instalado; `CHROME_PATH` permite indicar otra ruta compatible. Usan bases de datos temporales en puertos separados y no importan cobros en los datos del usuario. Cubren cuentas, permisos, cambio de contraseña, desactivación, sesiones, usuarios simultáneos, transferencias compartidas sin revelar datos ajenos, creación y PDF, importación revisada, anticipos, devoluciones, ZIP con justificantes, móvil y conflictos de revisión.

Las pruebas de fallos también simulan respuestas perdidas, reintentos, errores de escritura y copias, archivos incompletos, conexiones lentas y cinco navegadores guardando a la vez. Para la prueba adicional de volumen y terminación forzada, exclusivamente en datos temporales:

```sh
python3 tests/stress-server.py
```

El informe de resultados, dimensionamiento y condiciones pendientes antes de publicar está en [reviews/2026-10-17-fallos-y-capacidad.md](reviews/2026-10-17-fallos-y-capacidad.md). El servidor actual se mantiene para desarrollo y uso local: antes de exponerlo públicamente es necesaria la adaptación del motor HTTP descrita en [deploy/README.md](deploy/README.md).
# Finance


## Migración a varios emisores

Antes de aplicar el nuevo esquema en una instalación existente, el servidor genera y verifica automáticamente una copia SQLite `data/backups/antes-multiemisor-*.sqlite`. Conserva sin reescribir el estado financiero original, su revisión, las numeraciones y el histórico. Añade perfiles, accesos y estados independientes para los siguientes emisores. Las facturas existentes siguen en arquitecturadeguardia y mantienen su plantilla. No se crean cuentas de prueba ni emisores de demostración en los datos reales.

Las pruebas específicas están en `tests/test_emitters.py`, `tests/test_documents.py`, `tests/templates.test.js` y `tests/emitters-browser.mjs`. El informe de esta ampliación está en [reviews/2026-10-18-multiemisor.md](reviews/2026-10-18-multiemisor.md).
