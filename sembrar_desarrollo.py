"""
sembrar_desarrollo.py — SOLO PARA DESARROLLO. NO USAR EN PRODUCCIÓN.

Genera precios sintéticos para abril y mayo 2026 derivados de los precios
reales de junio 2026, aplicando las variaciones mensuales del INDEC de
Alimentos y Bebidas (GBA) hacia atrás, más un ruido pequeño (±1%) para que
la comparación tu-índice-vs-INDEC no sea trivialmente idéntica.

También descarga y persiste la serie oficial del INDEC en la tabla
serie_comparativa_indec, para que el endpoint /comparativo de la API pueda
consultarla localmente sin depender de la red.

Idempotente: borra los registros sintéticos previos antes de re-generar.
Los registros sintéticos se marcan con cadena="SINTETICO_DEV" para poder
identificarlos y eliminarlos limpiamente cuando lleguen datos reales.

Uso:
    python sembrar_desarrollo.py
    python sembrar_desarrollo.py --limpiar   # solo borra, no re-genera
"""
from __future__ import annotations

import logging
import random
import sys
from datetime import date

import pandas as pd

import comparativo
from models import RegistroPrecio, SerieComparativaINDEC, SessionLocal, crear_tablas

logger = logging.getLogger("sembrar_dev")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MARCA_SINTETICO = "SINTETICO_DEV"
SERIE_INDEC_ALIMENTOS = "148.3_INDEC_GBA_01_0_24"

# Semilla fija para que el ruido sea reproducible entre corridas.
random.seed(42)


def descargar_y_persistir_indec(db) -> pd.DataFrame:
    """Baja la serie INDEC y la vuelca a serie_comparativa_indec.
    Devuelve el DataFrame con la serie completa para uso posterior."""
    logger.info("Descargando serie oficial INDEC (Alimentos y Bebidas GBA)")
    df = comparativo.obtener_historico_indec()
    if df.empty:
        logger.error("No se pudo bajar la serie del INDEC — abortando")
        return df

    # `comparativo` devuelve fecha como Period; la convertimos a date (primer
    # día del mes) para persistir.
    df = df.copy()
    df["fecha"] = df["fecha"].dt.to_timestamp().dt.date

    # Upsert manual: por cada fila, chequear si existe (fecha, serie_id) y
    # actualizar/insertar. Es idempotente.
    insertados = 0
    actualizados = 0
    for _, fila in df.iterrows():
        existente = db.query(SerieComparativaINDEC).filter_by(
            fecha=fila["fecha"], serie_id=SERIE_INDEC_ALIMENTOS
        ).first()
        if existente:
            if float(existente.valor) != float(fila["indice_oficial_alimentos"]):
                existente.valor = fila["indice_oficial_alimentos"]
                actualizados += 1
        else:
            db.add(SerieComparativaINDEC(
                fecha=fila["fecha"],
                serie_id=SERIE_INDEC_ALIMENTOS,
                valor=fila["indice_oficial_alimentos"],
            ))
            insertados += 1

    db.commit()
    logger.info(f"Serie INDEC: {insertados} filas nuevas, {actualizados} actualizadas "
                f"(último dato: {df['fecha'].max()})")
    return df


def calcular_variaciones_indec(df_indec: pd.DataFrame) -> dict[str, float]:
    """Calcula variación mensual (%) del INDEC. Devuelve {'YYYY-MM': var_pct}.
    var_pct[abril] = cuánto varió abril vs marzo, etc."""
    df = df_indec.sort_values("fecha").copy()
    df["periodo"] = pd.to_datetime(df["fecha"]).dt.strftime("%Y-%m")
    df["var_pct"] = df["indice_oficial_alimentos"].pct_change() * 100
    return dict(zip(df["periodo"], df["var_pct"]))


def borrar_sinteticos(db) -> int:
    """Borra todos los RegistroPrecio marcados como sintéticos."""
    n = db.query(RegistroPrecio).filter(RegistroPrecio.cadena == MARCA_SINTETICO).delete()
    db.commit()
    if n:
        logger.info(f"Borrados {n} registros sintéticos previos")
    return n


