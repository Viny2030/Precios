# Analizador de Precios CABA — Nueva Canasta COICOP

Sistema de *nowcasting* del Índice de Precios de Alimentos y Bebidas para
CABA, bajo la **Nueva Canasta de Consumo (ENGHo 2017-2018)** y la
clasificación **COICOP**, cruzando los datos diarios del SEPA (Precios
Claros) con las ponderaciones de la nueva canasta y comparándolo contra el
IPC oficial rezagado del INDEC/GCBA.

## ⚖️ Marco legal

Bajo la **Ley N° 27.275 de Derecho de Acceso a la Información Pública**,
este sistema usa exclusivamente fuentes oficiales, abiertas y públicas.
**Cero datos sintéticos**: donde falta información real (un producto sin
clasificar, un mes sin ponderación cargada), el sistema no calcula ni
publica un número — prefiere quedarse sin dato antes que inventar uno.

## ⚠️ Estado real de las fuentes (verificado 2026-07-02)

Antes de asumir que este pipeline corre solo de punta a punta, es importante
saber esto — se probó cada URL en vivo, no se copió de ningún documento sin
confirmar:

| Fuente | Estado | Detalle |
|---|---|---|
| SEPA — catálogo de recursos (CKAN) | ✅ Funciona | `datos.gob.ar/api/3/action/package_show` devuelve los links reales, actualizados a diario |
| SEPA — descarga del ZIP diario | ❌ **Bloqueada** | El dominio `datos.produccion.gob.ar` tiene un WAF que devuelve 403 a pedidos automatizados (probado con varios User-Agent, tanto en la página del dataset como en los recursos individuales) |
| API de Series de Tiempo (IPC INDEC/GCBA) | ✅ Funciona | Series reales verificadas, ver `config.py` |
| BA Data — dataset "supermercados" | ❌ No existe con ese nombre | Se resolvió sin necesitarlo: el SEPA ya trae el código de provincia en cada fila, así que se filtra directo por `provincia == "02"` (CABA) |
| Dataset de ponderaciones listo para descargar | ✅ Existe (a nivel grupo, no subclase completa) | `indec.gob.ar/ftp/cuadros/economia/sh_ipc_aperturas.xls` — ver `seed_ponderaciones.py` |

**El WAF del SEPA no es un bug de este código** — es una protección real del
servidor del Ministerio que bloquea scripts. No se intentó evadirlo (eso no
sería correcto aunque el dato sea público). En cambio, `ingesta.py` tiene un
**modo manual**: descargá el ZIP del día desde un navegador y colocalo en
`data/manual/<dia>.zip` (ej. `data/manual/jueves.zip`) — el pipeline lo va a
usar automáticamente la próxima vez que corra, sin más cambios.

Si el bloqueo es un problema persistente para tu caso de uso, el protocolo
correcto bajo la Ley 27.275 es una solicitud formal vía **TAD (Trámites a
Distancia)** a la Dirección Nacional de Defensa del Consumidor pidiendo el
*dump* mensual en formato de archivo abierto.

## 🛠️ Instalación

```bash
pip install -r requirements.txt
python models.py               # crea las tablas (SQLite por defecto)
python seed_ponderaciones.py   # carga las ponderaciones reales del INDEC
```

Para usar PostgreSQL en vez de SQLite, seteá `DATABASE_URL` como variable
de entorno antes de correr cualquier script.

## 🚀 Uso

```bash
python main.py                          # pipeline diario (ingesta + transform + persistencia)
python calcular_indice_mensual.py 2026-02   # cierra el mes y calcula el índice
streamlit run app.py                    # dashboard online
```

Para automatizar la corrida diaria, asociá `main.py` a un cron job (Linux/Mac)
o al Task Scheduler (Windows) a las 4:00 AM.

## 📁 Estructura

