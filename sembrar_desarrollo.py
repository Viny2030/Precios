"""
sembrar_desarrollo.py — SOLO PARA DESARROLLO. NO USAR EN PRODUCCIÓN.

REESCRITO 2026-07-05. Enfoque anterior vs. actual:

  ANTES: generaba abril y mayo sintéticos derivándolos hacia atrás a partir
  de precios REALES de junio ya cargados en la base (vía ingesta del SEPA).
  Eso dejó de tener sentido: el SEPA solo expone una ventana rodante de
  ~7 días, así que a esta altura (julio) ya no hay forma de scrapear "junio"
  — esa ventana se cerró. Sin ingesta corriendo desde junio, no hay ancla
  real de la que partir.

  AHORA: abril, mayo Y junio 2026 son enteramente sintéticos, generados a
  partir de una canasta representativa de productos (con precios base
  ilustrativos, NO relevados) y las variaciones mensuales REALES ya
  publicadas por el INDEC para Alimentos y Bebidas GBA (serie
  config.SERIE_IPC_GBA_ALIMENTOS). Julio en adelante se nutre exclusivamente
  de datos reales scrapeados del SEPA vía main.py/barrer_semana.py — esos
  registros quedan con su cadena real (no SINTETICO_DEV) y conviven en las
  mismas tablas sin pisarse.

  Junio es el período base (config.PERIODO_BASE = 100), así que julio real
  se compara contra un junio sintético — es una limitación conocida y
  documentada (ver aviso en api.py), no algo oculto.

Por qué no hay variación real para el paso mayo→junio: el INDEC publica
cada mes el día 14 del siguiente (ver README/api.py), así que a la fecha en
que se corre este script (principios de julio) todavía no existe el dato
oficial de junio. Ese tramo se estima como el promedio de los últimos meses
conocidos — se loguea explícitamente como estimación, no como dato oficial,
y CONVIENE re-correr este script una vez que el INDEC publique junio
(~14/07) para reemplazar la estimación por el valor real.

Idempotente: borra los registros/eans sintéticos previos (fecha < julio
2026, cadena SINTETICO_DEV) antes de regenerar. No toca nada con fecha
>= julio (ahí vive exclusivamente el dato real de la ingesta).

Uso:
    python sembrar_desarrollo.py
    python sembrar_desarrollo.py --limpiar   # solo borra, no re-genera
"""
from __future__ import annotations

import logging
import random
import sys
from datetime import date
from pathlib import Path

import pandas as pd

import comparativo
import config
from models import MaestroProducto, RegistroPrecio, SerieComparativaINDEC, SessionLocal, crear_tablas

logger = logging.getLogger("sembrar_dev")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MARCA_SINTETICO = "SINTETICO_DEV"
SERIE_INDEC_ALIMENTOS = config.SERIE_IPC_GBA_ALIMENTOS
DICCIONARIO_COICOP_PATH = Path(config.DATA_DIR) / "diccionario_coicop.csv"

random.seed(42)

CANASTA_SINTETICA = [
    ("9990000000001", "Pan lactal 460g", "Marca genérica", "01.1.1", 2100),
    ("9990000000002", "Fideos guisero 500g", "Marca genérica", "01.1.1", 1350),
    ("9990000000003", "Carne picada común 1kg", "Marca genérica", "01.1.2", 8100),
    ("9990000000004", "Pollo entero 1kg", "Marca genérica", "01.1.2", 4900),
    ("9990000000005", "Leche entera sachet 1L", "Marca genérica", "01.1.4", 1500),
    ("9990000000006", "Huevos docena", "Marca genérica", "01.1.4", 3600),
    ("9990000000007", "Aceite girasol 900ml", "Marca genérica", "01.1.5", 2450),
    ("9990000000008", "Manteca 200g", "Marca genérica", "01.1.5", 1800),
    ("9990000000009", "Banana 1kg", "Marca genérica", "01.1.6", 2000),
    ("9990000000010", "Manzana 1kg", "Marca genérica", "01.1.6", 2250),
    ("9990000000011", "Papa 1kg", "Marca genérica", "01.1.7", 1250),
    ("9990000000012", "Tomate redondo 1kg", "Marca genérica", "01.1.7", 2450),
    ("9990000000013", "Azúcar 1kg", "Marca genérica", "01.1.8", 1400),
    ("9990000000014", "Dulce de leche 400g", "Marca genérica", "01.1.8", 2150),
    ("9990000000015", "Yerba mate 1kg", "Marca genérica", "01.2.1", 3950),
    ("9990000000016", "Café molido 250g", "Marca genérica", "01.2.1", 3400),
    ("9990000000017", "Gaseosa cola 2.25L", "Marca genérica", "01.2.2", 2250),
    ("9990000000018", "Agua mineral 2L", "Marca genérica", "01.2.2", 1100),
    ("9990000000019", "Cerveza rubia 1L", "Marca genérica", "02.1", 1950),
    ("9990000000020", "Vino tinto 750ml", "Marca genérica", "02.1", 3300),
    ("9990000000021", "Cigarrillos paquete 20u", "Marca genérica", "02.2.1", 6100),
]

