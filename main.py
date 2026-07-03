"""
main.py — Orquestador principal del pipeline

Flujo (pensado para correr una vez al día, ej. via cron a las 4:00 AM):
  1. Ingesta: descarga (o lee modo manual) el ZIP del SEPA del día y lo
     filtra a CABA.
  2. Transformación: normaliza precios por unidad y clasifica por COICOP.
  3. Persistencia: guarda los registros crudos filtrados en la base.

El cálculo del índice mensual (Fases I/II/III de econometria.py) se corre
aparte, al cierre del mes — ver econometria.py y el ejemplo de uso en su
docstring. Separarlo así evita recalcular el índice completo en cada
corrida diaria.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

import config
import ingesta
import transform
from models import SessionLocal, MaestroProducto, RegistroPrecio, crear_tablas

logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _dia_semana_hoy() -> str:
    return config.DIAS_SEPA[date.today().weekday() % 7]


def persistir_registros(df: pd.DataFrame) -> tuple[int, int]:
    """
    Vuelca el DataFrame procesado a la base: primero actualiza/crea las
    filas de maestro_productos, después inserta los registros de precio.
    Devuelve (productos_nuevos, precios_insertados).
    """
    if df.empty:
        return 0, 0

    db = SessionLocal()
    productos_nuevos = 0
    precios_insertados = 0
    try:
        eans_conocidos = {p.ean for p in db.query(MaestroProducto.ean).all()}

        for ean, grupo in df.groupby("ean"):
            fila = grupo.iloc[0]
            ean_int = int(ean)
            if ean_int not in eans_conocidos:
                db.add(MaestroProducto(
                    ean=ean_int,
                    descripcion=fila.get("nombre"),
                    marca=fila.get("marca"),
                    coicop_subclase=fila.get("coicop_subclase") if pd.notna(fila.get("coicop_subclase")) else None,
                    unidad_medida=fila.get("unidad_medida") if pd.notna(fila.get("unidad_medida")) else None,
                    contenido_neto=float(fila["contenido_neto"]) if pd.notna(fila.get("contenido_neto")) else None,
                ))
                eans_conocidos.add(ean_int)
                productos_nuevos += 1

        db.flush()

        for _, fila in df.iterrows():
            if pd.isna(fila.get("precio")) or pd.isna(fila.get("fecha")):
                continue
            db.add(RegistroPrecio(
                ean=int(fila["ean"]),
                precio_lista=float(fila["precio"]),
                fecha=pd.to_datetime(fila["fecha"]).date(),
                sucursal_caba_id=str(fila.get("sucursal")) if pd.notna(fila.get("sucursal")) else None,
                cadena=str(fila.get("cadena")) if pd.notna(fila.get("cadena")) else None,
            ))
            precios_insertados += 1

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error al persistir: {e}")
        raise
    finally:
        db.close()

    return productos_nuevos, precios_insertados


def ejecutar_pipeline_diario(dia: str | None = None):
    dia = dia or _dia_semana_hoy()
    logger.info(f"=== Pipeline diario — {dia} — {date.today().isoformat()} ===")

    crear_tablas()

    logger.info("1/3 — Ingesta")
    df_crudo = ingesta.procesar_dia_sepa(dia)
    if df_crudo.empty:
        logger.warning("Sin datos de CABA para hoy — nada para procesar. Ver ingesta.py "
                        "si esto se repite varios días seguidos (probable bloqueo del WAF).")
        return

    logger.info("2/3 — Transformación")
    df_norm = transform.normalizar_precios(df_crudo)
    df_clasificado = transform.clasificar_coicop(df_norm)
    df_alimentos = transform.filtrar_division_alimentos_bebidas(df_clasificado)

    logger.info("3/3 — Persistencia")
    nuevos, insertados = persistir_registros(df_alimentos)
    logger.info(f"Listo — {nuevos} productos nuevos, {insertados} precios insertados "
                f"(de {len(df_alimentos)} filas clasificadas en Alimentos/Bebidas)")


if __name__ == "__main__":
    ejecutar_pipeline_diario()