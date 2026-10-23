# arquitecturadeguardia Finance

Aplicación local para preparar facturas y gestionar su análisis y cobro. Interfaz HTML/CSS/JavaScript y servidor Python con SQLite; no necesita servicios externos para guardar datos.

## Arrancar

```sh
npm start
```

Abrir http://localhost:4173. Requiere Python 3.10 o posterior y Node.js LTS. La primera vez, ejecutar `sh scripts/setup-server.sh`, que crea el entorno `.venv` con el servidor HTTP [Waitress](https://docs.pylonsproject.org/projects/waitress/) (gratuito y de código abierto) y las dependencias de VERI*FACTU. Ejecutar `npm install` para instalar Playwright, utilizado para conservar los PDF. En este Mac utiliza Google Chrome; en otro equipo se puede indicar `CHROME_PATH` o instalar Chromium con `npx playwright install chromium`. Los PDF se preparan en el servidor y no envían datos a servicios externos.

Para instalarla en un servidor (Ubuntu Server 24.04 LTS, Cloudflare Tunnel y traslado de datos) ver [deploy/GUIA-SERVIDOR.md](deploy/GUIA-SERVIDOR.md).

## Guía de uso

El botón **?** (arriba a la derecha, también en el móvil) y **Guía de uso** en el menú lateral abren una guía con capítulos cortos: primeros pasos, facturas, clientes, PDF y correo, cobros, Análisis, facturas de ejemplo, «Me he equivocado, ¿qué hago?» y un glosario. Los administradores ven además los capítulos de administración (configuración, correo, usuarios, emisores, copias, importación y VERI*FACTU). El contenido está en `dist/guide.js`.

Las capturas (`dist/assets/guide/`, versiones de escritorio y móvil) se generan con datos de demostración en un servidor temporal, nunca con los datos reales. Después de cambiar la interfaz, regenerarlas con `PATH="$PWD/.venv/bin:$PATH" node scripts/guide-screenshots.mjs`.

## Empresas, autónomos y usuarios

La instalación admite varios emisores independientes. El selector **Empresa / autónomo** cambia el contexto de Facturas, Clientes, Análisis y Configuración. En móvil aparece encima del contenido. Cada factura pertenece al emisor seleccionado y conserva el usuario responsable, creador y emisor material. Los clientes, series de numeración, cobros, anticipos, justificantes, importaciones e historial son independientes por perfil. Dos emisores pueden tener el mismo número de factura; dentro de un emisor sigue siendo único.

La primera cuenta administradora es la **cuenta principal** y gestiona los emisores y los accesos en Usuarios. En una instalación anterior, el primer administrador activo pasa a ser la cuenta principal y las cuentas existentes conservan su acceso al emisor original. Al abrir una instalación sin usuarios, el titular crea su administrador: no existe contraseña predeterminada.

