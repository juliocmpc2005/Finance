# Claro · Facturación

Interfaz funcional para preparar y revisar facturas de una pequeña empresa española. HTML, CSS y JavaScript modular, sin framework ni compilación.

## Probar en local

`npm start` y abrir http://localhost:4173. `npm test` ejecuta las pruebas de cálculos, validación y numeración. Las pruebas de navegador están en `tests/browser.mjs` y requieren Playwright, un servidor local y Google Chrome instalado (se puede configurar `CHROME_PATH`).

## Incluye

- Listado con búsquedas, filtros, orden y exportación CSV.
- Agenda de clientes y configuración de empresa.
- Editor con varios conceptos, IVA, cálculo en céntimos y guardado de borradores.
- Revisión, numeración de prueba, copias históricas y duplicación.
- Rectificativas de prueba por sustitución, vinculadas al original.
- Vista de impresión A4 para guardar como PDF.
- Copias JSON y restauración confirmada.
- Diseño adaptable a móvil y navegación por teclado.

## Estado del producto

Es una demostración funcional de interfaz. Incluye datos ficticios y cada documento indica «sin validez fiscal». No implementa un sistema fiscal de producción: faltan el análisis de aplicabilidad a la empresa, reglas fiscales completas, inmutabilidad y auditoría en servidor, autenticación de aplicación, almacenamiento compartido, integración fiscal y entrega de facturas. No hay envío de correo. El alojamiento se publica con acceso privado mediante Sites.

Los datos se guardan en localStorage del navegador. No se sincronizan entre dispositivos ni con otros usuarios; no es un entorno multiusuario. Exportar una copia antes de limpiar el navegador. Las fuentes web son opcionales: la interfaz conserva fuentes de respaldo si la red no está disponible.
