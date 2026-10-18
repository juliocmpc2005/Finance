# arquitecturadeguardia Finance

Aplicación local para preparar facturas y gestionar su análisis y cobro. Interfaz HTML/CSS/JavaScript y servidor Python con SQLite; no necesita servicios externos para guardar datos.

## Arrancar

```sh
npm start
```

Abrir http://localhost:4173. Requiere Python 3.10 o posterior. Para instalar las herramientas de pruebas: `npm install`.

## Empresa y usuarios

La instalación representa una empresa. Al abrirla por primera vez, el titular crea su administrador con nombre, correo y contraseña. Las facturas, clientes y cobros existentes se conservan y se asignan inicialmente a ese administrador; antes de la asignación se guarda una copia JSON. No hay contraseña predeterminada.

- **Administrador:** acceso a todas las facturas y cobros de la empresa, clientes, configuración, importación, copias y Usuarios. En Facturas puede filtrar por usuario; cada factura muestra su responsable.
- **Usuario normal:** crea y consulta sus propios borradores y facturas, cambia su número, emite, duplica y rectifica sus documentos y gestiona sus cobros, anticipos y análisis. Sus CSV contienen únicamente los datos visibles para su cuenta. El directorio de clientes es compartido: puede consultarlo y crear o editar sus propios clientes; los otros registros los modifica administración.
- Cada factura guarda responsable, creador y emisor. Una rectificativa conserva el responsable de la factura original. La numeración se asigna en el servidor para toda la empresa en una sola transacción, aunque un usuario solo vea sus documentos.
- Los permisos se comprueban en cada lectura y escritura del servidor, incluidas las descargas de justificantes. La respuesta al usuario normal ya contiene sus facturas filtradas. Las copias completas, restauración, importación y el ejemplo histórico de Word quedan reservados al administrador.
- Un ingreso registrado por un usuario normal puede pagar sus facturas de varios clientes. Si el administrador reparte un ingreso entre facturas de distintos usuarios, cada uno ve solamente lo aplicado a sus facturas. El administrador gestiona el ingreso completo, su justificante, devoluciones y anulaciones. Los saldos personales no incluyen el importe de otros usuarios ni ofrecen ese dinero para repartirlo.
- Las ediciones de documentos distintos se combinan conservando los cambios de las otras sesiones. Si coinciden cambios sobre el mismo dato se exige revisar el conflicto. La emisión simultánea mantiene números únicos en toda la empresa.

**Usuarios → Crear usuario** crea una cuenta normal o administradora con contraseña temporal. La persona debe sustituirla por una personal antes de acceder a los datos. Editar permite cambiar el rol, restablecer la contraseña o desactivar el acceso. Cambiar rol, contraseña o estado revoca las sesiones anteriores. La última cuenta administradora activa está protegida. Desactivar una cuenta conserva sus documentos y el administrador sigue viéndolos.

**Mi cuenta** permite cambiar la contraseña y cerrar sesión. Las contraseñas admiten frases de 15 a 128 caracteres y se guardan con scrypt y sal individual. Las sesiones se identifican mediante cookies HttpOnly/SameSite y el servidor conserva únicamente el hash del identificador; duran como máximo 12 horas y caducan tras dos horas sin solicitudes de la aplicación. Los accesos fallidos tienen límite de intentos. La cookie añade Secure en el dominio HTTPS configurado. Las facturas y credenciales no se guardan en localStorage. Cerrar sesión retira los datos de las otras pestañas de ese navegador.

Si el administrador olvida su contraseña, la recuperación se hace desde el equipo de los datos, sin enviar correos ni exponer claves en argumentos:

```sh
python3 manage_users.py reset-password correo@empresa.es
```

Pide la nueva contraseña temporal de forma interactiva y cierra las sesiones de esa cuenta. Los usuarios desactivados permanecen desactivados.

Para el servidor futuro hay ejemplos de servicio y proxy HTTPS en [deploy/README.md](deploy/README.md). Actualmente continúa funcionando en localhost. Las pautas de contraseñas y sesiones se han contrastado con las referencias de [almacenamiento de contraseñas de OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) y [gestión de sesiones de OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

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

- Base de datos: `data/finance.sqlite`. Se conserva el historial de operaciones y las últimas 200 versiones completas del estado.
- Justificantes: `data/attachments/`.
- Copia diaria de SQLite: `data/backups/`. Se comprueba su integridad y se conservan las últimas 14 copias diarias; las copias manuales previas a cambios no se borran con esta retención. Incluye las cuentas, el estado y los registros de justificantes; los archivos de los justificantes permanecen en `data/attachments/`. Una copia local no protege frente a la pérdida del equipo.
- Configuración → Descargar copia genera un ZIP con la facturación y sus justificantes. Los usuarios y contraseñas permanecen en las tablas de acceso de SQLite; restaurar este ZIP conserva las cuentas actuales. Los responsables desconocidos de una copia se asignan al administrador que restaura.
- Configuración → Restaurar copia admite ZIP y JSON anteriores, muestra un resumen y exige confirmación. Antes de sustituir los datos conserva una copia local previa.
- Los datos de facturación permanecen en la base de datos del servidor; el navegador mantiene la sesión de trabajo en memoria y permite descargar los cambios si falla el guardado. Se comprueba la revisión y se combinan cambios independientes para evitar sobrescrituras.
- Si falla la copia automática después de guardar, se informa de que los cambios sí están guardados y se mantiene un aviso para descargar una copia. Si falla la escritura, permanece la opción de descargar los cambios sin guardar. Una recuperación de un usuario normal se identifica como parcial y no puede restaurarse como si fuera toda la empresa.
- Los comandos financieros llevan un identificador persistente de operación: una respuesta perdida y el reintento de ese mismo cobro no crean dos ingresos. Los conflictos independientes tienen reintentos limitados con espera variable; los cambios incompatibles siguen exigiendo revisión.
- Los documentos emitidos no se pueden alterar mediante el guardado genérico de borradores. La renumeración y las rectificaciones siguen sus operaciones específicas con historial. Las restauraciones comprueban estructura, saldos históricos y justificantes antes de sustituir el estado.
- La primera apertura del administrador puede trasladar los datos antiguos del navegador si todavía no existe estado en el servidor. Después se retiran las antiguas copias del navegador.
- El servidor escucha solo en 127.0.0.1 y protege las operaciones contra solicitudes de otros orígenes.

Para trasladar la facturación a otra instalación se puede utilizar el ZIP. Para trasladar también las cuentas, detener el servidor y copiar todo `data/`, incluidos SQLite y los justificantes, según la guía de despliegue. La base de datos y los datos privados están excluidos de Git. La instalación funciona en local y admite un origen HTTPS configurado para el servidor futuro.

## Plantilla de facturas

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
