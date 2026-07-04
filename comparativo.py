"""
comparativo.py — Descarga la serie oficial del INDEC de Alimentos y Bebidas
para GBA/CABA desde la API pública de Series de Tiempo del Min. de Economía.

La API a veces devuelve 403 a pedidos sin User-Agent (WAF anti-bot). Por eso
descargamos con requests + User-Agent honesto (config.USER_AGENT), en vez de
dejarle la descarga a pandas.read_csv() directo.
"""
from __future__ import annotations

import io
import logging

import pandas as pd
import requests

import config

logger = logging.getLogger("comparativo")

URL_API_INDEC_IPC = (
    "https://apis.datos.gob.ar/series/api/series/"
    "?ids=148.3_INDEC_GBA_01_0_24&format=csv"
)


def obtener_historico_indec() -> pd.DataFrame:
    """Devuelve DataFrame con columnas ['fecha' (Period 'M'),
    'indice_oficial_alimentos'] o vacío si la descarga falla."""
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