- **Cuenta principal:** acceso a todos los emisores, creación y archivo de perfiles, gestión de usuarios y permisos.
- **Administrador de un emisor:** consulta y gestiona toda la facturación, clientes, configuración, cobros, importaciones y copias de ese perfil.
- **Usuario normal de un emisor:** crea, consulta, renumera, duplica y rectifica sus propias facturas y gestiona sus cobros, anticipos y análisis. Comparte el directorio de clientes de ese perfil y puede crear o editar sus propias fichas.
- Un usuario puede ser administrador en un emisor y normal en otro. Únicamente aparecen los emisores asignados. La gestión global de cuentas y contraseñas permanece reservada a la cuenta principal.
- El emisor de cada petición se comprueba en el servidor, también para documentos PDF, justificantes, importaciones, restauraciones, auditoría y exportaciones. La selección se mantiene por pestaña: otra pestaña no puede cambiar el destino de un guardado pendiente.
- Cambiar de emisor desde el menú lateral guarda el borrador y espera a que termine. Si falla la escritura, conserva la opción de descargar los cambios y bloquea el cambio para evitar pérdidas.
- En **Nueva factura → Emitiendo como**, el selector traslada el mismo borrador al emisor elegido y continúa su edición. Conserva descripción, conceptos, importes, retención, fecha, notas y responsable; aplica la plantilla predeterminada del destino y reutiliza su cliente por NIF o copia la ficha si no existe. La numeración se asigna al emitir en el destino. El traslado es atómico, registra ambos históricos y admite reintentos sin duplicados. Solo permite emisores asignados y activos; las facturas emitidas y las rectificativas conservan su emisor. El responsable necesita acceso al destino.
- **Gestionar emisores** permite crear una empresa o autónomo con su NIF y datos fiscales. Archivar conserva el histórico y lo deja en consulta para la cuenta principal; reactivar recupera sus accesos anteriores. Un NIF identifica un único perfil, también entre los archivados.
- En Clientes, un administrador con acceso a otro perfil puede copiar expresamente una ficha al otro emisor. Se copia únicamente el contacto, con un identificador nuevo. Los cambios posteriores son independientes y no se trasladan facturas ni cobros.

Las transferencias compartidas entre usuarios mantienen las restricciones anteriores: cada usuario normal recibe únicamente la parte aplicada a sus facturas. Un cobro pertenece a un cliente y solo puede pagar facturas de ese cliente; puede pagar varias de sus facturas a la vez. No se permiten repartos de un cobro entre emisores distintos.

**Usuarios → Crear usuario** permite asignar, para cada empresa o autónomo, Sin acceso, Usuario normal o Administrador. Las cuentas nuevas utilizan contraseña temporal y deben elegir una personal. Cambiar accesos, rol, correo, contraseña o estado revoca las sesiones afectadas. Desactivar conserva sus documentos. La cuenta principal no puede desactivarse ni perder su rol mediante la interfaz.

**Mi cuenta** permite cambiar la contraseña y cerrar sesión. Las contraseñas tienen de 6 a 128 caracteres (se recomienda una frase larga) y se guardan con scrypt y sal individual; la comprobación se hace sin bloquear al resto de usuarios. Las sesiones utilizan cookies HttpOnly/SameSite y el servidor conserva únicamente su hash; la actividad se registra como máximo una vez por minuto; duran como máximo 12 horas y caducan tras dos horas sin solicitudes de la aplicación. Los accesos fallidos tienen límite de intentos. La cookie añade Secure en el dominio HTTPS configurado. Las facturas y credenciales no se guardan en localStorage. Los identificadores de facturas, clientes y cobros solo admiten letras, cifras y `. _ : -`, y la cabecera `Content-Security-Policy` impide ejecutar código que no proceda de los archivos de la aplicación. Cerrar sesión retira los datos de otras pestañas del navegador.

Para recuperar la contraseña desde el equipo de los datos:

```sh
python3 manage_users.py reset-password correo@empresa.es
```

Pide una nueva contraseña temporal de forma interactiva, revoca sesiones y conserva la desactivación de las cuentas desactivadas. La publicación en un servidor se describe en [deploy/README.md](deploy/README.md).

## Descripción y presentación de las facturas

**Nueva factura → Descripción** es un texto opcional de hasta 2000 caracteres, situado antes de Conceptos. Se guarda con el borrador, conserva los saltos de línea y aparece antes de los conceptos en los cuatro diseños. Si está vacío no ocupa espacio en el documento. Se conserva al duplicar o trasladar el borrador entre emisores, también para usuarios normales.

La presentación omite «Factura de honorarios». Desde el 19/10/2026 (presentación versión 4) todas las facturas nuevas muestran su número y la referencia para la transferencia, estén o no marcadas como VERI*FACTU, como exige el artículo 6 del RD 1619/2012. En la vista previa de un borrador aparece «Borrador» donde irá el número. Las facturas emitidas antes sin VERI*FACTU conservan su presentación sin número, y los PDF conservados no cambian. Cada nueva emisión guarda la versión de presentación en `presentationSnapshot`.

