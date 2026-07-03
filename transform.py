"""
transform.py — Capa B (parte 1): Normalización de variedades y mapeo COICOP

Dos responsabilidades:
  1. Normalizar el precio a unidad de medida homogénea (precio/kg, precio/l,
     precio/unidad) extrayendo el contenido neto del nombre del producto.
  2. Mapear cada EAN a su subclase COICOP.

Sobre el mapeo COICOP — leer antes de asumir que esto es automático:
No existe ningún portal público que publique un diccionario EAN → subclase
COICOP descargable (a diferencia del IPC o el tipo de cambio, que sí tienen
APIs). El propio documento de diseño original lo resuelve con un
"diccionario de equivalencias automatizado", pero ese diccionario hay que
construirlo — no se puede bajar de ningún lado sin inventarlo.

La forma correcta de encararlo (y la única consistente con "cero datos
sintéticos"): mantener data/diccionario_coicop.csv con pares EAN→subclase
que se van cargando a mano a medida que se identifican productos reales.
Los EAN sin clasificar quedan con coicop_subclase = None y no entran al
índice hasta que alguien los clasifique — no se les asigna una subclase
adivinada.

NOTA SOBRE EANs (corregido 2026-07-03): los EAN se manejan SIEMPRE como
string, nunca como int. Los códigos UPC/GTIN pueden traer ceros a la
izquierda significativos (ej. "0022000006653" en el dump real del SEPA), y
además Excel suele comérselos al editar CSVs. Para que el matching sea
inmune a ambas cosas, los dos lados (diccionario y datos) se comparan en
forma canónica: solo dígitos, sin ceros a la izquierda (ver _canon_ean).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd

import config

logger = logging.getLogger("transform")

DICCIONARIO_COICOP_PATH = Path(config.DATA_DIR) / "diccionario_coicop.csv"

# Patrones para extraer contenido neto del nombre del producto.
# Cubre los formatos más comunes en Argentina: "500g", "1.5L", "250cc", "12u".
_PATRON_CONTENIDO = re.compile(
    r"(\d+[.,]?\d*)\s*(kg|kgs|g|gr|grs|l|lt|lts|litro|litros|cc|ml|u|un|unid|unidades)\b",
    re.IGNORECASE,
)

_EQUIVALENCIAS_A_BASE = {
    # normaliza todo a kg (peso) o l (volumen) o unidad
    "kg": ("kg", 1.0), "kgs": ("kg", 1.0),
    "g": ("kg", 0.001), "gr": ("kg", 0.001), "grs": ("kg", 0.001),
    "l": ("l", 1.0), "lt": ("l", 1.0), "lts": ("l", 1.0),
    "litro": ("l", 1.0), "litros": ("l", 1.0),
    "cc": ("l", 0.001), "ml": ("l", 0.001),
    "u": ("unidad", 1.0), "un": ("unidad", 1.0), "unid": ("unidad", 1.0), "unidades": ("unidad", 1.0),
}


def _canon_ean(valor) -> Optional[str]:
    """
    Forma canónica de un EAN para matching: solo dígitos, sin ceros a la
    izquierda. Devuelve None si no queda ningún dígito.
    Maneja también EANs que llegan como float por culpa de Excel/pandas
    (ej. 7790895000997.0 → "7790895000997").
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    s = str(valor).strip()
    if s.endswith(".0"):  # float serializado
        s = s[:-2]
    digitos = re.sub(r"\D", "", s)
    digitos = digitos.lstrip("0")
    return digitos or None


def extraer_contenido_neto(nombre_producto: str) -> tuple[Optional[float], Optional[str]]:
    """
    Busca un patrón tipo '500g' o '1.5L' en el nombre y devuelve
    (contenido_en_unidad_base, unidad_base). Si no encuentra nada,
    devuelve (None, None) — no inventa un valor por defecto.
    """
    if not isinstance(nombre_producto, str):
        return None, None
    m = _PATRON_CONTENIDO.search(nombre_producto)
    if not m:
        return None, None
    valor_str, unidad_raw = m.groups()
    try:
        valor = float(valor_str.replace(",", "."))
    except ValueError:
        return None, None
    unidad_base, factor = _EQUIVALENCIAS_A_BASE.get(unidad_raw.lower(), (None, None))
    if unidad_base is None:
        return None, None
    return valor * factor, unidad_base


