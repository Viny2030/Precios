"""
comparativo.py — Descarga las series oficiales del INDEC de Alimentos y
Bebidas (GBA) desde la API pública de Series de Tiempo y desde el archivo
de aperturas por capítulos, para comparar contra el índice propio, tanto a
nivel general como por rubro (subclase COICOP).

La API/archivos a veces devuelven 403 a pedidos sin User-Agent (WAF
anti-bot). Por eso descargamos con requests + User-Agent honesto
(config.USER_AGENT), en vez de dejarle la descarga a pandas directo.

CORREGIDO 2026-07-05: el ID de serie que se usaba acá ("148.3_INDEC_GBA_01_0_24")
ya no existe en el catálogo de datos.gob.ar (devuelve 400) — probablemente
quedó de una versión anterior del catálogo. El ID vigente y verificado es
"101.1_I2AB_2016_M_26" ("IPC-GBA. Alimentos y Bebidas. Base dic 2016.
Mensual", valores de ÍNDICE, no de incidencia ni de variación), que ya
estaba correctamente declarado en config.SERIE_IPC_GBA_ALIMENTOS pero no se
usaba acá. Ahora se toma de ahí para no tener el ID duplicado en dos lugares.
Se agregó también "&limit=1000" — sin eso la API solo devuelve los primeros
100 meses de la serie (arranca en dic-2016), no los últimos.

AGREGADO 2026-07-05: obtener_indices_indec_por_rubro() — para el
comparativo POR RUBRO (no solo el total), el INDEC sí publica un desglose
regional por "principales aperturas" (el mismo archivo que usa
precios_seed_ponderaciones.py para las ponderaciones, pero en la hoja
"Índices aperturas" en vez de "Ponderaciones"). Esa hoja trae, para la
región GBA, el nivel de índice mensual de cada rubro (Pan y cereales,
Carnes y derivados, etc.) — exactamente la misma agrupación que usamos
para las 11 subclases COICOP de la canasta.

AGREGADO 2026-07-10: funciones persistir_serie() / actualizar_serie_*() —
antes la lógica de "bajar del INDEC y guardar en serie_comparativa_indec"
vivía duplicada dentro de sembrar_desarrollo.py (que además mezcla eso con
la siembra de precios sintéticos). Se movió acá para poder reusarla desde
un script liviano (actualizar_series_oficiales.py) que SOLO refresca las
series de comparación —sin tocar sintéticos— pensado para correr después
del día 14 de cada mes (cuando el INDEC/GCBA publican el dato del mes
anterior). Se agregó también actualizar_serie_gcba_alimentos(): la serie
config.SERIE_IPC_CABA_ALIMENTOS estaba declarada en config.py pero nunca
se descargaba ni se guardaba en ningún lado — por eso el comparativo
general nunca podía mostrar GCBA, solo INDEC.
"""
from __future__ import annotations

import io
import logging

import pandas as pd
import requests
from sqlalchemy.orm import Session

import config
from models import SerieComparativaINDEC

logger = logging.getLogger("comparativo")

URL_APERTURAS_INDEC = "https://www.indec.gob.ar/ftp/cuadros/economia/sh_ipc_aperturas.xls"


def _url_serie(serie_id: str) -> str:
    return f"{config.SERIES_API_BASE}?ids={serie_id}&format=csv&limit=1000"

# Mismo mapeo que usa precios_seed_ponderaciones.py para las ponderaciones
# (nombre de fila tal como aparece en el archivo del INDEC -> código COICOP
# de grupo). Se repite acá en vez de importarlo para no acoplar este módulo
# a precios_seed_ponderaciones.py; si el INDEC cambia los nombres de fila,
# hay que actualizar los dos lugares (son solo 11 líneas).
MAPEO_FILA_A_CODIGO = {
    "Pan y cereales": "01.1.1",
    "Carnes y derivados": "01.1.2",
    "Leche, productos lácteos y huevos": "01.1.4",
    "Aceites, grasas y manteca": "01.1.5",
    "Frutas": "01.1.6",
    "Verduras, tubérculos y legumbres": "01.1.7",
    "Azúcar, dulces, chocolate, golosinas, etc.": "01.1.8",
    "Café, té, yerba y cacao": "01.2.1",
    "Aguas minerales, bebidas gaseosas y jugos": "01.2.2",
    "Bebidas alcohólicas": "02.1",
    "Tabaco": "02.2.1",
}


