# Metodología — Índice de Precios de Alimentos y Bebidas, CABA

Documento único de referencia. Consolida y reemplaza las notas dispersas en
`README.md`, `ESTADO_PENDIENTES.md` y los docstrings de cada módulo — pensado
para poder citarse tal cual (nota de prensa, paper, informe universitario)
sin tener que reconstruir la metodología leyendo el código.

Autor: Ph.D. Vicente Humberto Monteverde — Investigador en economía
política, Doctor en Ciencias Económicas. Contacto: vhmonte@retina.ar

## 1. Qué mide este índice

Un índice de precios de Alimentos y Bebidas (COICOP divisiones 01 y 02) para
la Ciudad Autónoma de Buenos Aires (CABA), calculado mes a mes a partir de
precios efectivamente relevados (no encuestados ni estimados) en sucursales
de CABA. Es un ejercicio de *nowcasting* independiente, no una medición
oficial ni un reemplazo del IPC del INDEC.

## 2. Fuentes de datos (todas públicas, Ley 27.275)

| Dato | Fuente | Cómo se obtiene |
|---|---|---|
| Precios diarios | SEPA / Precios Claros (Ministerio de Producción) | `ingesta.py`, descarga automática diaria vía catálogo CKAN de datos.gob.ar |
| Ponderaciones de la canasta | INDEC, `sh_ipc_aperturas.xls`, hoja "Ponderaciones", región GBA | `precios_seed_ponderaciones.py` |
| Series oficiales de comparación (GCBA, INDEC GBA Alimentos, INDEC Nacional) | Ministerio de Economía (API de Series de Tiempo) y GCBA | `comparativo.py` |
| Clasificación EAN → COICOP | No existe fuente pública — se construye a mano (ver sección 4) | `data/diccionario_coicop.csv` |

No se usan datos sintéticos, encuestados ni simulados para publicar el
índice vigente. Los meses de arranque (abril-junio 2026) se calcularon en su
momento con una canasta sintética de referencia para poder probar el
pipeline antes de tener suficiente historial real; esos períodos fueron
**borrados** el 2026-08-01 al pasar a julio como primer mes real (ver
`ESTADO_PENDIENTES.md`, punto -1) — el historial hoy arranca limpio en julio
2026.

## 3. La canasta: ENGHo 2017-2018 ("nueva"), no ENGHo 2004-2005 ("vieja")