FECHA_ABRIL = date(2026, 4, 15)
FECHA_MAYO = date(2026, 5, 15)
FECHA_JUNIO = date(2026, 6, 15)


def descargar_y_persistir_indec(db) -> pd.DataFrame:
    logger.info(f"Descargando serie oficial INDEC (Alimentos y Bebidas GBA, {SERIE_INDEC_ALIMENTOS})")
    df = comparativo.obtener_historico_indec()
    if df.empty:
        logger.error("No se pudo bajar la serie del INDEC — abortando")
        return df

    df = df.copy()
    df["fecha"] = df["fecha"].dt.to_timestamp().dt.date

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
                f"(último dato publicado: {df['fecha'].max()})")
    return df


def descargar_y_persistir_indec_por_rubro(db) -> None:
    """Baja el nivel de índice INDEC por rubro (ver
    comparativo.obtener_indices_indec_por_rubro) y lo vuelca a
    serie_comparativa_indec con serie_id = 'APERTURA_<coicop_subclase>'.
    Es lo que permite comparar CADA RUBRO (no solo el total) contra el
    INDEC en /comparativo/{periodo}/rubros."""
    logger.info("Descargando índices INDEC por rubro (aperturas GBA)...")
    df = comparativo.obtener_indices_indec_por_rubro()
    if df.empty:
        logger.warning("No se pudo bajar el desglose por rubro del INDEC — "
                        "/comparativo/{periodo}/rubros va a quedar sin datos INDEC por ahora.")
        return

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


def calcular_variaciones_indec(df_indec: pd.DataFrame) -> dict[str, float]:
    df = df_indec.sort_values("fecha").copy()
    df["periodo"] = pd.to_datetime(df["fecha"]).dt.strftime("%Y-%m")
    df["var_pct"] = df["indice_oficial_alimentos"].pct_change() * 100
    return dict(zip(df["periodo"], df["var_pct"]))


def borrar_sinteticos(db) -> int:
    n = db.query(RegistroPrecio).filter(
        RegistroPrecio.cadena == MARCA_SINTETICO,
        RegistroPrecio.fecha < date(2026, 7, 1),
    ).delete()
    db.commit()
    if n:
        logger.info(f"Borrados {n} registros sintéticos previos (abr-jun)")
    return n


def sembrar_maestro_productos(db) -> None:
    for ean, descripcion, marca, coicop, _ in CANASTA_SINTETICA:
        existente = db.query(MaestroProducto).filter_by(ean=int(ean)).first()
        if existente:
            existente.descripcion = descripcion
            existente.marca = marca
            existente.coicop_subclase = coicop
        else:
            nuevo = MaestroProducto(
                ean=int(ean), descripcion=descripcion, marca=marca,
                coicop_subclase=coicop, unidad_medida="unidad", contenido_neto=1,
            )
            db.add(nuevo)
    db.commit()
    logger.info(f"{len(CANASTA_SINTETICA)} productos sintéticos en maestro_productos (upsert)")


