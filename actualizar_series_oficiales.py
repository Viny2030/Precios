"""
actualizar_series_oficiales.py — Refresca SOLO las series oficiales de
comparación: INDEC (Alimentos y Bebidas GBA, Nivel General Nacional,
aperturas por rubro) y GCBA (Alimentos y Bebidas no alcohólicas CABA).

No toca precios (ni reales ni SINTETICO_DEV) — a diferencia de
sembrar_desarrollo.py, que además reseeda la canasta sintética de
abril/mayo/junio. Este script es el que conviene correr periódicamente
de acá en adelante (julio 2026+), una vez que ya no hace falta regenerar
sintéticos: solo mantiene al día los benchmarks contra los que se compara
el índice propio.

Cuándo correrlo:
- El INDEC publica el IPC del mes cerrado el día 14 del mes siguiente.
- El GCBA (Dirección Gral. de Estadística y Censos) publica en fechas
  similares, no siempre exactas — correr este script no rompe nada si
  todavía no hay dato nuevo (persistir_serie() es idempotente: si no
  hay filas nuevas, no cambia nada).
Por eso el workflow programado (.github/workflows/actualizar_series_oficiales.yml)
lo corre el día 16 de cada mes, con margen sobre la fecha de publicación.

Uso:
    python actualizar_series_oficiales.py
"""
from __future__ import annotations

import logging

import comparativo
from models import SessionLocal, crear_tablas

logger = logging.getLogger("actualizar_series")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    crear_tablas()
    db = SessionLocal()
    try:
        logger.info("=== Actualización de series oficiales (INDEC + GCBA) ===")
        resultado = comparativo.actualizar_todas_las_series(db)
        vacias = [nombre for nombre, df in resultado.items() if df.empty]
        if vacias:
            logger.warning(
                f"Series que no se pudieron actualizar en esta corrida: {', '.join(vacias)} "
                "(seguramente sin dato nuevo publicado, o falla de red — no es necesariamente un error)."
            )
        logger.info("Listo.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
