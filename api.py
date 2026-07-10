"""
api.py — API REST (FastAPI) del Índice de Precios de Alimentos y Bebidas CABA.

Expone los índices calculados por el pipeline (calcular_indice_mensual.py) y
el comparativo contra la serie oficial del INDEC.

Corrida en desarrollo:
    uvicorn api:app --reload

Documentación interactiva (Swagger UI):
    http://127.0.0.1:8000/docs

Convenciones de la respuesta:
- Todas las fechas y períodos siguen ISO ("YYYY-MM" para períodos mensuales,
  "YYYY-MM-DD" para fechas puntuales).
- El campo `origen_datos` en cada índice aclara si el período se calculó con
  precios reales o precios SINTÉTICOS_DEV (útil hasta que julio 2026 cierre).
- El comparativo con INDEC devuelve `indec_disponible: false` cuando el mes
  aún no fue publicado (INDEC publica el día 14 del mes siguiente).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func

import config
from models import (
    IndiceCalculado,
    PonderacionCoicop,
    RegistroPrecio,
    SerieComparativaINDEC,
    SessionLocal,
)

MARCA_SINTETICO = "SINTETICO_DEV"
# Comparativo GENERAL (/comparativo/{periodo}): contra el Nivel General
# Nacional del INDEC — el número de inflación mensual que sale en todos
# lados, no el desglose regional de Alimentos y Bebidas (cambiado
# 2026-07-05 a pedido: comparar contra "la del INDEC" que todo el mundo
# cita, no contra GBA). OJO: es un benchmark de precios en general (todos
# los rubros), no de alimentos — se explicita en la nota de la respuesta.
SERIE_INDEC_NACIONAL = config.SERIE_IPC_NACIONAL_NIVEL_GENERAL

# Comparativo POR RUBRO (/comparativo/{periodo}/rubros): sigue contra GBA,
# porque el INDEC no publica un desglose por rubro a nivel Nacional (el
# archivo de aperturas solo trae regiones: GBA, Pampeana, NOA, NEA, Cuyo,
# Patagonia — ver comparativo.obtener_indices_indec_por_rubro).

app = FastAPI(
    title="Índice de Alimentos y Bebidas — CABA",
    description=(
        "Índice propio calculado a partir de precios oficiales publicados bajo "
        "Ley 27.275 (SEPA / Precios Claros), con comparativo contra el IPC "
        "oficial del INDEC (Alimentos y Bebidas, GBA). "
        f"Base = {config.PERIODO_BASE} = 100."
    ),
    version="0.1.0",
)

# CORS abierto para desarrollo; ajustar en producción a dominios específicos.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Dashboard estático (rubros.html) ────────────────────────────────────────
# Página simple sin build (HTML + JS vanilla) que consume esta misma API y
# muestra el índice rubro por rubro. Se sirve directo desde acá para poder
# abrirla tipeando la URL del deploy + /dashboard, sin manejar un archivo
# aparte ni CORS entre dominios distintos.
_DASHBOARD_PATH = Path(__file__).parent / "rubros.html"


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    if not _DASHBOARD_PATH.exists():
        raise HTTPException(404, "rubros.html no está presente junto a api.py en este deploy")
    # Único "templating": reemplazo de texto plano para no arrastrar Jinja2
    # como dependencia solo por esto — rubros.html es HTML+JS vanilla.
    html = _DASHBOARD_PATH.read_text(encoding="utf-8")
    return html.replace("{{PERIODO_BASE}}", config.PERIODO_BASE)


# ── Modelos de respuesta (Pydantic) ─────────────────────────────────────────

class InfoSistema(BaseModel):
    servicio: str
    version: str
    periodo_base: str
    total_registros_precios: int
    periodos_calculados: int
    ultimo_periodo: Optional[str]
    aviso: str


class IndiceGeneral(BaseModel):
    periodo: str = Field(..., example="2026-05")
    indice_valor: float = Field(..., example=97.50)
    variacion_pct_mensual: Optional[float] = Field(None, example=3.59,
        description="Variación % contra el mes anterior. Null si es el primer período.")
    cantidad_variedades: int = Field(..., example=30)
    origen_datos: str = Field(..., example="sintetico_dev",
        description="'real' o 'sintetico_dev' — este último solo hasta que existan datos reales.")


class IndiceRubro(BaseModel):
    coicop_subclase: str = Field(..., example="01.1.1")
    descripcion: Optional[str] = Field(None, example="Pan y cereales")
    indice_valor: float
    variacion_pct_mensual: Optional[float]
    cantidad_variedades: int
    ponderacion_caba: Optional[float] = Field(None,
        description="Peso relativo en la canasta ENGHo 2017-2018.")


class Rubro(BaseModel):
    coicop_subclase: str
    descripcion: Optional[str]
    division: Optional[str]
    ponderacion_caba: Optional[float]


class Comparativo(BaseModel):
    periodo: str
    indice_propio: float
    variacion_pct_propia: Optional[float] = None
    indec_disponible: bool
    indec_indice: Optional[float] = Field(None,
        description="Nivel del INDEC (Nivel General Nacional) en el período (en su base histórica).")
    indec_variacion_pct: Optional[float] = None
    diferencia_puntos_pct: Optional[float] = Field(None,
        description="Variación propia menos variación INDEC, en puntos porcentuales.")
    gcba_disponible: bool = Field(False,
        description="Si hay dato del GCBA (Alimentos y Bebidas no alcohólicas CABA) para este período.")
    gcba_indice: Optional[float] = Field(None,
        description="Nivel del GCBA en el período (en su base histórica).")
    gcba_variacion_pct: Optional[float] = None
    diferencia_puntos_pct_gcba: Optional[float] = Field(None,
        description="Variación propia menos variación GCBA, en puntos porcentuales.")
    gba_alimentos_disponible: bool = Field(False,
        description="Si hay dato de INDEC IPC-GBA Alimentos y Bebidas para este período.")
    gba_alimentos_indice: Optional[float] = None
    gba_alimentos_variacion_pct: Optional[float] = None
    diferencia_puntos_pct_gba_alimentos: Optional[float] = None
    nota: Optional[str] = None


class EvolucionGeneral(BaseModel):
    """Un renglón por período calculado — para la pestaña 'Evolución general'
    del dashboard: índice propio vs. GCBA (Alimentos y Bebidas CABA) vs.
    INDEC GBA Alimentos (la serie regional específica de alimentos, la misma
    que se usa para calibrar el sintético) vs. INDEC Nivel General Nacional
    (benchmark de inflación general, no solo alimentos)."""
    periodo: str
    origen_datos: str = Field(..., description="'real' o 'sintetico_dev'.")
    indice_propio: float
    variacion_pct_propia: Optional[float] = None
    gcba_disponible: bool
    gcba_indice: Optional[float] = None
    gcba_variacion_pct: Optional[float] = None
    diferencia_pp_gcba: Optional[float] = None
    gba_alimentos_disponible: bool = False
    gba_alimentos_indice: Optional[float] = Field(None,
        description="Nivel de INDEC IPC-GBA Alimentos y Bebidas (serie config.SERIE_IPC_GBA_ALIMENTOS).")
    gba_alimentos_variacion_pct: Optional[float] = None
    diferencia_pp_gba_alimentos: Optional[float] = None
    indec_disponible: bool
    indec_indice: Optional[float] = None
    indec_variacion_pct: Optional[float] = None
    diferencia_pp_indec: Optional[float] = None


class EvolucionRubro(BaseModel):
    """Un renglón por período calculado para UN rubro (subclase COICOP) —
    para la pestaña 'Evolución por rubro'.

    Compara el propio contra INDEC (aperturas región GBA) — el único
    desglose por rubro que el INDEC publica. ADEMÁS incluye, a modo de
    referencia/contexto, los benchmarks GENERALES del período (GCBA
    Alimentos CABA e INDEC Nivel General Nacional) en los campos
    *_general_* — estos NO son específicos del rubro (ni GCBA ni INDEC
    publican desglose por rubro para esas series), son el mismo dato que
    se ve en la pestaña 'Evolución general', repetido acá para poder
    comparar de un vistazo cómo le fue a este rubro puntual contra el
    panorama general."""
    periodo: str
    coicop_subclase: str
    descripcion: Optional[str] = None
    indice_propio: float
    variacion_pct_propia: Optional[float] = None
    indec_disponible: bool
    indec_indice: Optional[float] = None
    indec_variacion_pct: Optional[float] = None
    diferencia_pp: Optional[float] = None
    gcba_general_disponible: bool = False
    gcba_general_variacion_pct: Optional[float] = Field(None,
        description="Variación % del GCBA (Alimentos CABA) en el período — dato GENERAL, no específico de este rubro.")
    diferencia_pp_gcba_general: Optional[float] = None
    indec_general_disponible: bool = False
    indec_general_variacion_pct: Optional[float] = Field(None,
        description="Variación % del INDEC Nivel General Nacional en el período — dato GENERAL, no específico de este rubro.")
    diferencia_pp_indec_general: Optional[float] = None


class ComparativoRubro(BaseModel):
    coicop_subclase: str
    descripcion: Optional[str] = None
    indice_propio: float
    variacion_pct_propia: Optional[float] = None
    indec_disponible: bool
    indec_indice: Optional[float] = None
    indec_variacion_pct: Optional[float] = None
    diferencia_puntos_pct: Optional[float] = None
    nota: Optional[str] = None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _to_float(x) -> Optional[float]:
    if x is None:
        return None
    return float(x) if isinstance(x, Decimal) else float(x)


def _periodo_a_rango_fechas(periodo: str) -> tuple[date, date]:
    """'2026-05' -> (2026-05-01, 2026-06-01)."""
    try:
        anio, mes = map(int, periodo.split("-"))
    except (ValueError, AttributeError):
        raise HTTPException(400, f"Período mal formado: '{periodo}' (usar YYYY-MM)")
    inicio = date(anio, mes, 1)
    fin = date(anio + (mes == 12), (mes % 12) + 1, 1)
    return inicio, fin


def _origen_datos_periodo(db, periodo: str) -> str:
    """Mira los RegistroPrecio del período: si la mayoría son SINTETICO_DEV,
    marca el período como sintético."""
    inicio, fin = _periodo_a_rango_fechas(periodo)
    total = db.query(func.count(RegistroPrecio.id)).filter(
        RegistroPrecio.fecha >= inicio, RegistroPrecio.fecha < fin
    ).scalar() or 0
    sinteticos = db.query(func.count(RegistroPrecio.id)).filter(
        RegistroPrecio.fecha >= inicio, RegistroPrecio.fecha < fin,
        RegistroPrecio.cadena == MARCA_SINTETICO,
    ).scalar() or 0
    if total == 0:
        return "sin_datos"
    return "sintetico_dev" if sinteticos > total / 2 else "real"


def _descripciones_coicop(db) -> dict[str, tuple[str, str, Optional[float]]]:
    """Devuelve {coicop_subclase: (descripcion, division, ponderacion)}."""
    filas = db.query(PonderacionCoicop).all()
    return {
        f.coicop_subclase: (f.descripcion_rubro, f.division, _to_float(f.ponderacion_caba))
        for f in filas
    }


def _valor_variacion_serie(db, serie_id: str, periodo: str) -> tuple[bool, Optional[float], Optional[float]]:
    """Busca una serie oficial (INDEC o GCBA, cacheada en
    serie_comparativa_indec) en un período dado y calcula su variación %
    contra el registro anterior de la MISMA serie. Devuelve
    (disponible, indice_valor, variacion_pct). disponible=False si el
    período todavía no fue publicado (o la serie no está cargada)."""
    inicio, _ = _periodo_a_rango_fechas(periodo)
    actual = (
        db.query(SerieComparativaINDEC)
        .filter(SerieComparativaINDEC.serie_id == serie_id, SerieComparativaINDEC.fecha == inicio)
        .first()
    )
    if not actual:
        return False, None, None

    anterior = (
        db.query(SerieComparativaINDEC)
        .filter(SerieComparativaINDEC.serie_id == serie_id, SerieComparativaINDEC.fecha < inicio)
        .order_by(SerieComparativaINDEC.fecha.desc())
        .first()
    )
    variacion = None
    if anterior and float(anterior.valor) > 0:
        variacion = (float(actual.valor) / float(anterior.valor) - 1) * 100
    return True, _to_float(actual.valor), variacion


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/", response_model=InfoSistema, tags=["info"])
def raiz():
    """Health check + resumen del estado del sistema."""
    db = SessionLocal()
    try:
        total = db.query(func.count(RegistroPrecio.id)).scalar() or 0
        periodos = db.query(func.count(func.distinct(IndiceCalculado.periodo))).filter(
            IndiceCalculado.nivel == "general"
        ).scalar() or 0
        ultimo = db.query(func.max(IndiceCalculado.periodo)).filter(
            IndiceCalculado.nivel == "general"
        ).scalar()
        return InfoSistema(
            servicio="Índice de Alimentos y Bebidas — CABA",
            version="0.1.0",
            periodo_base=config.PERIODO_BASE,
            total_registros_precios=total,
            periodos_calculados=periodos,
            ultimo_periodo=ultimo,
            aviso=(
                "Servicio en desarrollo. Algunos períodos pueden estar calculados "
                "con datos SINTÉTICOS_DEV. Ver campo `origen_datos` de cada índice."
            ),
        )
    finally:
        db.close()


@app.get("/indices", response_model=list[IndiceGeneral], tags=["indices"])
def listar_indices():
    """Lista todos los períodos con índice general calculado, ordenados
    cronológicamente."""
    db = SessionLocal()
    try:
        filas = (
            db.query(IndiceCalculado)
            .filter(IndiceCalculado.nivel == "general")
            .order_by(IndiceCalculado.periodo)
            .all()
        )
        return [
            IndiceGeneral(
                periodo=f.periodo,
                indice_valor=_to_float(f.indice_valor),
                variacion_pct_mensual=_to_float(f.variacion_pct),
                cantidad_variedades=f.cantidad_variedades or 0,
                origen_datos=_origen_datos_periodo(db, f.periodo),
            )
            for f in filas
        ]
    finally:
        db.close()


@app.get("/indices/{periodo}", response_model=IndiceGeneral, tags=["indices"])
def obtener_indice(periodo: str):
    """Devuelve el índice general de un período (formato YYYY-MM)."""
    db = SessionLocal()
    try:
        f = (
            db.query(IndiceCalculado)
            .filter(IndiceCalculado.nivel == "general", IndiceCalculado.periodo == periodo)
            .first()
        )
        if not f:
            raise HTTPException(404, f"No hay índice calculado para {periodo}")
        return IndiceGeneral(
            periodo=f.periodo,
            indice_valor=_to_float(f.indice_valor),
            variacion_pct_mensual=_to_float(f.variacion_pct),
            cantidad_variedades=f.cantidad_variedades or 0,
            origen_datos=_origen_datos_periodo(db, f.periodo),
        )
    finally:
        db.close()


@app.get("/indices/{periodo}/rubros", response_model=list[IndiceRubro], tags=["indices"])
def apertura_por_rubros(periodo: str):
    """Apertura del período por subclases COICOP (rubro por rubro)."""
    db = SessionLocal()
    try:
        filas = (
            db.query(IndiceCalculado)
            .filter(IndiceCalculado.nivel == "coicop_subclase",
                    IndiceCalculado.periodo == periodo)
            .order_by(IndiceCalculado.coicop_subclase)
            .all()
        )
        if not filas:
            raise HTTPException(404, f"No hay apertura por rubros para {periodo}")

        desc = _descripciones_coicop(db)
        return [
            IndiceRubro(
                coicop_subclase=f.coicop_subclase,
                descripcion=desc.get(f.coicop_subclase, (None, None, None))[0],
                indice_valor=_to_float(f.indice_valor),
                variacion_pct_mensual=_to_float(f.variacion_pct),
                cantidad_variedades=f.cantidad_variedades or 0,
                ponderacion_caba=desc.get(f.coicop_subclase, (None, None, None))[2],
            )
            for f in filas
        ]
    finally:
        db.close()


@app.get("/rubros", response_model=list[Rubro], tags=["catalogo"])
def catalogo_rubros():
    """Catálogo de subclases COICOP en la canasta ENGHo, con descripción y
    ponderación."""
    db = SessionLocal()
    try:
        filas = db.query(PonderacionCoicop).order_by(PonderacionCoicop.coicop_subclase).all()
        return [
            Rubro(
                coicop_subclase=f.coicop_subclase,
                descripcion=f.descripcion_rubro,
                division=f.division,
                ponderacion_caba=_to_float(f.ponderacion_caba),
            )
            for f in filas
        ]
    finally:
        db.close()


@app.get("/comparativo/{periodo}", response_model=Comparativo, tags=["comparativo"])
def comparativo(periodo: str):
    """Compara la variación mensual del índice propio contra la del INDEC
    (Nivel General Nacional) y la del GCBA (Alimentos y Bebidas no
    alcohólicas CABA). Si alguna todavía no publicó el período, su
    `*_disponible` da false — no bloquea la respuesta."""
    db = SessionLocal()
    try:
        propio = (
            db.query(IndiceCalculado)
            .filter(IndiceCalculado.nivel == "general", IndiceCalculado.periodo == periodo)
            .first()
        )
        if not propio:
            raise HTTPException(404, f"No hay índice propio calculado para {periodo}")

        variacion_propia = _to_float(propio.variacion_pct)

        indec_disp, indec_val, indec_var = _valor_variacion_serie(db, SERIE_INDEC_NACIONAL, periodo)
        gcba_disp, gcba_val, gcba_var = _valor_variacion_serie(db, config.SERIE_IPC_CABA_ALIMENTOS, periodo)
        gba_disp, gba_val, gba_var = _valor_variacion_serie(db, config.SERIE_IPC_GBA_ALIMENTOS, periodo)

        diferencia_indec = None
        if variacion_propia is not None and indec_var is not None:
            diferencia_indec = variacion_propia - indec_var

        diferencia_gcba = None
        if variacion_propia is not None and gcba_var is not None:
            diferencia_gcba = variacion_propia - gcba_var

        diferencia_gba = None
        if variacion_propia is not None and gba_var is not None:
            diferencia_gba = variacion_propia - gba_var

        nota = (
            "INDEC (nivel gral.): comparado contra IPC Nivel General Nacional (todos los "
            "rubros, no solo alimentos). INDEC (GBA alimentos): serie regional específica "
            "de Alimentos y Bebidas. GCBA: serie propia de Alimentos y Bebidas no "
            "alcohólicas de CABA. Todas publican ~día 14 del mes siguiente; si "
            "`*_disponible` es false para alguna, todavía no se publicó ese período o la "
            "serie no está cargada localmente."
        )

        return Comparativo(
            periodo=periodo,
            indice_propio=_to_float(propio.indice_valor),
            variacion_pct_propia=variacion_propia,
            indec_disponible=indec_disp,
            indec_indice=indec_val,
            indec_variacion_pct=indec_var,
            diferencia_puntos_pct=diferencia_indec,
            gcba_disponible=gcba_disp,
            gcba_indice=gcba_val,
            gcba_variacion_pct=gcba_var,
            diferencia_puntos_pct_gcba=diferencia_gcba,
            gba_alimentos_disponible=gba_disp,
            gba_alimentos_indice=gba_val,
            gba_alimentos_variacion_pct=gba_var,
            diferencia_puntos_pct_gba_alimentos=diferencia_gba,
            nota=nota,
        )
    finally:
        db.close()


@app.get("/comparativo/evolucion/general", response_model=list[EvolucionGeneral], tags=["comparativo"])
def evolucion_general():
    """Serie histórica completa (todos los períodos con índice general
    calculado): propio vs. GCBA (Alimentos y Bebidas CABA) vs. INDEC (Nivel
    General Nacional). Alimenta la pestaña 'Evolución general' del
    dashboard — no hace falta pedir período por período."""
    db = SessionLocal()
    try:
        filas = (
            db.query(IndiceCalculado)
            .filter(IndiceCalculado.nivel == "general")
            .order_by(IndiceCalculado.periodo)
            .all()
        )
        resultado = []
        for f in filas:
            variacion_propia = _to_float(f.variacion_pct)
            indec_disp, indec_val, indec_var = _valor_variacion_serie(db, SERIE_INDEC_NACIONAL, f.periodo)
            gcba_disp, gcba_val, gcba_var = _valor_variacion_serie(db, config.SERIE_IPC_CABA_ALIMENTOS, f.periodo)
            gba_disp, gba_val, gba_var = _valor_variacion_serie(db, config.SERIE_IPC_GBA_ALIMENTOS, f.periodo)

            resultado.append(EvolucionGeneral(
                periodo=f.periodo,
                origen_datos=_origen_datos_periodo(db, f.periodo),
                indice_propio=_to_float(f.indice_valor),
                variacion_pct_propia=variacion_propia,
                gcba_disponible=gcba_disp,
                gcba_indice=gcba_val,
                gcba_variacion_pct=gcba_var,
                diferencia_pp_gcba=(variacion_propia - gcba_var)
                    if (variacion_propia is not None and gcba_var is not None) else None,
                gba_alimentos_disponible=gba_disp,
                gba_alimentos_indice=gba_val,
                gba_alimentos_variacion_pct=gba_var,
                diferencia_pp_gba_alimentos=(variacion_propia - gba_var)
                    if (variacion_propia is not None and gba_var is not None) else None,
                indec_disponible=indec_disp,
                indec_indice=indec_val,
                indec_variacion_pct=indec_var,
                diferencia_pp_indec=(variacion_propia - indec_var)
                    if (variacion_propia is not None and indec_var is not None) else None,
            ))
        return resultado
    finally:
        db.close()


@app.get("/comparativo/evolucion/rubro/{coicop_subclase}", response_model=list[EvolucionRubro], tags=["comparativo"])
def evolucion_rubro(coicop_subclase: str):
    """Serie histórica completa de UN rubro (subclase COICOP): propio vs.
    INDEC (aperturas región GBA — el único desglose por rubro que el INDEC
    publica), MÁS los benchmarks generales del período (GCBA e INDEC Nivel
    General Nacional) como referencia — ver docstring de EvolucionRubro.
    Alimenta la pestaña 'Evolución por rubro' del dashboard."""
    db = SessionLocal()
    try:
        filas = (
            db.query(IndiceCalculado)
            .filter(IndiceCalculado.nivel == "coicop_subclase",
                    IndiceCalculado.coicop_subclase == coicop_subclase)
            .order_by(IndiceCalculado.periodo)
            .all()
        )
        if not filas:
            raise HTTPException(404, f"No hay índice calculado para el rubro {coicop_subclase}")

        descripcion = _descripciones_coicop(db).get(coicop_subclase, (None, None, None))[0]
        serie_id = f"APERTURA_{coicop_subclase}"

        resultado = []
        for f in filas:
            variacion_propia = _to_float(f.variacion_pct)

            indec_disp, indec_val, indec_var = _valor_variacion_serie(db, serie_id, f.periodo)

            gcba_gral_disp, _, gcba_gral_var = _valor_variacion_serie(
                db, config.SERIE_IPC_CABA_ALIMENTOS, f.periodo
            )
            indec_gral_disp, _, indec_gral_var = _valor_variacion_serie(
                db, SERIE_INDEC_NACIONAL, f.periodo
            )

            resultado.append(EvolucionRubro(
                periodo=f.periodo,
                coicop_subclase=coicop_subclase,
                descripcion=descripcion,
                indice_propio=_to_float(f.indice_valor),
                variacion_pct_propia=variacion_propia,
                indec_disponible=indec_disp,
                indec_indice=indec_val,
                indec_variacion_pct=indec_var,
                diferencia_pp=(variacion_propia - indec_var)
                    if (variacion_propia is not None and indec_var is not None) else None,
                gcba_general_disponible=gcba_gral_disp,
                gcba_general_variacion_pct=gcba_gral_var,
                diferencia_pp_gcba_general=(variacion_propia - gcba_gral_var)
                    if (variacion_propia is not None and gcba_gral_var is not None) else None,
                indec_general_disponible=indec_gral_disp,
                indec_general_variacion_pct=indec_gral_var,
                diferencia_pp_indec_general=(variacion_propia - indec_gral_var)
                    if (variacion_propia is not None and indec_gral_var is not None) else None,
            ))
        return resultado
    finally:
        db.close()


@app.get("/comparativo/{periodo}/rubros", response_model=list[ComparativoRubro], tags=["comparativo"])
def comparativo_por_rubro(periodo: str):
    """Compara CADA RUBRO (subclase COICOP) de tu índice contra el
    equivalente del INDEC (aperturas por capítulos, región GBA — ver
    comparativo.obtener_indices_indec_por_rubro). Los rubros donde el
    INDEC no publica una serie equivalente, o donde ese período todavía
    no fue publicado, devuelven indec_disponible=false para ese rubro
    puntual (el resto de los rubros de la respuesta no se ven afectados)."""
    db = SessionLocal()
    try:
        propios = (
            db.query(IndiceCalculado)
            .filter(IndiceCalculado.nivel == "coicop_subclase", IndiceCalculado.periodo == periodo)
            .order_by(IndiceCalculado.coicop_subclase)
            .all()
        )
        if not propios:
            raise HTTPException(404, f"No hay apertura por rubros calculada para {periodo}")

        desc = _descripciones_coicop(db)
        inicio_periodo, _ = _periodo_a_rango_fechas(periodo)
        resultado = []

        for f in propios:
            serie_id = f"APERTURA_{f.coicop_subclase}"
            indec_actual = (
                db.query(SerieComparativaINDEC)
                .filter(SerieComparativaINDEC.serie_id == serie_id,
                        SerieComparativaINDEC.fecha == inicio_periodo)
                .first()
            )
            if not indec_actual:
                resultado.append(ComparativoRubro(
                    coicop_subclase=f.coicop_subclase,
                    descripcion=desc.get(f.coicop_subclase, (None, None, None))[0],
                    indice_propio=_to_float(f.indice_valor),
                    variacion_pct_propia=_to_float(f.variacion_pct),
                    indec_disponible=False,
                    nota=("El INDEC aún no publicó este rubro/período, o no tiene serie "
                          "equivalente publicada para esta subclase COICOP."),
                ))
                continue

            indec_anterior = (
                db.query(SerieComparativaINDEC)
                .filter(SerieComparativaINDEC.serie_id == serie_id,
                        SerieComparativaINDEC.fecha < inicio_periodo)
                .order_by(SerieComparativaINDEC.fecha.desc())
                .first()
            )
            variacion_indec = None
            if indec_anterior and float(indec_anterior.valor) > 0:
                variacion_indec = ((float(indec_actual.valor) / float(indec_anterior.valor)) - 1) * 100

            variacion_propia = _to_float(f.variacion_pct)
            diferencia = None
            if variacion_propia is not None and variacion_indec is not None:
                diferencia = variacion_propia - variacion_indec

            resultado.append(ComparativoRubro(
                coicop_subclase=f.coicop_subclase,
                descripcion=desc.get(f.coicop_subclase, (None, None, None))[0],
                indice_propio=_to_float(f.indice_valor),
                variacion_pct_propia=variacion_propia,
                indec_disponible=True,
                indec_indice=_to_float(indec_actual.valor),
                indec_variacion_pct=variacion_indec,
                diferencia_puntos_pct=diferencia,
            ))

        return resultado
    finally:
        db.close()