def actualizar_diccionario_coicop() -> None:
    DICCIONARIO_COICOP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DICCIONARIO_COICOP_PATH.exists():
        df = pd.read_csv(DICCIONARIO_COICOP_PATH, dtype=str)
    else:
        df = pd.DataFrame(columns=["ean", "coicop_subclase"])

    eans_sinteticos = set(x[0] for x in CANASTA_SINTETICA)
    df = df[~df["ean"].astype(str).isin(eans_sinteticos)]
    filas_nuevas = [{"ean": x[0], "coicop_subclase": x[3]} for x in CANASTA_SINTETICA]
    nuevas = pd.DataFrame(filas_nuevas)
    df = pd.concat([df, nuevas], ignore_index=True)
    df.to_csv(DICCIONARIO_COICOP_PATH, index=False)
    logger.info(f"{DICCIONARIO_COICOP_PATH.name}: {len(eans_sinteticos)} EANs sintéticos "
                f"agregados/actualizados ({len(df)} filas totales)")


def sembrar_precios_sinteticos(db, var_abril: float, var_mayo: float, var_junio: float) -> int:
    insertados = 0
    for ean, _, _, _, precio_marzo in CANASTA_SINTETICA:
        ean_int = int(ean)

        precio_abril = precio_marzo * (1 + var_abril / 100) * random.uniform(0.99, 1.01)
        precio_mayo = precio_abril * (1 + var_mayo / 100) * random.uniform(0.99, 1.01)
        precio_junio = precio_mayo * (1 + var_junio / 100) * random.uniform(0.99, 1.01)

        pares = [(FECHA_ABRIL, precio_abril), (FECHA_MAYO, precio_mayo), (FECHA_JUNIO, precio_junio)]
        for fecha, precio in pares:
            registro = RegistroPrecio(
                ean=ean_int, precio_lista=round(precio, 2), fecha=fecha,
                cadena=MARCA_SINTETICO, sucursal_caba_id="SINT-DEV-01",
            )
            db.add(registro)
            insertados += 1

    db.commit()
    logger.info(f"Sembrados {insertados} registros sintéticos "
                f"({len(CANASTA_SINTETICA)} productos x 3 meses)")
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
        descargar_y_persistir_indec_por_rubro(db)
        if df_indec.empty:
            logger.warning(
                "Sin serie INDEC (red caida o catalogo cambio de nuevo). "
                "Uso variaciones DE FALLBACK (~1% mensual) - reemplazalas corriendo "
                "este script de nuevo cuando la API vuelva."
            )
            var_abril, var_mayo, var_junio = 1.0, 1.0, 1.0
        else:
            variaciones = calcular_variaciones_indec(df_indec)
            var_abril = variaciones.get("2026-04")
            var_mayo = variaciones.get("2026-05")
            var_junio = variaciones.get("2026-06")

            if var_abril is None or var_mayo is None:
                logger.error(
                    f"Faltan variaciones reales para abril ({var_abril}) o mayo ({var_mayo}). "
                    "Uso el fallback de 1.0% para lo que falte."
                )
            var_abril = var_abril if var_abril is not None else 1.0
            var_mayo = var_mayo if var_mayo is not None else 1.0

            if var_junio is None:
                ultimos = [v for v in variaciones.values() if pd.notna(v)][-3:]
                var_junio = sum(ultimos) / len(ultimos) if ultimos else var_mayo
                logger.warning(
                    f"INDEC aun no publico junio 2026 (publica ~14/07). "
                    f"Uso una ESTIMACION de {var_junio:.2f}% (promedio de los ultimos "
                    f"{len(ultimos)} meses conocidos) - volve a correr este script "
                    f"despues del 14/07 para reemplazarla por el dato real."
                )

        logger.info(f"Variaciones usadas -> abril: {var_abril:.2f}% (real), "
                    f"mayo: {var_mayo:.2f}% (real), junio: {var_junio:.2f}% (estimado)")

        sembrar_maestro_productos(db)
        actualizar_diccionario_coicop()
        sembrar_precios_sinteticos(db, var_abril, var_mayo, var_junio)

        logger.info("Listo. Ahora podes correr:")
        logger.info("  python calcular_indice_mensual.py 2026-04")
        logger.info("  python calcular_indice_mensual.py 2026-05")
        logger.info("  python calcular_indice_mensual.py 2026-06")
        logger.info("Y desde julio, la ingesta real (main.py / barrer_semana.py) "
                     "alimenta los periodos siguientes sin tocar lo sintetico.")
    finally:
        db.close()


if __name__ == "__main__":
    solo_limpiar = "--limpiar" in sys.argv
    main(solo_limpiar=solo_limpiar)