## Borradores y textos recientes

Cada usuario conserva como máximo **15 borradores en total entre todos sus emisores**, incluidos ejemplos y borradores VERI*FACTU sin emitir. La cola se ordena por la última edición real guardada en el servidor. Abrir o volver a guardar sin cambiar los datos no actualiza la posición. Al superar 15 se elimina automáticamente el menos reciente de ese usuario; los demás usuarios y las facturas emitidas permanecen intactos. Se avisa al crear un nuevo borrador. Los traslados entre emisores se reconcilian una sola vez y no cuentan como dos borradores. Las pestañas antiguas no pueden resucitar un borrador eliminado; los cambios reales que entren en conflicto conservan la opción de recuperación.

**Conceptos recientes** y **Descripciones recientes** permiten buscar y reutilizar los últimos **50 textos distintos de cada tipo por usuario y emisor**. Se guardan al terminar de escribir, al salir o revisar la factura, al emitir y antes de eliminar un borrador de la cola. Reutilizar un texto lo coloca al principio sin duplicarlo. Al llegar al límite salen los menos recientes. Se conserva el texto completo con saltos de línea y se inserta como texto seguro. Las listas privadas se guardan en SQLite, no en localStorage; otros usuarios y otros emisores no las reciben. La primera consulta recupera los textos de las facturas propias existentes, sin volver a rellenar entradas ya descartadas.

La primera actualización guarda una copia SQLite completa `data/backups/antes-limites-borradores-*.sqlite` antes de aplicar la cola a los borradores existentes. La política también se aplica al restaurar una copia; las facturas emitidas no se eliminan. Las copias completas SQLite conservan además la cola y los historiales privados.

## Facturas de ejemplo

En **Nueva factura**, marcar **Factura de ejemplo** permite guardar y crear una muestra con serie anual propia `EJEMPLO-año-número`, independiente por emisor. Las rectificativas de ejemplos usan `EJEMPLO-R`. Se conservan conceptos, descripción, importes, plantilla y permisos del usuario. Al duplicar un ejemplo, el nuevo borrador sigue marcado; se puede desmarcar antes de emitir para crear una factura ordinaria. El cambio de emisor conserva la opción.

Los ejemplos permanecen en Facturas con identificación visible y pueden descargarse como PDF marcado **FACTURA DE EJEMPLO · SIN VALIDEZ FISCAL**. No consumen la numeración del emisor ni cuentan en el importe emitido del mes. Quedan excluidos de Análisis, sus exportaciones, pendientes, selecciones de cobro e historial visible; la auditoría completa del servidor conserva la operación. Se ha retirado «Incluir ejemplos» de Análisis. El servidor impide usar VERI*FACTU en un ejemplo o asociarle cobros, ajustes o devoluciones. Tras crear el documento se conserva su clasificación y numeración; para cambiar la muestra se duplica como borrador.

## Numeración y series

Cada emisor tiene una serie por defecto con sus iniciales: arquitecturadeguardia usa `ADG` y, por ejemplo, «Pepe Sánchez» usa `PS`. Las iniciales se toman de cada palabra del nombre fiscal, sin «de», «la», «y», «S.L.» ni otras partículas. **Configuración → Serie por defecto** permite fijar otras (de 1 a 10 letras o cifras); vacía, se vuelven a calcular del nombre, de modo que cambiar el nombre también cambia la serie.

Las nuevas emisiones usan `INICIALES-trimestreT-año-número`, por ejemplo `ADG-4T-2026-01` o `PS-4T-2026-01`. El trimestre procede de la fecha de expedición. El contador es anual por emisor: continúa entre trimestres y vuelve a 01 al cambiar de año. Se muestran al menos dos cifras (01…99, 100…). Las rectificativas tienen serie separada `INICIALES-R-trimestreT-año-número`.