def sembrar_precios_sinteticos(db, variaciones_indec: dict[str, float]) -> int:
    """Genera precios sintéticos para abril y mayo 2026, derivados de
    los precios reales de junio.

    Fórmula: precio_mes(ean) = precio_mes_siguiente(ean) / (1 + var_mes_siguiente/100)
    Con ruido multiplicativo uniforme en [0.99, 1.01] para que la
    comparación con INDEC no sea trivial.
    """
    precios_junio = db.query(RegistroPrecio.ean, RegistroPrecio.precio_lista).filter(
        RegistroPrecio.fecha >= date(2026, 6, 1),
        RegistroPrecio.fecha < date(2026, 7, 1),
        RegistroPrecio.cadena != MARCA_SINTETICO,  # solo reales
    ).all()

    if not precios_junio:
        logger.error("No hay precios reales en junio 2026 — nada de qué partir")
        return 0

    # Promedio geométrico por EAN para tener UN precio de junio por producto.
    df_junio = pd.DataFrame(precios_junio, columns=["ean", "precio"])
    df_junio["precio"] = df_junio["precio"].astype(float)
    precio_por_ean_junio = df_junio.groupby("ean")["precio"].mean().to_dict()

    var_mayo_junio = variaciones_indec.get("2026-06")
    var_abr_may = variaciones_indec.get("2026-05")

    if var_mayo_junio is None or var_abr_may is None:
        logger.error(
            f"No hay variaciones INDEC para mayo→junio ({var_mayo_junio}) "
            f"o abril→mayo ({var_abr_may}) — el INDEC quizá aún no publicó junio. "
            "Voy a usar un supuesto de 3.0% mensual como fallback dev."
        )
        var_mayo_junio = var_mayo_junio if var_mayo_junio is not None else 3.0
        var_abr_may = var_abr_may if var_abr_may is not None else 3.0

    logger.info(f"Variaciones INDEC usadas: abr→may={var_abr_may:.2f}%, "
                f"may→jun={var_mayo_junio:.2f}%")

    # Fechas representativas del mes (15) — con un solo día por mes alcanza,
    # es lo mismo que junio real (que solo tiene 26/06).
    fecha_mayo = date(2026, 5, 15)
    fecha_abril = date(2026, 4, 15)

    insertados = 0
    for ean, precio_jun in precio_por_ean_junio.items():
        # precio_mayo = precio_junio / (1 + var_may_jun/100), con ruido ±1%
        ruido_mayo = random.uniform(0.99, 1.01)
        precio_mayo = precio_jun / (1 + var_mayo_junio / 100) * ruido_mayo

        # precio_abril = precio_mayo / (1 + var_abr_may/100), con ruido ±1%
        ruido_abril = random.uniform(0.99, 1.01)
        precio_abril = precio_mayo / (1 + var_abr_may / 100) * ruido_abril

        db.add(RegistroPrecio(
            ean=ean, precio_lista=round(precio_mayo, 2),
            fecha=fecha_mayo, cadena=MARCA_SINTETICO,
        ))
        db.add(RegistroPrecio(
            ean=ean, precio_lista=round(precio_abril, 2),
            fecha=fecha_abril, cadena=MARCA_SINTETICO,
        ))
        insertados += 2

    db.commit()
    logger.info(f"Sembrados {insertados} registros sintéticos "
                f"({len(precio_por_ean_junio)} EANs × 2 meses)")
    return insertados


def main(solo_limpiar: bool = False):
    crear_tablas()
    db = SessionLocal()
    try:
        n_borrados = borrar_sinteticos(db)
        if solo_limpiar:
            logger.info(f"Modo --limpiar: se borraron {n_borrados} registros. Listo.")
            return

        df_indec = descargar_y_persistir_indec(db)
        if df_indec.empty:
            logger.warning(
                "Sin serie INDEC (probable 403 del WAF o red caída). "
                "Uso variaciones DE FALLBACK basadas en el promedio de inflación "
                "mensual de Alimentos y Bebidas del último año (~3.0% mensual). "
                "Cuando la API vuelva, corré: python sembrar_desarrollo.py --limpiar "
                "y después de nuevo sin --limpiar para regenerar con datos reales."
            )
            variaciones = {"2026-05": 3.0, "2026-06": 3.0}
        else:
            variaciones = calcular_variaciones_indec(df_indec)

        sembrar_precios_sinteticos(db, variaciones)

        logger.info("Listo. Ahora podés correr:")
        logger.info("  python calcular_indice_mensual.py 2026-04")
        logger.info("  python calcular_indice_mensual.py 2026-05")
        logger.info("  python calcular_indice_mensual.py 2026-06")
    finally:
        db.close()


if __name__ == "__main__":
    solo_limpiar = "--limpiar" in sys.argv
    main(solo_limpiar=solo_limpiar)