def normalizar_precios(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega columnas contenido_neto, unidad_medida y precio_normalizado
    (precio por kg/l/unidad) a partir de la columna 'nombre'.
    Filas donde no se pudo extraer el contenido quedan con
    precio_normalizado = NaN (no se inventa un valor).
    """
    df = df.copy()
    if "nombre" not in df.columns:
        logger.warning("No hay columna 'nombre' — no se puede normalizar contenido neto")
        df["contenido_neto"] = None
        df["unidad_medida"] = None
        df["precio_normalizado"] = None
        return df

    extraidos = df["nombre"].apply(extraer_contenido_neto)
    df["contenido_neto"] = extraidos.apply(lambda t: t[0])
    df["unidad_medida"] = extraidos.apply(lambda t: t[1])

    precio_col = "precio" if "precio" in df.columns else None
    if precio_col:
        df["precio_normalizado"] = df.apply(
            lambda r: (r[precio_col] / r["contenido_neto"])
            if pd.notna(r["contenido_neto"]) and r["contenido_neto"] > 0
            else None,
            axis=1,
        )
    else:
        df["precio_normalizado"] = None

    sin_normalizar = df["precio_normalizado"].isna().sum()
    if sin_normalizar:
        logger.info(
            f"{sin_normalizar}/{len(df)} filas sin contenido neto detectable en el "
            f"nombre — quedan sin precio_normalizado (no se les inventa un valor)."
        )
    return df


def cargar_diccionario_coicop() -> dict[str, str]:
    """
    Carga el diccionario EAN -> coicop_subclase desde
    data/diccionario_coicop.csv, con los EAN en forma canónica (string,
    solo dígitos, sin ceros a la izquierda). Si el archivo no existe, lo
    crea vacío con el header correcto y devuelve {} — el sistema sigue
    funcionando, simplemente ningún producto queda clasificado hasta que
    se cargue.
    """
    if not DICCIONARIO_COICOP_PATH.exists():
        DICCIONARIO_COICOP_PATH.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=["ean", "coicop_subclase"]).to_csv(DICCIONARIO_COICOP_PATH, index=False)
        logger.warning(
            f"No existía {DICCIONARIO_COICOP_PATH} — se creó vacío. "
            f"El índice no va a tener productos clasificados hasta que se cargue a mano."
        )
        return {}

    # dtype=str: NUNCA dejar que pandas convierta los EAN a número (pierde
    # ceros a la izquierda y puede pasarlos a notación float).
    df = pd.read_csv(DICCIONARIO_COICOP_PATH, dtype=str)
    if df.empty:
        logger.warning(f"{DICCIONARIO_COICOP_PATH} existe pero está vacío.")
        return {}

    diccionario: dict[str, str] = {}
    for ean_raw, subclase in zip(df["ean"], df["coicop_subclase"]):
        ean = _canon_ean(ean_raw)
        if ean and isinstance(subclase, str) and subclase.strip():
            diccionario[ean] = subclase.strip()
    logger.info(f"Diccionario COICOP cargado: {len(diccionario)} EANs clasificados")
    return diccionario


def clasificar_coicop(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega la columna coicop_subclase mapeando por EAN (en forma canónica)
    contra el diccionario cargado. Los EAN sin entrada quedan con NaN.
    """
    df = df.copy()
    diccionario = cargar_diccionario_coicop()
    if "ean" not in df.columns:
        logger.error("No hay columna 'ean' — no se puede clasificar por COICOP")
        df["coicop_subclase"] = None
        return df

    df["coicop_subclase"] = df["ean"].map(lambda e: diccionario.get(_canon_ean(e)))

    clasificados = df["coicop_subclase"].notna().sum()
    total = len(df)
    logger.info(
        f"Clasificación COICOP: {clasificados}/{total} filas ({clasificados/total:.1%} "
        f"si total>0) — el resto necesita cargarse en {DICCIONARIO_COICOP_PATH.name}"
    )
    return df


def filtrar_division_alimentos_bebidas(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra a las divisiones COICOP 01 y 02, según config.DIVISIONES_COICOP."""
    if "coicop_subclase" not in df.columns:
        return df.iloc[0:0]
    mask = df["coicop_subclase"].astype(str).str[:2].isin(config.DIVISIONES_COICOP)
    return df[mask].copy()