En **Nueva factura → Serie** se puede escribir otra serie completa cuando la casilla VERI*FACTU no está marcada (hasta 40 letras, cifras, º y los signos `- / . _`, sin espacios; `EJEMPLO` está reservada). Cada serie lleva su propio contador: `OBRA` produce `OBRA-01`, `OBRA-02`…; una serie con trimestre, como `PS-1T-2026`, comparte el contador anual de `PS`. El borrador guarda la serie aunque esté incompleta; se comprueba al revisar y al emitir. Al marcar VERI*FACTU, la serie vuelve a la predeterminada y queda bloqueada. Duplicar conserva la serie escrita; las rectificativas y los traslados a otro emisor vuelven a la serie por defecto.

Las emisiones previas conservan sus números y documentos. Las series antiguas con `º` o `°` siguen contando en el mismo contador anual; el cambio a `T` no reinicia ni reutiliza sus números. Antes de generar un nuevo registro VERI*FACTU se comprueba que el número cumple la longitud y los caracteres admitidos por la AEAT. Al calcular el siguiente se tienen en cuenta los números de la serie en todos los trimestres y, para ADG, series anteriores F/R, históricos numéricos, antiguas series VF-F/VF-R y los números guardados en el historial de renumeración. Las nuevas facturas ordinarias y de pruebas comparten la reserva de números dentro del emisor para no repetir identificadores; las de pruebas siguen excluidas de las cifras y cobros habituales. Los documentos VERI*FACTU previamente sellados conservan su presentación; las nuevas emisiones guardan `presentationSnapshot` versión 3 con la visibilidad del número.

## Cambiar el número de una factura

Facturas → menú de tres puntos → **Editar número de factura**. También está disponible dentro de la factura y en el botón del lápiz de Análisis. Permite cambiar el identificador completo después de emitir, incluidas letras, año y cifras; se refleja en los listados, exportaciones y nombres de los nuevos archivos PDF. Los PDF ya descargados no se modifican.

Los cobros, saldos y rectificativas conservan sus vínculos. Los cambios de número quedan registrados con fecha, número anterior y nuevo, visibles en el diálogo y en Análisis → Historial. Se bloquean números usados por otras facturas, incluidos equivalentes históricos como `02-2026` y `F-2026-002`. La numeración automática no reutiliza números anteriores y una nueva importación reconoce las facturas renumeradas. Duplicar una factura crea un borrador sin heredar su historial de números.

## Eliminar y anular facturas

Desde el menú de tres puntos del listado, el editor o la revisión de la factura, siempre con una confirmación:

- **Borradores y facturas de ejemplo:** **Eliminar** los borra definitivamente. Puede hacerlo su responsable o un administrador. Un borrador eliminado no reaparece aunque otra pestaña antigua lo tuviera abierto.
- **Facturas emitidas:** **Anular factura** (solo administradores). No se borran: se conservan con su número y su PDF, marcadas como **Anulada**, en la pestaña **Anuladas** del listado. Dejan de contar en pendientes, cobros y Análisis, no se pueden renumerar, rectificar ni enviar por correo. No se puede deshacer.
- **El número de una factura anulada queda libre.** Si era la última de su serie, la siguiente factura emitida vuelve a tomar ese número. Si era intermedia, la numeración continúa y el número libre se puede asignar a otra factura con **Editar número de factura**. La anulada se conserva en **Anuladas** con su número y PDF originales; solo la vigente cuenta para la numeración, los duplicados y la importación del Excel. La numeración debe ser correlativa y única: consulta con tu gestoría antes de reutilizar el número de una factura que ya llegó al cliente.
- Antes de anular hay que anular sus cobros o ajustes aplicados, y antes de eliminar o anular una factura rectificada hay que eliminar o anular su rectificativa. Al anular una rectificativa, la factura original vuelve a ser la versión vigente.
- Las facturas **VERI*FACTU** no se pueden eliminar ni anular: sus registros fiscales son inmutables y se corrigen desde VERI*FACTU · pruebas.

