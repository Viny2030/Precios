"""
econometria.py — Capa B (parte 2): Núcleo econométrico

Implementa las 3 fases descritas en el diseño:
  Fase I:   Precio promedio mensual por EAN (media geométrica de precios
            diarios/observados en el mes, en sucursales de CABA).
  Fase II:  Índice elemental de Jevons por subclase COICOP (media geométrica
            de los relativos de precio respecto al período base).
  Fase III: Agregación Laspeyres con las ponderaciones fijas de la ENGHo.

Antes de Fase I se aplica un control de outliers (config.UMBRAL_OUTLIER_RATIO)
para no dejar que un error de carga (ej. un cero de más) contamine la media
geométrica del mes — se descarta la observación, no se "corrige" inventando
un valor.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

import config

logger = logging.getLogger("econometria")


# ── Control de outliers ─────────────────────────────────────────────────────

def filtrar_outliers(df: pd.DataFrame, col_precio: str = "precio",
                      col_grupo: str = "ean") -> pd.DataFrame:
    """
    Descarta observaciones cuyo precio se desvía más de
    config.UMBRAL_OUTLIER_RATIO veces respecto a la mediana de su EAN en
    el mismo mes. No imputa nada — solo excluye el dato sospechoso.
    """
    if df.empty or col_precio not in df.columns:
        return df

    df = df.copy()
    medianas = df.groupby(col_grupo)[col_precio].transform("median")
    ratio = df[col_precio] / medianas.replace(0, np.nan)
    mask_ok = ratio.between(1 / config.UMBRAL_OUTLIER_RATIO, config.UMBRAL_OUTLIER_RATIO) | medianas.isna()

    descartados = (~mask_ok).sum()
    if descartados:
        logger.warning(f"Outliers descartados: {descartados}/{len(df)} filas "
                        f"(ratio vs. mediana del EAN fuera de "
                        f"[1/{config.UMBRAL_OUTLIER_RATIO}, {config.UMBRAL_OUTLIER_RATIO}])")
    return df[mask_ok].copy()


# ── Fase I: precio promedio mensual por EAN (media geométrica) ─────────────

def _media_geometrica(serie: pd.Series) -> float:
    """Media geométrica numéricamente estable (vía log), ignorando NaN/<=0."""
    valores = serie.dropna()
    valores = valores[valores > 0]
    if valores.empty:
        return float("nan")
    return float(np.exp(np.mean(np.log(valores))))


def precio_promedio_mensual(df: pd.DataFrame, periodo: str,
                             col_precio: str = "precio_normalizado") -> pd.DataFrame:
    """
    Fase I. df debe tener columnas: ean, fecha, <col_precio>.
    Devuelve DataFrame con columnas: ean, periodo, precio_prom, dias_con_dato.
    """
    if df.empty:
        return pd.DataFrame(columns=["ean", "periodo", "precio_prom", "dias_con_dato"])

    df = filtrar_outliers(df, col_precio=col_precio)

    agrupado = df.groupby("ean")[col_precio].agg(
        precio_prom=_media_geometrica,
        dias_con_dato="count",
    ).reset_index()
    agrupado["periodo"] = periodo
    return agrupado


# ── Fase II: índice elemental de Jevons por subclase COICOP ────────────────

def indice_jevons_por_subclase(
    precios_periodo: pd.DataFrame,
    precios_base: pd.DataFrame,
    coicop_por_ean: dict[str, str],
) -> pd.DataFrame:
    """
    Fase II. Calcula, para cada subclase COICOP, el índice de Jevons
    (media geométrica de los relativos P_t/P_t0) usando solo los EAN que
    tienen precio tanto en el período actual como en el base.

    precios_periodo / precios_base: salida de precio_promedio_mensual()
    coicop_por_ean: mapeo ean -> subclase (de transform.cargar_diccionario_coicop)

    Devuelve: DataFrame con columnas coicop_subclase, indice_jevons, n_variedades.
    """
    if precios_periodo.empty or precios_base.empty:
        return pd.DataFrame(columns=["coicop_subclase", "indice_jevons", "n_variedades"])

    merged = precios_periodo.merge(
        precios_base[["ean", "precio_prom"]].rename(columns={"precio_prom": "precio_base"}),
        on="ean", how="inner",
    )
    merged = merged[(merged["precio_prom"] > 0) & (merged["precio_base"] > 0)]
    # EANs en la BD son BigInteger; en el diccionario COICOP son str (para
    # preservar ceros a la izquierda). Convertimos acá para que el .map()
    # matchee — no tocamos transform.cargar_diccionario_coicop porque otros
    # consumidores dependen del formato str.
    merged["coicop_subclase"] = merged["ean"].astype(str).map(coicop_por_ean)
    merged = merged.dropna(subset=["coicop_subclase"])

    if merged.empty:
        logger.warning(
            "Ningún EAN con precio en ambos períodos tiene subclase COICOP asignada — "
            "revisar data/diccionario_coicop.csv"
        )
        return pd.DataFrame(columns=["coicop_subclase", "indice_jevons", "n_variedades"])

    merged["relativo"] = merged["precio_prom"] / merged["precio_base"]

    resultado = merged.groupby("coicop_subclase").agg(
        indice_jevons=("relativo", _media_geometrica),
        n_variedades=("ean", "nunique"),
    ).reset_index()
    resultado["indice_jevons"] *= 100  # base = 100
    return resultado


# ── Fase III: agregación Laspeyres con ponderaciones ENGHo ──────────────────

def agregacion_laspeyres(
    indices_subclase: pd.DataFrame,
    ponderaciones: pd.DataFrame,
) -> Optional[dict]:
    """
    Fase III. indices_subclase: salida de indice_jevons_por_subclase()
    ponderaciones: DataFrame con columnas coicop_subclase, ponderacion_caba

    Devuelve dict con indice_general, cobertura_ponderacion (qué fracción
    del peso total tiene datos este período), y detalle por subclase.
    Si la cobertura es muy baja, devuelve None en vez de un índice poco
    representativo — mejor no publicar un número que publicar uno inflado
    con muy pocas subclases.
    """
    if indices_subclase.empty or ponderaciones.empty:
        logger.error("Sin índices elementales o sin ponderaciones — no se puede agregar")
        return None

    merged = indices_subclase.merge(ponderaciones, on="coicop_subclase", how="inner")
    if merged.empty:
        logger.error("Ninguna subclase con índice calculado coincide con las ponderaciones cargadas")
        return None

    peso_total_canasta = ponderaciones["ponderacion_caba"].sum()
    peso_cubierto = merged["ponderacion_caba"].sum()
    cobertura = float(peso_cubierto / peso_total_canasta) if peso_total_canasta else 0.0

    if cobertura < config.COBERTURA_MINIMA:
        logger.warning(
            f"Cobertura de ponderación muy baja ({cobertura:.1%}, mínimo "
            f"{config.COBERTURA_MINIMA:.0%}) — el índice de este período no sería "
            f"representativo. No se calcula un valor."
        )
        return None

    # Se re-normalizan los pesos a las subclases con dato disponible, para no
    # sesgar el índice hacia abajo solo porque falten subclases sin datos.
    merged["peso_renormalizado"] = merged["ponderacion_caba"] / peso_cubierto
    indice_general = float((merged["indice_jevons"] * merged["peso_renormalizado"]).sum())

    return {
        "indice_general": indice_general,
        "cobertura_ponderacion": cobertura,
        "n_subclases": len(merged),
        "detalle": merged[["coicop_subclase", "indice_jevons", "ponderacion_caba", "n_variedades"]]
        .to_dict(orient="records"),
    }


# ── Imputación por subgrupo (para EAN con quiebre de stock puntual) ─────────

def imputar_variacion_subgrupo(
    df_precios: pd.DataFrame,
    coicop_por_ean: dict[str, str],
    col_precio: str = "precio_normalizado",
) -> pd.DataFrame:
    """
    Para EAN que faltan en una semana puntual (no en todo el mes — eso ya lo
    absorbe la media geométrica de Fase I), imputa usando la variación
    promedio de su subgrupo COICOP inmediato en esa semana, en vez de
    inventar un precio para ese EAN específico. Requiere columna 'semana'
    (period W) ya calculada en df_precios.
    """
    if df_precios.empty or "semana" not in df_precios.columns:
        return df_precios

    df = df_precios.copy()
    df["coicop_subclase"] = df["ean"].map(coicop_por_ean)

    variacion_subgrupo = (
        df.groupby(["coicop_subclase", "semana"])[col_precio]
        .apply(lambda s: s.pct_change().mean())
        .rename("variacion_subgrupo_pct")
        .reset_index()
    )

    df = df.merge(variacion_subgrupo, on=["coicop_subclase", "semana"], how="left")
    return df