def _normalizar_nombre_rubro(nombre: str) -> str:
    """Los nombres de fila no son 100% idénticos entre hojas del mismo
    archivo del INDEC (ej. 'etc.' vs 'etc,' al final) — se normaliza
    quitando espacios y puntuación de cierre antes de comparar."""
    return str(nombre).strip().rstrip(".,").strip()


_MAPEO_NORMALIZADO = {_normalizar_nombre_rubro(k): v for k, v in MAPEO_FILA_A_CODIGO.items()}


def obtener_historico_indec(serie_id: str | None = None) -> pd.DataFrame:
    """Devuelve DataFrame con columnas ['fecha' (Period 'M'),
    'indice_oficial_alimentos'] o vacío si la descarga falla, para la serie
    pedida (por defecto config.SERIE_IPC_GBA_ALIMENTOS, la que se usa para
    calibrar los precios sintéticos). Para el comparativo general contra el
    Nivel General Nacional, llamar con serie_id=config.SERIE_IPC_NACIONAL_NIVEL_GENERAL.
    NO es por rubro — para eso ver obtener_indices_indec_por_rubro()."""
    serie_id = serie_id or config.SERIE_IPC_GBA_ALIMENTOS
    logger.info(f"Conectando con la API de Series de Tiempo (INDEC) — serie {serie_id}...")
    try:
        r = requests.get(
            _url_serie(serie_id),
            headers={"User-Agent": config.USER_AGENT, "Accept": "text/csv"},
            timeout=60,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Error al conectar con la API de series: {e}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        logger.error(f"Respuesta del INDEC no parseable como CSV: {e}")
        return pd.DataFrame()

    if df.empty or df.shape[1] < 2:
        logger.error("La API devolvió una tabla vacía o mal formada")
        return pd.DataFrame()

    df.columns = ["fecha", "indice_oficial_alimentos"]
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.to_period("M")

    logger.info(f"Serie oficial recuperada. Último dato disponible: {df['fecha'].max()}")
    return df


def obtener_indices_indec_por_rubro(columna_region: str = "GBA") -> pd.DataFrame:
    """
    Descarga sh_ipc_aperturas.xls y devuelve, para la región pedida, el
    nivel de índice mensual de cada rubro que tiene equivalente en
    MAPEO_FILA_A_CODIGO (las 11 subclases de la canasta 01+02).

    Devuelve DataFrame en formato largo: columnas
    ['fecha' (Period 'M'), 'coicop_subclase', 'indice_indec'].
    Vacío si la descarga o el parseo fallan.
    """
    try:
        logger.info(f"Descargando {URL_APERTURAS_INDEC} (hoja 'Índices aperturas')...")
        resp = requests.get(URL_APERTURAS_INDEC, headers={"User-Agent": config.USER_AGENT}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"No se pudo descargar {URL_APERTURAS_INDEC}: {e}")
        return pd.DataFrame()

    try:
        df_raw = pd.read_excel(io.BytesIO(resp.content), sheet_name="Índices aperturas", header=None)
    except Exception as e:
        logger.error(f"No se pudo leer la hoja 'Índices aperturas': {e}")
        return pd.DataFrame()

    etiqueta_region = f"Región {columna_region}"
    filas_region = df_raw[df_raw[0].astype(str).str.strip() == etiqueta_region].index
    if len(filas_region) == 0:
        logger.error(f"No se encontró la fila '{etiqueta_region}' en el archivo del INDEC")
        return pd.DataFrame()
    idx_region = filas_region[0]

    # El bloque de la región termina en la próxima fila "Región X" (o al
    # final de la hoja si es la última región).
    todas_regiones = df_raw[df_raw[0].astype(str).str.strip().str.startswith("Región", na=False)].index
    posteriores = [i for i in todas_regiones if i > idx_region]
    idx_fin = min(posteriores) if posteriores else len(df_raw)

    fechas = df_raw.iloc[idx_region, 1:]
    fechas = pd.to_datetime(fechas, errors="coerce")

    filas_largas = []
    for i in range(idx_region + 1, idx_fin):
        etiqueta = df_raw.iloc[i, 0]
        if not isinstance(etiqueta, str):
            continue
        codigo = _MAPEO_NORMALIZADO.get(_normalizar_nombre_rubro(etiqueta))
        if codigo is None:
            continue  # rubro sin equivalente en nuestra canasta (ropa, transporte, etc.)

        valores = pd.to_numeric(df_raw.iloc[i, 1:], errors="coerce")
        for fecha, valor in zip(fechas, valores):
            if pd.isna(fecha) or pd.isna(valor):
                continue
            filas_largas.append({
                "fecha": pd.Period(fecha, freq="M"),
                "coicop_subclase": codigo,
                "indice_indec": float(valor),
            })

    df_largo = pd.DataFrame(filas_largas)
    if df_largo.empty:
        logger.error("No se extrajo ningún rubro — revisar MAPEO_FILA_A_CODIGO / formato del archivo")
        return df_largo

    n_rubros = df_largo["coicop_subclase"].nunique()
    logger.info(f"Índices por rubro (región {columna_region}): {n_rubros}/{len(MAPEO_FILA_A_CODIGO)} "
                f"rubros con serie, hasta {df_largo['fecha'].max()}")
    return df_largo


# ── Persistencia en serie_comparativa_indec ─────────────────────────────────
# A partir de acá: funciones que bajan una serie oficial y la vuelcan a la
# base, para que la API (api.py) y el dashboard (rubros.html) las puedan leer
# sin volver a pegarle a datos.gob.ar/INDEC en cada request.

def persistir_serie(db: Session, df: pd.DataFrame, serie_id: str, etiqueta: str) -> pd.DataFrame:
    """Vuelca un DataFrame de obtener_historico_indec() (columnas 'fecha',
    'indice_oficial_alimentos') a serie_comparativa_indec bajo el serie_id
    pedido. Upsert por (fecha, serie_id). No hace commit si el DataFrame
    viene vacío (descarga falló)."""
    if df.empty:
        logger.error(f"No se pudo bajar la serie oficial ({etiqueta}, {serie_id}) — se sigue sin ella")
        return df

    df = df.copy()
    df["fecha"] = df["fecha"].dt.to_timestamp().dt.date

    insertados = 0
    actualizados = 0
    for _, fila in df.iterrows():
        existente = db.query(SerieComparativaINDEC).filter_by(
            fecha=fila["fecha"], serie_id=serie_id
        ).first()
        if existente:
            if float(existente.valor) != float(fila["indice_oficial_alimentos"]):
                existente.valor = fila["indice_oficial_alimentos"]
                actualizados += 1
        else:
            db.add(SerieComparativaINDEC(
                fecha=fila["fecha"], serie_id=serie_id, valor=fila["indice_oficial_alimentos"],
            ))
            insertados += 1

    db.commit()
    logger.info(f"Serie oficial ({etiqueta}): {insertados} filas nuevas, {actualizados} actualizadas "
                f"(último dato: {df['fecha'].max()})")
    return df


def actualizar_serie_gba_alimentos(db: Session) -> pd.DataFrame:
    """Serie de CALIBRACIÓN (Alimentos y Bebidas GBA, INDEC) — de acá salen
    las variaciones que usa sembrar_desarrollo.py para armar el sintético
    abril/mayo/junio."""
    df = obtener_historico_indec(config.SERIE_IPC_GBA_ALIMENTOS)
    return persistir_serie(db, df, config.SERIE_IPC_GBA_ALIMENTOS, "Alimentos y Bebidas GBA (INDEC)")


def actualizar_serie_nacional_general(db: Session) -> pd.DataFrame:
    """Serie de BENCHMARK Nivel General Nacional (INDEC) — la que sale en
    los diarios como "la inflación del mes". Alimenta /comparativo/{periodo}
    y /comparativo/evolucion/general."""
    df = obtener_historico_indec(config.SERIE_IPC_NACIONAL_NIVEL_GENERAL)
    return persistir_serie(db, df, config.SERIE_IPC_NACIONAL_NIVEL_GENERAL, "Nivel General Nacional (INDEC)")


def actualizar_serie_gcba_alimentos(db: Session) -> pd.DataFrame:
    """Serie oficial del GCBA (Alimentos y Bebidas no alcohólicas, específica
    de CABA — no una región agregada como GBA). Estaba declarada en
    config.SERIE_IPC_CABA_ALIMENTOS pero, hasta ahora, nunca se descargaba:
    esta función es la que faltaba para que el comparativo general pueda
    mostrar GCBA además de INDEC."""
    df = obtener_historico_indec(config.SERIE_IPC_CABA_ALIMENTOS)
    return persistir_serie(
        db, df, config.SERIE_IPC_CABA_ALIMENTOS,
        "Alimentos y Bebidas no alcohólicas CABA (GCBA)",
    )


def actualizar_indec_por_rubro(db: Session, columna_region: str = "GBA") -> pd.DataFrame:
    """Descarga las aperturas por rubro del INDEC (obtener_indices_indec_por_rubro)
    y las vuelca a serie_comparativa_indec con serie_id = 'APERTURA_<coicop_subclase>'.
    Alimenta /comparativo/{periodo}/rubros y /comparativo/evolucion/rubro/{coicop}."""
    df = obtener_indices_indec_por_rubro(columna_region)
    if df.empty:
        logger.warning("No se pudo bajar el desglose por rubro del INDEC — los endpoints "
                        "de comparativo por rubro van a quedar sin datos INDEC por ahora.")
        return df

    df = df.copy()
    df["fecha"] = df["fecha"].dt.to_timestamp().dt.date

    insertados = 0
    actualizados = 0
    for _, fila in df.iterrows():
        serie_id = f"APERTURA_{fila['coicop_subclase']}"
        existente = db.query(SerieComparativaINDEC).filter_by(
            fecha=fila["fecha"], serie_id=serie_id
        ).first()
        if existente:
            if float(existente.valor) != float(fila["indice_indec"]):
                existente.valor = fila["indice_indec"]
                actualizados += 1
        else:
            db.add(SerieComparativaINDEC(
                fecha=fila["fecha"], serie_id=serie_id, valor=fila["indice_indec"],
            ))
            insertados += 1

    db.commit()
    logger.info(f"Índices INDEC por rubro: {insertados} filas nuevas, {actualizados} actualizadas "
                f"({df['coicop_subclase'].nunique()} rubros, hasta {df['fecha'].max()})")
    return df


def actualizar_todas_las_series(db: Session) -> dict[str, pd.DataFrame]:
    """Descarga y persiste las 4 series oficiales que usa el sistema (GBA
    Alimentos, Nacional Nivel General, GCBA Alimentos CABA, aperturas por
    rubro). Punto de entrada único, usado tanto por sembrar_desarrollo.py
    (bootstrap con sintéticos) como por actualizar_series_oficiales.py
    (refresco periódico sin tocar sintéticos)."""
    return {
        "gba_alimentos": actualizar_serie_gba_alimentos(db),
        "nacional_general": actualizar_serie_nacional_general(db),
        "gcba_alimentos": actualizar_serie_gcba_alimentos(db),
        "aperturas_rubro": actualizar_indec_por_rubro(db),
    }