## Enviar facturas por correo

Una vez emitida la factura, **Enviar por correo** (debajo de **Descargar PDF**) abre un diálogo con el correo del cliente como destinatario por defecto. Se pueden añadir más correos separados por comas (máximo 10) y modificar el asunto y el mensaje. Se adjunta el mismo PDF conservado que se descarga. Las facturas de ejemplo no se envían.

Cada emisor envía desde su propia cuenta: un administrador la configura en **Configuración → Correo de envío** (servidor SMTP, seguridad SSL/TLS o STARTTLS, puerto, usuario, contraseña y remitente) y puede comprobarla con **Probar conexión**. En Gmail se necesita una contraseña de aplicación. La contraseña se guarda cifrada con la misma clave del servidor que los certificados de VERI*FACTU (`data/vf-secrets/`). La opción «Sin cifrado» solo se admite con un servidor de correo en el mismo equipo. El correo sale a través del servidor configurado; es el único caso en que la aplicación envía datos a un servicio externo, y solo cuando se pulsa **Enviar**.

Los envíos realizados quedan registrados con la fecha, los destinatarios y quién los envió. Ese registro se muestra en la revisión de la factura y en el historial de seguridad. Se guarda en SQLite (tabla `mail_log`) y se incluye en las copias diarias de `data/backups/`, pero no en el ZIP de cada emisor. Los intentos fallidos se notifican en pantalla y no se registran.

## Análisis

- Resumen por año, trimestre, mes o intervalo, con fecha de corte y filtro de cliente.
- Facturación, cobrado aplicado, ajustes y pendiente por periodo y total.
- Los ingresos bancarios se agrupan por fecha de ingreso, independientemente de la emisión.
- Pestaña «Todas» con pagadas, no pagadas y parcialmente pagadas; columnas de concepto y pagos asociados, con enlaces al detalle.
- Nombre opcional para cada pago; los anteriores se identifican por referencia o pagador.
- Pago parcial desde «Cobrar»: seleccionar «Pago parcial» e introducir el importe recibido; el resto queda pendiente.
- Pendientes agrupables por cliente y selección de varias facturas para cobrar conjuntamente.
- Al registrar un cobro se elige el cliente que paga y solo se ofrecen sus facturas pendientes; el pagador es siempre ese cliente. Una transferencia puede pagar varias facturas del mismo cliente y una factura puede recibir varios pagos. Los anticipos quedan ligados a su cliente y solo se aplican a sus facturas.
- Anticipos y sobrantes quedan disponibles para aplicar después o devolver.
- Diferencias de hasta 0,02 € generan un ajuste identificado; las mayores requieren clasificación explícita.
- Ajustes de confirming, compensaciones, devoluciones y anulaciones con motivo.
- Historial de cobros en cada factura, justificantes PDF/PNG/JPG y exportaciones CSV.
- Las rectificativas por sustitución actualizan la factura original y mantienen sus cobros. Se atribuyen al periodo de la factura original y se explican en Análisis. No constituyen una implementación fiscal de rectificaciones.
- Los ejemplos iniciales se excluyen del análisis salvo que se active «Incluir ejemplos».

## Importar el histórico

Análisis → Importar Excel → Revisar «AA ingresos ADG 2026.xlsx», o seleccionar otro archivo.

El Excel se lee como datos: no se ejecutan fórmulas, macros ni instrucciones incluidas en documentos. La vista previa permite elegir hoja y filas, corregir datos y marcar incidencias revisadas. Cada cobro propuesto se selecciona y confirma por separado. Si el Excel atribuye a una misma transferencia facturas de varios clientes, el cobro se asigna al cliente con mayor importe y las facturas de los demás se dejan fuera con un aviso: siguen pendientes y la diferencia queda como saldo a favor de quien pagó. La importación se realiza únicamente al confirmar en pantalla.

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

