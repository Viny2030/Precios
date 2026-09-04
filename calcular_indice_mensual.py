"""
calcular_indice_mensual.py — Cierra el mes: corre las 3 fases de econometria.py
sobre los datos ya persistidos y guarda el resultado en indice_calculado.

Uso:
    python calcular_indice_mensual.py 2026-02   # calcula febrero 2026
                                                  # (compara contra config.PERIODO_BASE)
    python calcular_indice_mensual.py            # sin argumento: calcula el
                                                  # mes calendario anterior a
                                                  # hoy (UTC), sin importar
                                                  # qué día del mes se llame.
                                                  # Pensado para un cron que
                                                  # solo puede fijar un start
                                                  # command fijo (ej. Railway
                                                  # Cron) — ver _mes_anterior().
"""
import logging
import sys
from datetime import date, datetime, timedelta, timezone

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


def _mes_anterior(hoy: date | None = None) -> str:
    """Mes calendario anterior a `hoy` (UTC), formato 'YYYY-MM', sin importar
    qué día del mes se llame esta función.

    AGREGADO 2026-09-01: esta cuenta ya se había escrito una vez -- en
    PowerShell, adentro de .github/workflows/calcular_indice_mensual.yml --
    y tuvo un bug real (usaba "ayer", que solo da el mes anterior si corre
    el día 1; el día 2 -- cuando de hecho dispara el cron -- daba el mes en
    curso sin cerrar). Centralizarla acá, en Python, con tests, evita
    reescribir/reintroducir el mismo bug en cada plataforma nueva que
    dispare este script (ej. un cron de Railway, que solo puede fijar un
    start command fijo tipo `python calcular_indice_mensual.py`, sin lugar
    para lógica de fecha propia)."""
    hoy = hoy or datetime.now(timezone.utc).date()
    primer_dia_mes_actual = hoy.replace(day=1)
    ultimo_dia_mes_anterior = primer_dia_mes_actual - timedelta(days=1)
    return ultimo_dia_mes_anterior.strftime("%Y-%m")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        periodo = sys.argv[1]
        logger.info(f"Periodo forzado por argumento: {periodo}")
    else:
        periodo = _mes_anterior()
        logger.info(f"Sin argumento — calculando el mes calendario anterior a hoy: {periodo}")
    calcular_y_guardar(periodo)
