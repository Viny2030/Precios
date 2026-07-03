"""
app.py — Dashboard online (Streamlit)

Correr con: streamlit run app.py
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import func

import comparativo
import config
from models import IndiceCalculado, RegistroPrecio, SerieComparativaINDEC, SessionLocal

st.set_page_config(page_title="Índice de Precios CABA — Nueva Canasta", layout="wide")

st.title("📊 Índice de Alimentos y Bebidas — CABA")
st.caption(
    "Nueva Canasta (ENGHo 2017-2018 / COICOP) · Fórmula de Jevons + Laspeyres · "
    "Datos oficiales bajo Ley 27.275 — cero datos sintéticos."
)

db = SessionLocal()


# ── Estado general de la base ────────────────────────────────────────────────

total_registros = db.query(func.count(RegistroPrecio.id)).scalar() or 0
total_indices = db.query(func.count(IndiceCalculado.id)).scalar() or 0

if total_registros == 0:
    st.warning(
        "⚠️ Todavía no hay registros de precios cargados en la base.\n\n"
        "Esto es esperable si es la primera vez que corrés el proyecto: correr "
        "`python main.py` descarga (o intenta descargar) el ZIP del día del SEPA. "
        "Si el portal bloqueó la descarga automática (ver `ingesta.py` para el porqué), "
        "descargá el ZIP a mano desde https://datos.gob.ar/dataset/produccion-precios-claros---base-sepa "
        "y guardalo en `data/manual/<dia>.zip` antes de volver a correr `main.py`."
    )
    db.close()
    st.stop()


col1, col2, col3 = st.columns(3)
col1.metric("Registros de precios (CABA)", f"{total_registros:,}")
col2.metric("Períodos con índice calculado", total_indices)

ultimo_indice = (
    db.query(IndiceCalculado)
    .filter(IndiceCalculado.nivel == "general")
    .order_by(IndiceCalculado.periodo.desc())
    .first()
)
if ultimo_indice:
    col3.metric(
        f"Inflación Alimentos — {ultimo_indice.periodo}",
        f"{float(ultimo_indice.variacion_pct or 0):+.1f}%",
    )
else:
    col3.metric("Inflación Alimentos", "sin calcular todavía")

st.divider()


# ── Gráfico de tendencia: índice propio vs. oficial ──────────────────────────

st.subheader("Tu índice vs. IPC oficial")

indices_generales = pd.read_sql(
    db.query(IndiceCalculado)
    .filter(IndiceCalculado.nivel == "general")
    .order_by(IndiceCalculado.periodo)
    .statement,
    db.bind,
)

serie_oficial = pd.read_sql(db.query(SerieComparativaINDEC).statement, db.bind)

fig = go.Figure()
if not indices_generales.empty:
    fig.add_trace(go.Scatter(
        x=indices_generales["periodo"], y=indices_generales["indice_valor"].astype(float),
        name="Índice propio (Nueva Canasta)", mode="lines+markers",
    ))
if not serie_oficial.empty:
    for serie_id, nombre in [
        (config.SERIE_IPC_GBA_ALIMENTOS, "IPC-GBA Alimentos (INDEC)"),
        (config.SERIE_IPC_CABA_ALIMENTOS, "IPC Alimentos CABA (GCBA)"),
    ]:
        sub = serie_oficial[serie_oficial["serie_id"] == serie_id]
        if not sub.empty:
            fig.add_trace(go.Scatter(
                x=sub["fecha"], y=sub["valor"].astype(float),
                name=nombre, mode="lines", line=dict(dash="dot"),
            ))

if fig.data:
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Sin datos suficientes todavía para graficar la tendencia.")

if st.button("🔄 Actualizar serie comparativa (INDEC/GCBA)"):
    with st.spinner("Descargando series oficiales..."):
        df_comp = comparativo.obtener_historico_comparativo()
        if not df_comp.empty:
            comparativo.guardar_en_db(db, df_comp)
            st.success("Serie actualizada — recargá la página para ver el gráfico.")
        else:
            st.error("No se pudo descargar la serie oficial en este momento.")

st.divider()


# ── Apertura por rubros COICOP ───────────────────────────────────────────────

st.subheader("Apertura por rubros COICOP")

indices_subclase = pd.read_sql(
    db.query(IndiceCalculado)
    .filter(IndiceCalculado.nivel == "coicop_subclase")
    .order_by(IndiceCalculado.periodo.desc())
    .statement,
    db.bind,
)

if not indices_subclase.empty:
    ultimo_periodo = indices_subclase["periodo"].max()
    tabla = indices_subclase[indices_subclase["periodo"] == ultimo_periodo][
        ["coicop_subclase", "indice_valor", "variacion_pct", "cantidad_variedades"]
    ].sort_values("variacion_pct", ascending=False)
    st.dataframe(tabla, use_container_width=True, hide_index=True)
else:
    st.info("Todavía no hay índices por subclase COICOP calculados.")

db.close()

st.caption(
    "Fuentes: SEPA/Precios Claros (Ministerio de Producción), ENGHo 2017-2018 (INDEC), "
    "IPC-GBA (INDEC), IPC CABA (GCBA). Ver README.md para el detalle metodológico y las "
    "limitaciones de acceso automatizado conocidas."
)
