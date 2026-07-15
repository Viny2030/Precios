# Manual de uso — Observatorio de Precios alimentos y bebidas

Guía para navegar el dashboard (`/dashboard`, servido por `api.py` a partir de
`rubros.html`) y para consumir la API REST directamente.

## 1. Qué es este sitio

Un índice propio de precios de Alimentos y Bebidas para CABA, calculado a
partir de precios reales del SEPA (Precios Claros, Ley 27.275), comparado mes
a mes contra tres referencias oficiales:

- **GCBA** — IPC Alimentos y Bebidas no alcohólicas, específico de CABA.
- **INDEC GBA Alimentos** — IPC-GBA Alimentos y Bebidas (la región que más se
  acerca a CABA en las estadísticas nacionales).
- **INDEC Nivel General Nacional** — el número de inflación mensual que se
  cita habitualmente en medios (todos los rubros, no solo alimentos).

## 2. La pestaña "Evolución general"

Una fila por período (mes) con:

- **Período** y **Origen**: badge que indica si ese mes se calculó con
  precios reales del SEPA (**Real**) o con precios de referencia estimados
  (**Sintético**) — esto último aplica solo a abril/mayo/junio 2026, mientras
  no había datos reales todavía.
- **Índice / Var. %** por cada fuente (Propio, GCBA, INDEC GBA, INDEC
  Nacional). El índice está en base `{{PERIODO_BASE}}` = 100 (variable, ver
  `config.PERIODO_BASE`).
- **Dif. pp**: variación propia menos variación de la serie oficial, en
  puntos porcentuales. Un valor positivo significa que el índice propio subió
  más que esa referencia oficial ese mes.

Si una fuente todavía no publicó el mes (INDEC/GCBA publican ~el día 14 del
mes siguiente), esa columna muestra "—" en vez de romper la tabla.

## 3. La pestaña "Evolución por rubro"

Elegí un rubro (subclase COICOP) en el selector — la lista sale del catálogo
de la canasta (`/rubros`). Para ese rubro puntual se muestra:

- Propio vs. **INDEC (aperturas GBA)** — el único desglose por rubro que el
  INDEC publica (no hay apertura por rubro a nivel Nacional ni de CABA).
- Como referencia, los mismos benchmarks **generales** (GCBA e INDEC Nivel
  General Nacional) de la pestaña anterior, repetidos acá para poder
  comparar de un vistazo cómo le fue a ese rubro contra el panorama general
  — esos dos NO son específicos del rubro.

La selección de rubro y la pestaña activa quedan guardadas en el navegador
(no hace falta volver a elegirlas cada vez que se recarga la página).

## 4. Cómo leer los badges de origen de datos

| Badge | Significado |
|---|---|
| Real | Calculado con precios reales relevados del SEPA ese mes. |
| Sintético | Calculado con una estimación de referencia (solo meses de arranque, abril–junio 2026, antes de tener suficiente historial real). |
| Sin datos | Todavía no hay índice calculado para ese período/rubro. |

## 5. API REST (para uso programático)

Documentación interactiva (Swagger): `<url-del-deploy>/docs`.

| Endpoint | Qué devuelve |
|---|---|
| `GET /` | Health check + resumen (total de registros, período base, último período calculado). |
| `GET /indices` | Serie completa del índice general (todos los períodos). |
| `GET /indices/{periodo}` | Índice general de un mes puntual (`YYYY-MM`). |
| `GET /indices/{periodo}/rubros` | Apertura por subclase COICOP de un mes. |
| `GET /rubros` | Catálogo de rubros (subclase, descripción, ponderación ENGHo). |
| `GET /comparativo/{periodo}` | Comparativo general propio vs. GCBA/INDEC GBA/INDEC Nacional para un mes. |
| `GET /comparativo/evolucion/general` | Igual que el anterior pero para todos los meses — alimenta la pestaña "Evolución general". |
| `GET /comparativo/{periodo}/rubros` | Comparativo por rubro (propio vs. INDEC aperturas GBA) de un mes. |
| `GET /comparativo/evolucion/rubro/{coicop_subclase}` | Igual que el anterior pero para todos los meses de un rubro — alimenta la pestaña "Evolución por rubro". |

## 6. Alcance y limitaciones (léase antes de citar los datos)

- El índice es una construcción propia (nowcasting), no la medición oficial
  del INDEC ni la reemplaza.
- Los períodos "Sintético" son una estimación de referencia, no un precio
  relevado — se marcan explícitamente para no confundirlos con datos reales.
- El desglose por rubro del INDEC solo existe a nivel regional (GBA); no hay
  apertura oficial exclusiva de CABA.
- Fuentes: Ministerio de Economía de la Nación (API de Series de Tiempo),
  INDEC (`sh_ipc_aperturas.xls`), GCBA/BA Data (SEPA — Precios Claros), bajo
  Ley 27.275 de Acceso a la Información Pública.
