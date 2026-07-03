"""
calcular_indice_mensual.py — Cierra el mes: corre las 3 fases de econometria.py
sobre los datos ya persistidos y guarda el resultado en indice_calculado.

Uso:
    python calcular_indice_mensual.py 2026-02   # calcula febrero 2026
                                                  # (compara contra config.PERIODO_BASE)
"""
import logging
import sys
from datetime import date

import pandas as pd

import config
import econometria
import transform
from models import IndiceCalculado, RegistroPrecio, SessionLocal

logger = logging.getLogger("calcular_indice")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _precios_del_periodo(db, periodo: str) -> pd.DataFrame:
    """periodo: 'YYYY-MM'. Devuelve DataFrame ean, fecha, precio para ese mes."""
    anio, mes = map(int, periodo.split("-"))
    query = db.query(RegistroPrecio.ean, RegistroPrecio.fecha, RegistroPrecio.precio_lista).filter(
        RegistroPrecio.fecha >= date(anio, mes, 1),
        RegistroPrecio.fecha < date(anio + (mes == 12), (mes % 12) + 1, 1),
    )
    df = pd.read_sql(query.statement, db.bind)
    df = df.rename(columns={"precio_lista": "precio_normalizado"})
    return df


def calcular_y_guardar(periodo: str, periodo_base: str | None = None):
    periodo_base = periodo_base or config.PERIODO_BASE
    db = SessionLocal()
    try:
        logger.info(f"Calculando índice de {periodo} vs. base {periodo_base}")

        df_periodo = _precios_del_periodo(db, periodo)
        df_base = _precios_del_periodo(db, periodo_base)

        if df_periodo.empty:
            logger.error(f"Sin registros de precios para {periodo} — nada para calcular")
            return
        if df_base.empty:
            logger.error(f"Sin registros de precios para el período base {periodo_base}")
            return

        # Fase I
        precios_prom_periodo = econometria.precio_promedio_mensual(df_periodo, periodo)
        precios_prom_base = econometria.precio_promedio_mensual(df_base, periodo_base)

        # Fase II
        coicop_por_ean = transform.cargar_diccionario_coicop()
        indices_subclase = econometria.indice_jevons_por_subclase(
            precios_prom_periodo, precios_prom_base, coicop_por_ean
        )
        if indices_subclase.empty:
            logger.error("Sin índices elementales calculados — revisar diccionario COICOP")
            return

        # Fase III
        ponderaciones = pd.read_sql("SELECT coicop_subclase, ponderacion_caba FROM ponderaciones_coicop", db.bind)
        if ponderaciones.empty:
            logger.error(
                "Sin ponderaciones cargadas en ponderaciones_coicop — el índice general "
                "no se puede calcular sin el vector de pesos de la ENGHo. Ver README."
            )
            return

        resultado = econometria.agregacion_laspeyres(indices_subclase, ponderaciones)
        if resultado is None:
            logger.error("agregacion_laspeyres() no devolvió resultado — ver warnings arriba")
            return

        # Persistir índice general
        _upsert_indice(db, periodo, "general", None, resultado["indice_general"],
                        n_variedades=sum(d["n_variedades"] for d in resultado["detalle"]))

        # Persistir índices por subclase
        for fila in resultado["detalle"]:
            _upsert_indice(db, periodo, "coicop_subclase", fila["coicop_subclase"],
                            fila["indice_jevons"], n_variedades=fila["n_variedades"])

        db.commit()
        logger.info(
            f"Listo — índice general {periodo}: {resultado['indice_general']:.2f} "
            f"(cobertura de ponderación: {resultado['cobertura_ponderacion']:.1%}, "
            f"{resultado['n_subclases']} subclases)"
        )
    finally:
        db.close()


def _upsert_indice(db, periodo, nivel, coicop_subclase, valor, n_variedades):
    existente = db.query(IndiceCalculado).filter_by(
        periodo=periodo, nivel=nivel, coicop_subclase=coicop_subclase
    ).first()

    anterior = (
        db.query(IndiceCalculado)
        .filter(IndiceCalculado.nivel == nivel, IndiceCalculado.coicop_subclase == coicop_subclase,
                IndiceCalculado.periodo < periodo)
        .order_by(IndiceCalculado.periodo.desc())
        .first()
    )
    variacion = None
    if anterior and float(anterior.indice_valor) > 0:
        variacion = (valor / float(anterior.indice_valor) - 1) * 100

    if existente:
        existente.indice_valor = valor
        existente.variacion_pct = variacion
        existente.cantidad_variedades = n_variedades
    else:
        db.add(IndiceCalculado(
            periodo=periodo, nivel=nivel, coicop_subclase=coicop_subclase,
            indice_valor=valor, variacion_pct=variacion, cantidad_variedades=n_variedades,
        ))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python calcular_indice_mensual.py YYYY-MM")
        sys.exit(1)
    calcular_y_guardar(sys.argv[1])
