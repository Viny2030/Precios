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
"""
from __future__ import annotations

import io
import logging

import pandas as pd
import requests

import config

logger = logging.getLogger("comparativo")

URL_API_INDEC_IPC = (
    f"{config.SERIES_API_BASE}?ids={config.SERIE_IPC_GBA_ALIMENTOS}&format=csv&limit=1000"
)

URL_APERTURAS_INDEC = "https://www.indec.gob.ar/ftp/cuadros/economia/sh_ipc_aperturas.xls"

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


def obtener_historico_indec() -> pd.DataFrame:
    """Devuelve DataFrame con columnas ['fecha' (Period 'M'),
    'indice_oficial_alimentos'] o vacío si la descarga falla. Nivel general
    (Alimentos y Bebidas GBA), NO por rubro — para eso ver
    obtener_indices_indec_por_rubro()."""
    logger.info("Conectando con la API de Series de Tiempo (INDEC)...")
    try:
        r = requests.get(
            URL_API_INDEC_IPC,
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