Este proyecto pondera sus subclases con la Encuesta Nacional de Gastos de
los Hogares más reciente (2017-2018), adelantándose al empalme oficial del
INDEC, que a la fecha (agosto 2026) sigue publicando su IPC oficial con la
canasta 2004-2005 — el cambio fue anunciado por el INDEC el 14/10/2025 con
entrada en vigencia prevista para enero 2026, pero el Gobierno lo suspendió
en febrero 2026 sin fecha de reemplazo. El dashboard (pestaña "Canasta nueva
vs. vieja") desarrolla esta diferencia con cifras y fuentes.

**Limitación real de las ponderaciones**: el INDEC solo publica en
`sh_ipc_aperturas.xls` los grupos que superan un umbral de peso (2%, o 1.5%
para Alimentos/Bebidas) — 11 subclases de las divisiones 01+02. Categorías
chicas como "Pescados y mariscos" (01.1.3) u "Otros alimentos" (01.1.9) no
tienen ponderación oficial publicada y por lo tanto **nunca pueden entrar al
índice general**, aunque se clasifiquen EANs en esas subclases (quedan
disponibles solo para análisis exploratorio, no para el agregado). La suma
de pesos cargados en `ponderaciones_coicop` no llega al 100% de las
divisiones 01+02 por este motivo — es una limitación de la fuente, no un
error del pipeline.

## 4. Clasificación EAN → subclase COICOP

No existe ningún portal público que publique un diccionario EAN → COICOP
descargable. El mapeo se construye con un proceso de 4 pasos, documentado en
cada script:

1. `generar_lista_clasificacion.py` — arma una lista de trabajo con los EAN
   más relevantes del último dump (por presencia en sucursales/cadenas), con
   una *sugerencia* automática por palabras clave.
2. `clasificar_interactivo.py` — revisión humana de la sugerencia, uno por
   uno, para los casos ambiguos.
3. `autoclasificar_resto.py` — segunda pasada automática (reglas de
   palabras clave más agresivas, con lista negativa para descartar
   productos de limpieza/higiene/mascotas que no son alimentos) sobre lo que
   quedó sin clasificar.
4. `actualizar_diccionario.py` — vuelca lo confirmado a
   `data/diccionario_coicop.csv`, sin pisar clasificaciones previas salvo
   `--pisar` explícito.

Un EAN sin clasificar queda con `coicop_subclase = None` y **no entra al
índice** hasta que alguien lo clasifique — nunca se le asigna una subclase
adivinada para no dejarlo afuera.

Estado al 2026-08-01: 543 EAN clasificados, ~208 quedan ambiguos pendientes
de revisión humana (ver `data/clasificacion_pendiente.csv`).

**Limitación importante — clasificar tarde no recupera cobertura pasada.**
`main.py` (la ingesta diaria) filtra y persiste SOLO las filas ya
clasificadas al momento de correr (`transform.filtrar_division_alimentos_bebidas`,
que descarta todo lo que tenga `coicop_subclase = None`). Un EAN sin
clasificar ese día no se guarda en `registro_precios` — se pierde, no queda
"crudo" en la base para reclasificar después. Si un EAN se clasifica recién
el 2026-08-01, el índice de julio 2026 no lo va a tener aunque el producto
se haya vendido y relevado todo julio: solo empieza a contarse desde el día
que se clasificó en adelante. Por eso conviene clasificar EANs relevantes
(sobre todo en subclases de mucho peso y poca variedad, ver
`diagnostico_cobertura_coicop.py`) lo antes posible, no cuando ya cerró el
mes — la ventana de recuperación real es acotada: `ingesta.py` cachea los
últimos ZIP del SEPA en `data/manual/`, pero el propio dataset SEPA es una
ventana rodante de ~7 días, así que `barrer_semana.py` con el diccionario
ampliado como mucho recupera la última semana cacheada, nunca un mes
completo ya cerrado.

## 5. Cálculo del índice (3 fases, `econometria.py`)

**Fase 0 — filtro de outliers.** Antes de promediar, se descarta cualquier
observación cuyo precio se desvíe más de `config.UMBRAL_OUTLIER_RATIO`
(5×) respecto a la mediana de su EAN en el mes. No se "corrige" el valor —
se excluye la observación.

**Fase I — precio promedio mensual por EAN (media geométrica).** Se agrupan
todas las observaciones diarias/semanales de un EAN en el mes y se calcula
su media geométrica (más robusta que la aritmética frente a outliers
residuales y más apropiada para relativos de precio).

**Fase II — índice elemental de Jevons por subclase.** Para cada EAN con
precio tanto en el período actual como en el período base, se calcula el
relativo `precio_actual / precio_base`. El índice de la subclase es la media
geométrica de esos relativos (fórmula de Jevons, estándar para índices
elementales sin información de cantidades). **Solo se comparan EAN contra sí
mismos** entre ambos períodos — si un EAN no tiene precio en los dos
períodos, no participa. Esto implica que el período base debe compartir
productos reales con el período a medir; no se puede encadenar un producto
sintético/inventado con uno real (la limitación que rompió el primer intento
de calcular julio contra una base de junio sintética — ver
`ESTADO_PENDIENTES.md`).

**Fase III — agregación Laspeyres con ponderaciones fijas ENGHo.** El índice
general es el promedio ponderado de los índices de subclase, con los pesos
de `ponderaciones_coicop` **renormalizados** a las subclases que sí tienen
dato ese mes (para no sesgar el índice a la baja solo porque falten
categorías). Si la cobertura de ponderación (peso cubierto / peso total de
la canasta 01+02) cae por debajo de `config.COBERTURA_MINIMA` (50% por
defecto), **no se publica índice general ese mes** — se prioriza no publicar
un número poco representativo antes que publicar uno inflado con pocas
subclases.

## 6. Período base

`config.PERIODO_BASE`. Definido como el primer mes con precios 100% reales
del SEPA (julio 2026, desde el 2026-08-01 — antes era junio 2026, que era
sintético, ver sección 2). El índice general y por subclase se normalizan a
100 en ese período. La primera variación % mes a mes real aparece recién en
el segundo mes con datos reales (agosto vs. julio).

## 7. Comparación contra series oficiales

`comparativo.py` + endpoints `/comparativo/*` de `api.py`. Se compara contra
tres series, cada una con su propia limitación documentada en el dashboard:

- **GCBA** (Alimentos y Bebidas no alcohólicas, específica de CABA).
- **INDEC GBA Alimentos** (única apertura regional específica de alimentos
  que el INDEC publica — no existe una apertura exclusiva de CABA).
- **INDEC Nivel General Nacional** (benchmark de inflación general, todos
  los rubros — no solo alimentos; el número que se cita habitualmente en
  medios).

Todas las comparaciones son por **variación % mensual de la serie propia**
(no por nivel — cada serie tiene su propia base histórica). Ver sección 3
sobre la diferencia de canasta (nueva vs. vieja) entre este índice y las
series oficiales del INDEC, que explica parte de cualquier diferencia
observada.

## 8. Qué NO es este índice (léase antes de citarlo)

Es una construcción propia (nowcasting) sobre datos públicos reales, no la
medición oficial del INDEC ni la reemplaza. Cubre solo Alimentos y Bebidas
(dos de las 12-13 divisiones del IPC completo), solo CABA, y solo lo que
está clasificado en `diccionario_coicop.csv` (543 EAN al 2026-08-01, con
cobertura de ponderación variable mes a mes). El desglose por rubro del
INDEC contra el que se compara solo existe a nivel regional (GBA), no hay
apertura oficial exclusiva de CABA. Los pesos de la canasta ENGHo 2017-2018
no suman el 100% de las divisiones 01+02 por la limitación de la fuente
descrita en la sección 3.

## 9. Referencias citadas en el dashboard (pestaña "Canasta nueva vs. vieja")

INDEC, gacetilla 14/10/2025 (anuncio del nuevo IPC) · Chequeado,
"El INDEC no actualizó la canasta de bienes y servicios para medir la
inflación" (11/02/2026) · Infobae, "La inflación fue de 1,9% en junio: cuál
hubiera sido el dato con el índice actualizado que el Gobierno postergó"
(15/07/2026) · La Nación, "Cómo será el IPC con una canasta de consumo más
cercana a la realidad" (03/06/2024).