```
config.py          # URLs oficiales verificadas y parámetros
models.py           # Esquema SQLAlchemy (5 tablas)
seed_ponderaciones.py  # Descarga y carga las ponderaciones reales del INDEC
ingesta.py           # Capa A: descarga SEPA + filtrado CABA por chunks
transform.py         # Capa B (1): normalización de unidades + mapeo COICOP
econometria.py        # Capa B (2): Fórmulas de Jevons y Laspeyres
comparativo.py        # Serie oficial INDEC/GCBA para contraste
main.py              # Orquestador del pipeline diario
calcular_indice_mensual.py  # Cierre de mes: corre las 3 fases y persiste
app.py               # Dashboard (Streamlit)
```

## ✅ Ponderaciones COICOP (`ponderaciones_coicop`) — actualización

**Corrección respecto a una versión anterior de este README**: sí existe una
fuente real y descargable con ponderaciones oficiales — no es la ENGHo
cruda (esa sí requiere navegación manual), pero es la estructura de pesos
que el propio INDEC usa para el IPC, publicada en
`indec.gob.ar/ftp/cuadros/economia/sh_ipc_aperturas.xls` (hoja
"Ponderaciones", región GBA — la apertura regional más específica
disponible, ya que no hay una apertura exclusiva de CABA en este archivo).

Corré `python seed_ponderaciones.py` para cargarlas automáticamente —
descarga el Excel real del INDEC, lo parsea, y llena `ponderaciones_coicop`
con 11 grupos reales (Pan y cereales, Carnes, Lácteos, etc.), cada uno con
su código COICOP verificado contra el clasificador oficial.

**Limitación real que hay que conocer**: esta tabla del INDEC solo publica
los grupos que superan cierto umbral de peso — quedan afuera categorías
chicas como "Pescados y mariscos" u "Otros alimentos" (no se desagregan
en esta publicación). La suma de los pesos cargados no llega al 100% de
las divisiones 01+02 por ese motivo, no por un error de carga.
`econometria.agregacion_laspeyres()` ya maneja esto: renormaliza los pesos
disponibles antes de agregar, en vez de asumir que suman 1.0.

Y el nivel de detalle es "grupo" COICOP (3 segmentos, ej. `01.1.1`), no
"subclase" completa (4 segmentos, ej. `01.1.1.1`) — para bajar a ese nivel
de detalle sí haría falta la ENGHo cruda. Es un nivel de agregación
razonable para un índice de este tipo (coincide, de hecho, con el ejemplo
"01.1.2 Carnes" que cita el propio documento de diseño original).

## ⚠️ Diccionario EAN → COICOP (`data/diccionario_coicop.csv`)

Mismo criterio: no existe una fuente pública descargable que mapee cada
código de barras a su subclase COICOP. Se arranca vacío y se completa a
mano, identificando los EAN más frecuentes en las primeras corridas y
clasificándolos contra el
[nomenclador COICOP de Naciones Unidas](https://unstats.un.org/). Los EAN
sin clasificar quedan fuera del índice — no se les asigna una subclase
adivinada por similitud de nombre ni nada parecido.

## 📊 Metodología (resumen)

1. **Fase I** — Precio promedio mensual por EAN: media geométrica de los
   precios observados en el mes en sucursales de CABA (con control de
   outliers: se descarta, no se corrige, una observación que se desvíe más
   de 5x de la mediana del EAN en ese mes).
2. **Fase II** — Índice elemental de Jevons por subclase COICOP: media
   geométrica de los relativos de precio (mes actual / período base).
3. **Fase III** — Agregación Laspeyres con las ponderaciones fijas de la
   ENGHo. Si la cobertura de ponderación de un período es menor al 50%
   (muy pocas subclases con datos), el sistema no publica un índice general
   para ese período — mejor sin dato que un número no representativo.

## 📊 Tecnologías

- Python 3.10+
- Pandas, NumPy, SQLAlchemy
- Streamlit + Plotly para el dashboard
- SQLite (desarrollo) / PostgreSQL (producción)
