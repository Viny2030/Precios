"""
borrar_sinteticos_definitivo.py — Limpieza TOTAL de los datos sintéticos de
abril-mayo-junio 2026, ahora que julio pasó a ser la base real
(config.PERIODO_BASE = "2026-07", ver ESTADO_PENDIENTES.md punto -1).

`sembrar_desarrollo.py --limpiar` solo borra RegistroPrecio (cadena=
SINTETICO_DEV). Esto no alcanza para "empezar de cero": deja huérfanos en
maestro_productos, deja calculados en indice_calculado los meses
abril/mayo/junio (que ya no tienen sentido — estaban indexados contra una
base sintética que dejó de existir como tal), y deja las 21 filas
sintéticas en data/diccionario_coicop.csv.

Este script borra las 4 cosas:
  1. RegistroPrecio con cadena=SINTETICO_DEV (abril-junio 2026)
  2. MaestroProducto de los 21 EAN inventados (9990000000001..21)
  3. IndiceCalculado de los períodos 2026-04, 2026-05, 2026-06
     (nivel="general" y nivel="coicop_subclase")
  4. Las 21 filas con esos EAN en data/diccionario_coicop.csv

Después de correr esto, el historial del índice arranca limpio en julio
2026 (base real = 100). Para poblarlo:
    python calcular_indice_mensual.py 2026-07

Es idempotente: si ya no queda nada sintético, corre sin romper nada (borra
0 filas en cada paso).

Uso:
    python borrar_sinteticos_definitivo.py
"""
from __future__ import annotations

import logging

import pandas as pd

import config
from models import IndiceCalculado, MaestroProducto, RegistroPrecio, SessionLocal
from sembrar_desarrollo import CANASTA_SINTETICA, DICCIONARIO_COICOP_PATH, MARCA_SINTETICO

logger = logging.getLogger("borrar_sinteticos_definitivo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PERIODOS_SINTETICOS = ["2026-04", "2026-05", "2026-06"]
EANS_SINTETICOS = [int(x[0]) for x in CANASTA_SINTETICA]


def borrar_registro_precio(db) -> int:
    n = db.query(RegistroPrecio).filter(RegistroPrecio.cadena == MARCA_SINTETICO).delete()
    db.commit()
    logger.info(f"RegistroPrecio: {n} filas sintéticas borradas (cadena={MARCA_SINTETICO})")
    return n


def borrar_maestro_productos(db) -> int:
    n = db.query(MaestroProducto).filter(MaestroProducto.ean.in_(EANS_SINTETICOS)).delete(
        synchronize_session=False
    )
    db.commit()
    logger.info(f"MaestroProducto: {n} EAN sintéticos borrados")
    return n


def borrar_indice_calculado(db) -> int:
    n = db.query(IndiceCalculado).filter(IndiceCalculado.periodo.in_(PERIODOS_SINTETICOS)).delete(
        synchronize_session=False
    )
    db.commit()
    logger.info(f"IndiceCalculado: {n} filas de {', '.join(PERIODOS_SINTETICOS)} borradas")
    return n


def limpiar_diccionario_coicop() -> int:
    if not DICCIONARIO_COICOP_PATH.exists():
        logger.info(f"{DICCIONARIO_COICOP_PATH} no existe — nada que limpiar ahí")
        return 0
    df = pd.read_csv(DICCIONARIO_COICOP_PATH, dtype=str)
    eans_sinteticos_str = {str(e) for e in EANS_SINTETICOS}
    antes = len(df)
    df = df[~df["ean"].astype(str).isin(eans_sinteticos_str)]
    borrados = antes - len(df)
    df.to_csv(DICCIONARIO_COICOP_PATH, index=False)
    logger.info(f"{DICCIONARIO_COICOP_PATH.name}: {borrados} filas sintéticas borradas "
                f"({len(df)} filas reales quedan)")
    return borrados


def main():
    db = SessionLocal()
    try:
        logger.info(f"Base de datos: {config.DATABASE_URL}")
        n1 = borrar_registro_precio(db)
        n2 = borrar_maestro_productos(db)
        n3 = borrar_indice_calculado(db)
        n4 = limpiar_diccionario_coicop()
        logger.info(
            f"Listo. Total borrado: {n1} precios, {n2} productos maestro, "
            f"{n3} índices calculados, {n4} filas de diccionario COICOP."
        )
        logger.info("Ahora corré: python calcular_indice_mensual.py 2026-07")
    finally:
        db.close()


if __name__ == "__main__":
    main()
