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
from datetime import date, datetime
from zoneinfo import ZoneInfo
import pandas as pd
import alertas
import config
import ingesta
import transform
from models import SessionLocal, MaestroProducto, RegistroPrecio, crear_tablas

logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _fecha_hoy_ar() -> date:
    # FIX 2026-09-02: antes se usaba date.today() (fecha del servidor, en UTC).
    # Como Argentina está UTC-3, cerca del cambio de día UTC el servidor ya
    # "cree" que es el día siguiente cuando en Argentina todavía no llegó
    # la medianoche -- esto hacía que el cron pidiera el recurso SEPA
    # equivocado justo en el peor momento (cuando ese recurso recién se
    # estaba por generar). Se fija explícitamente la fecha de Argentina,
    # sin importar en qué huso horario corra el servidor ni a qué hora
    # dispare el cron.
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()


def _dia_semana_hoy() -> str:
    return config.DIAS_SEPA[_fecha_hoy_ar().weekday() % 7]


def persistir_registros(df: pd.DataFrame) -> tuple[int, int]:
    """
    Vuelca el DataFrame procesado a la base: primero actualiza/crea las
    filas de maestro_productos, después inserta los registros de precio.
    Devuelve (productos_nuevos, precios_insertados).

    AGREGADO 2026-09-01: reescrito para insertar en bloques (bulk_insert_mappings)
    en vez de un db.add() por fila -- con cientos de miles de filas, el enfoque
    anterior (un objeto ORM por fila, todo pendiente hasta un solo commit final)
    era tan lento y pesado que el proceso se quedaba colgado sin terminar nunca
    la Persistencia.
    """
    if df.empty:
        return 0, 0
    db = SessionLocal()
    productos_nuevos = 0
    precios_insertados = 0
    LOTE = 20_000
    try:
        eans_conocidos = {p.ean for p in db.query(MaestroProducto.ean).all()}

        nuevos_productos = []
        vistos = set()
        for ean, grupo in df.groupby("ean"):
            ean_int = int(ean)
            if ean_int in eans_conocidos or ean_int in vistos:
                continue
            fila = grupo.iloc[0]
            nuevos_productos.append({
                "ean": ean_int,
                "descripcion": fila.get("nombre"),
                "marca": fila.get("marca"),
                "coicop_subclase": fila.get("coicop_subclase") if pd.notna(fila.get("coicop_subclase")) else None,
                "unidad_medida": fila.get("unidad_medida") if pd.notna(fila.get("unidad_medida")) else None,
                "contenido_neto": float(fila["contenido_neto"]) if pd.notna(fila.get("contenido_neto")) else None,
            })
            vistos.add(ean_int)
        if nuevos_productos:
            db.bulk_insert_mappings(MaestroProducto, nuevos_productos)
            productos_nuevos = len(nuevos_productos)
        db.commit()

        validos = df.dropna(subset=["precio", "fecha"])
        buffer = []
        for fila in validos.itertuples(index=False):
            buffer.append({
                "ean": int(fila.ean),
                "precio_lista": float(fila.precio),
                "fecha": pd.to_datetime(fila.fecha).date(),
                "sucursal_caba_id": str(fila.sucursal) if pd.notna(fila.sucursal) else None,
                "cadena": str(fila.cadena) if pd.notna(fila.cadena) else None,
            })
            if len(buffer) >= LOTE:
                db.bulk_insert_mappings(RegistroPrecio, buffer)
                db.commit()
                precios_insertados += len(buffer)
                buffer.clear()
        if buffer:
            db.bulk_insert_mappings(RegistroPrecio, buffer)
            db.commit()
            precios_insertados += len(buffer)
    except Exception as e:
        db.rollback()
        logger.error(f"Error al persistir: {e}")
        raise
    finally:
        db.close()
    return productos_nuevos, precios_insertados


def ejecutar_pipeline_diario(dia: str | None = None):
    dia = dia or _dia_semana_hoy()
    logger.info(f"=== Pipeline diario — {dia} — {_fecha_hoy_ar().isoformat()} ===")
    crear_tablas()
    logger.info("1/3 — Ingesta")
    df_crudo = ingesta.procesar_dia_sepa(dia)
    if df_crudo.empty:
        logger.warning("Sin datos de CABA para hoy — nada para procesar. Ver ingesta.py "
                        "si esto se repite varios días seguidos (probable bloqueo del WAF).")
        alertas.alertar_ingesta_vacia(dia, motivo="procesar_dia_sepa() devolvió 0 filas")
        return
    logger.info("2/3 — Transformación")
    df_norm = transform.normalizar_precios(df_crudo)
    df_clasificado = transform.clasificar_coicop(df_norm)
    df_alimentos = transform.filtrar_division_alimentos_bebidas(df_clasificado)
    logger.info("3/3 — Persistencia")
    nuevos, insertados = persistir_registros(df_alimentos)
    logger.info(f"Listo — {nuevos} productos nuevos, {insertados} precios insertados "
                f"(de {len(df_alimentos)} filas clasificadas en Alimentos/Bebidas)")
    if insertados == 0:
        alertas.alertar_ingesta_vacia(dia, motivo="0 precios insertados (llegaron filas pero ninguna con precio/fecha válidos)")
    else:
        alertas.marcar_ingesta_ok()


if __name__ == "__main__":
    ejecutar_pipeline_diario()