Al emitir se conservan los datos y la versión de plantilla y se archiva una representación imprimible independiente, con estilos e imágenes incorporados. **Descargar PDF** genera el PDF en el servidor la primera vez y reutiliza después los mismos bytes. Cambiar el nombre, logo, IBAN o diseño predeterminado no modifica ese documento. La renumeración genera otra versión y **Documentos anteriores** permite descargar las previas. Para documentos históricos sin archivo previo, la primera descarga conserva su representación disponible sin modificar el estado financiero. Los históricos importados siguen identificados como representaciones de datos, no sustituyen el original.


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
.venv/bin/python tests/stress-server.py
```

El informe de resultados, dimensionamiento y condiciones pendientes antes de publicar está en [reviews/2026-10-17-fallos-y-capacidad.md](reviews/2026-10-17-fallos-y-capacidad.md). El servidor HTTP es Waitress, el mismo en el Mac y en el servidor; los pasos de publicación están en [deploy/README.md](deploy/README.md).
# Finance


## Migración a varios emisores

Antes de aplicar el nuevo esquema en una instalación existente, el servidor genera y verifica automáticamente una copia SQLite `data/backups/antes-multiemisor-*.sqlite`. Conserva sin reescribir el estado financiero original, su revisión, las numeraciones y el histórico. Añade perfiles, accesos y estados independientes para los siguientes emisores. Las facturas existentes siguen en arquitecturadeguardia y mantienen su plantilla. No se crean cuentas de prueba ni emisores de demostración en los datos reales.

Las pruebas específicas están en `tests/test_emitters.py`, `tests/test_documents.py`, `tests/templates.test.js` y `tests/emitters-browser.mjs`. El informe de esta ampliación está en [reviews/2026-10-18-multiemisor.md](reviews/2026-10-18-multiemisor.md).

## VERI*FACTU experimental (solo pruebas AEAT)

En **Nueva factura** puedes marcar **VERI*FACTU · Pruebas AEAT**. Está desmarcada inicialmente; el borrador sigue siendo editable. Al emitir se fija su contenido y su número de prueba, incluso si el envío falla o es rechazado. Las correcciones generan registros nuevos. Los documentos `VF-F`/`VF-R` y sus cobros se mantienen fuera de los listados e informes habituales.

Instala el adaptador con `sh scripts/setup-verifactu.sh` y arranca con `npm start`. En **VERI*FACTU · pruebas**, la cuenta principal configura la identidad del productor; los administradores añaden el certificado propio de cada empresa o autónomo. El envío automático permanece desactivado hasta activarlo para ese emisor. El destino está limitado al entorno oficial de pruebas y no existe opción de producción.

La importación requiere un PKCS#12 `.pfx` o `.p12` con su clave privada. Distingue las copias que se abren pero carecen de clave privada, las exportaciones públicas CER/CRT o P7B renombradas y los cifrados no compatibles. Un fallo de descifrado no demuestra por sí solo que la contraseña sea incorrecta: también puede deberse a un archivo dañado o una exportación incompatible. Una importación fallida conserva el certificado y la configuración anteriores. Las pruebas cubren AES-256, TripleDES y contraseñas con caracteres no ASCII y espacios, sin recortarlas.

Se conservan XML, huellas, intentos, respuestas y PDF. Los certificados se cifran y la contraseña de importación no se guarda. Para una recuperación completa conserva el directorio de datos y su clave privada del servidor mediante una copia cifrada con acceso restringido. Los ZIP por emisor incluyen un archivo fiscal de consulta, sin credenciales; no sustituyen la recuperación de la instalación completa.

Las pruebas automatizadas usan certificados y respuestas sintéticos; la aceptación real en AEAT requiere configurar los certificados del usuario y comprobarla en su entorno de pruebas. Alcance, recuperación y fuentes: [informe de la integración experimental](reviews/2026-10-19-verifactu-experimental.md).
