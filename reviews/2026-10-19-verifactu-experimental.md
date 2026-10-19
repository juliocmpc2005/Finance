# VERI*FACTU experimental · 19/10/2026

Integración propia con el servicio oficial de pruebas, manteniendo la casilla por borrador solicitada. No contiene modo de producción ni una URL de envío configurable.

## Uso

1. `sh scripts/setup-verifactu.sh` instala las dependencias en `.venv`. `npm start` utiliza ese Python automáticamente. Node.js y Chrome/Playwright siguen generando y conservando los documentos.
2. La cuenta principal configura nombre y NIF del productor del programa en **VERI*FACTU · pruebas**. Esta identidad es distinta del emisor de cada factura. El NIF del productor queda fijado cuando existen registros; la instalación se identifica mediante un UUID persistente.
3. Cada administrador configura el certificado PKCS#12 propio de su empresa o autónomo. Se valida su fecha y la coincidencia del NIF con los identificadores del certificado. El envío automático está desactivado inicialmente. Guardar un certificado no lo activa por sí solo.
4. En **Nueva factura**, la casilla **VERI*FACTU · Pruebas AEAT** comienza desmarcada. El borrador puede seguir editándose y trasladándose a otro emisor. Las rectificativas mantienen el mismo entorno que el original.
5. Al emitir con la casilla marcada, el servidor guarda atómicamente número de prueba, factura, registro XML, huella, documento y trabajo de envío. Las series `VF-F` y `VF-R` son independientes de `F` y `R`. Se mantiene la retención en el importe a cobrar, mientras que XML y QR usan base más IVA antes de IRPF.
6. El documento emitido queda inmodificable, incluso para administradores, antes del primer intento de envío. Se permiten cobros parciales de prueba. Las facturas y los cobros experimentales se excluyen de Facturas/Análisis/Cobros habituales y de los informes ordinarios; pueden consultarse en la pestaña de pruebas y en VERI*FACTU.
7. Al activar expresamente el envío automático del emisor, el servidor procesa su cola. La pestaña del navegador puede cerrarse. La cola queda en pausa para emisores archivados o con envío desactivado.

## Integración

- SOAP 1.1 con autenticación TLS mediante certificado del emisor; destino fijo `https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP`. No se siguen redirecciones.
- XML y respuestas se validan contra los XSD oficiales descargados y fijados en `backend/verifactu_specs/manifest.json`. Las importaciones de esquemas se resuelven exclusivamente con archivos locales; las respuestas no pueden cargar entidades externas.
- Altas, subsanaciones y anulaciones son registros nuevos. Se encadenan por emisor en orden de generación, incluyendo los registros rechazados. No se sustituye el XML previo.
- Huella SHA-256 y QR según las especificaciones oficiales. El PDF incorpora un QR de 35 mm y la identificación visible del entorno experimental. Las plantillas sin VERI*FACTU conservan su salida anterior.
- Registros y auditoría de intentos tienen tablas independientes y protecciones SQL contra actualización o borrado. El estado de transporte se modifica en otra tabla. Importaciones/restauraciones no pueden borrar ni alterar las facturas protegidas por el archivo fiscal existente.
- Los reintentos reutilizan el XML exacto. Una respuesta de duplicado no equivale automáticamente a aceptación: se consulta el registro y se comprueba la huella actual y el estado remoto. La cola utiliza reservas con vencimiento para recuperar envíos tras interrupciones y respeta el tiempo de espera devuelto por la AEAT.
- Los certificados se guardan cifrados. La contraseña de importación no se conserva. La clave local está en `data/vf-secrets/master.key`, con permisos restringidos; los archivos PEM temporales se eliminan después de cargar el contexto TLS.
- El estado financiero nunca contiene claves privadas, certificados o contraseñas. Los usuarios normales solo consultan sus registros y no configuran certificados.

## Copias y recuperación

Se genera una copia SQLite verificada antes de añadir el esquema fiscal a una instalación existente. Las copias SQLite diarias incluyen registros, cola, intentos y certificados cifrados. Para trasladar o recuperar completamente esta instalación hay que conservar **todo** el directorio de datos, incluida su clave `vf-secrets/master.key`, con acceso restringido y copia cifrada.

El ZIP/JSON por emisor incluye un archivo fiscal de consulta (`_verifactuArchive`), sin las credenciales. Restaurar ese ZIP en la misma instalación no retrocede los registros ni los envíos. La importación de un archivo fiscal en una instalación nueva no está habilitada: debe recuperarse la instalación completa para conservar identidad, certificados y continuidad. Una copia anterior a una factura protegida se rechaza si pretendiera eliminarla.

## Alcance y comprobación

Primera versión para pruebas de facturas completas nacionales, IVA de régimen general, exenciones identificadas explícitamente y rectificación por sustitución R4/S. Se rechazan NIF extranjeros y no se asumen causas de exención para IVA 0 %. No incorpora producción, SII, TicketBAI, OSS, inversión del sujeto pasivo, facturación simplificada ni otros regímenes especiales. Configurar el productor y superar validaciones XML no constituye una declaración responsable ni una homologación del programa.

Pruebas: vector de huella publicado por la AEAT; validación XSD de alta, anulación, subsanación, rectificativa y consulta; total antes de IRPF; QR codificado; permisos por emisor/usuario; certificados incorrectos/caducados; cifrado; bloqueo de cambios y restauraciones; pagos parciales aislados; respuestas perdidas; duplicados confirmados por consulta; reservas caducadas; envíos en pausa; PDF y móvil. Los ensayos utilizan datos sintéticos, certificados de prueba locales y transporte simulado. No se han remitido facturas a la AEAT ni se ha verificado una aceptación real con certificados del usuario.

## Fuentes

- [Documentación técnica y entorno de pruebas AEAT](https://sede.agenciatributaria.gob.es/Sede/iva/sistemas-informaticos-facturacion-verifactu/informacion-tecnica.html)
- [Servicio, validaciones y ejemplos](https://sede.agenciatributaria.gob.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/Veri-Factu_Descripcion_SWeb.pdf)
- [Algoritmo de huella](https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/Veri-Factu_especificaciones_huella_hash_registros.pdf)
- [Especificaciones del QR](https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/DetalleEspecificacTecnCodigoQRfactura.pdf)
- [FAQ de desarrolladores: retenciones e importe total](https://sede.agenciatributaria.gob.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/FAQs-Desarrolladores.pdf)
