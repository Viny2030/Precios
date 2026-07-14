"""
tests/test_econometria.py — Tests unitarios de econometria.py (Fases I/II/III).

Corré con: pytest tests/ -v
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import config
import econometria as eco


# ── Fase 0: filtrar_outliers ────────────────────────────────────────────────

class TestFiltrarOutliers:
    def test_descarta_valor_muy_por_encima_de_la_mediana(self):
        df = pd.DataFrame({
            "ean": [1, 1, 1, 1],
            "precio": [100, 105, 95, 100 * config.UMBRAL_OUTLIER_RATIO * 2],
        })
        resultado = eco.filtrar_outliers(df)
        assert len(resultado) == 3
        assert (resultado["precio"] < 1000).all()

    def test_descarta_valor_muy_por_debajo_de_la_mediana(self):
        df = pd.DataFrame({
            "ean": [1, 1, 1, 1],
            "precio": [100, 105, 95, 100 / (config.UMBRAL_OUTLIER_RATIO * 2)],
        })
        resultado = eco.filtrar_outliers(df)
        assert len(resultado) == 3

    def test_mantiene_valores_dentro_del_rango(self):
        df = pd.DataFrame({"ean": [1, 1, 1], "precio": [100, 110, 90]})
        resultado = eco.filtrar_outliers(df)
        assert len(resultado) == 3

    def test_df_vacio_devuelve_vacio(self):
        df = pd.DataFrame(columns=["ean", "precio"])
        resultado = eco.filtrar_outliers(df)
        assert resultado.empty

    def test_columna_de_precio_ausente_devuelve_sin_tocar(self):
        df = pd.DataFrame({"ean": [1, 2], "otra_cosa": [1, 2]})
        resultado = eco.filtrar_outliers(df)
        assert len(resultado) == 2

    def test_grupos_distintos_se_evaluan_independientemente(self):
        # El EAN 2 tiene un outlier, pero no debe afectar al EAN 1.
        df = pd.DataFrame({
            "ean": [1, 1, 1, 2, 2, 2],
            "precio": [100, 100, 100, 50, 50, 50 * config.UMBRAL_OUTLIER_RATIO * 3],
        })
        resultado = eco.filtrar_outliers(df)
        assert (resultado["ean"] == 1).sum() == 3
        assert (resultado["ean"] == 2).sum() == 2


# ── Fase I: media geométrica / precio_promedio_mensual ─────────────────────

class TestMediaGeometrica:
    def test_caso_basico(self):
        # media geometrica de 2 y 8 = sqrt(16) = 4
        assert eco._media_geometrica(pd.Series([2.0, 8.0])) == pytest.approx(4.0)

    def test_ignora_nan(self):
        serie = pd.Series([2.0, np.nan, 8.0])
        assert eco._media_geometrica(serie) == pytest.approx(4.0)

    def test_ignora_valores_cero_o_negativos(self):
        serie = pd.Series([2.0, 0.0, -5.0, 8.0])
        assert eco._media_geometrica(serie) == pytest.approx(4.0)

    def test_serie_vacia_devuelve_nan(self):
        assert math.isnan(eco._media_geometrica(pd.Series([], dtype=float)))

    def test_todo_invalido_devuelve_nan(self):
        assert math.isnan(eco._media_geometrica(pd.Series([0.0, -1.0, np.nan])))

    def test_un_solo_valor(self):
        assert eco._media_geometrica(pd.Series([50.0])) == pytest.approx(50.0)


class TestPrecioPromedioMensual:
    def test_calcula_promedio_por_ean(self):
        df = pd.DataFrame({
            "ean": [1, 1, 2, 2],
            "fecha": pd.to_datetime(["2026-07-01", "2026-07-02"] * 2),
            "precio_normalizado": [100.0, 100.0, 10.0, 40.0],
        })
        resultado = eco.precio_promedio_mensual(df, "2026-07")
        fila1 = resultado[resultado["ean"] == 1].iloc[0]
        fila2 = resultado[resultado["ean"] == 2].iloc[0]
        assert fila1["precio_prom"] == pytest.approx(100.0)
        assert fila2["precio_prom"] == pytest.approx(20.0)  # sqrt(10*40)
        assert (resultado["periodo"] == "2026-07").all()

    def test_df_vacio(self):
        df = pd.DataFrame(columns=["ean", "fecha", "precio_normalizado"])
        resultado = eco.precio_promedio_mensual(df, "2026-07")
        assert resultado.empty
        assert list(resultado.columns) == ["ean", "periodo", "precio_prom", "dias_con_dato"]


# ── Fase II: índice de Jevons por subclase ──────────────────────────────────

class TestIndiceJevonsPorSubclase:
    def test_calcula_indice_correctamente(self):
        precios_periodo = pd.DataFrame({"ean": [1, 2], "precio_prom": [110.0, 220.0]})
        precios_base = pd.DataFrame({"ean": [1, 2], "precio_prom": [100.0, 200.0]})
        coicop = {"1": "01.1.1", "2": "01.1.1"}
        resultado = eco.indice_jevons_por_subclase(precios_periodo, precios_base, coicop)
        assert len(resultado) == 1
        fila = resultado.iloc[0]
        assert fila["coicop_subclase"] == "01.1.1"
        # ambos productos subieron 10% => relativo 1.1 => indice 110
        assert fila["indice_jevons"] == pytest.approx(110.0)
        assert fila["n_variedades"] == 2

    def test_sin_overlap_de_eans_devuelve_vacio(self):
        """Reproduce el caso real que rompió el calculo de julio: la base
        (junio, sintetico) y el periodo (julio, real) no comparten EANs."""
        precios_periodo = pd.DataFrame({"ean": [100, 101], "precio_prom": [50.0, 60.0]})
        precios_base = pd.DataFrame({"ean": [1, 2], "precio_prom": [100.0, 200.0]})
        coicop = {"1": "01.1.1", "2": "01.1.1", "100": "01.1.1", "101": "01.1.1"}
        resultado = eco.indice_jevons_por_subclase(precios_periodo, precios_base, coicop)
        assert resultado.empty

    def test_eans_sin_clasificar_se_excluyen(self):
        precios_periodo = pd.DataFrame({"ean": [1, 2], "precio_prom": [110.0, 220.0]})
        precios_base = pd.DataFrame({"ean": [1, 2], "precio_prom": [100.0, 200.0]})
        coicop = {}  # diccionario vacio -> nada clasificado
        resultado = eco.indice_jevons_por_subclase(precios_periodo, precios_base, coicop)
        assert resultado.empty

    def test_inputs_vacios(self):
        vacio = pd.DataFrame(columns=["ean", "precio_prom"])
        no_vacio = pd.DataFrame({"ean": [1], "precio_prom": [1.0]})
        assert eco.indice_jevons_por_subclase(vacio, no_vacio, {}).empty
        assert eco.indice_jevons_por_subclase(no_vacio, vacio, {}).empty

    def test_precios_no_positivos_se_excluyen(self):
        precios_periodo = pd.DataFrame({"ean": [1, 2], "precio_prom": [0.0, 220.0]})
        precios_base = pd.DataFrame({"ean": [1, 2], "precio_prom": [100.0, 200.0]})
        coicop = {"1": "01.1.1", "2": "01.1.1"}
        resultado = eco.indice_jevons_por_subclase(precios_periodo, precios_base, coicop)
        assert resultado.iloc[0]["n_variedades"] == 1


# ── Fase III: agregación Laspeyres ──────────────────────────────────────────

class TestAgregacionLaspeyres:
    def test_agregacion_basica(self):
        indices = pd.DataFrame({
            "coicop_subclase": ["01.1.1", "01.1.2"],
            "indice_jevons": [110.0, 120.0],
            "n_variedades": [3, 2],
        })
        ponderaciones = pd.DataFrame({
            "coicop_subclase": ["01.1.1", "01.1.2"],
            "ponderacion_caba": [0.6, 0.4],
        })
        resultado = eco.agregacion_laspeyres(indices, ponderaciones)
        assert resultado is not None
        esperado = 110.0 * 0.6 + 120.0 * 0.4
        assert resultado["indice_general"] == pytest.approx(esperado)
        assert resultado["cobertura_ponderacion"] == pytest.approx(1.0)
        assert resultado["n_subclases"] == 2

    def test_inputs_vacios_devuelve_none(self):
        vacio = pd.DataFrame(columns=["coicop_subclase", "indice_jevons"])
        no_vacio = pd.DataFrame({"coicop_subclase": ["01.1.1"], "ponderacion_caba": [1.0]})
        assert eco.agregacion_laspeyres(vacio, no_vacio) is None
        assert eco.agregacion_laspeyres(
            pd.DataFrame({"coicop_subclase": ["01.1.1"], "indice_jevons": [100.0]}),
            pd.DataFrame(columns=["coicop_subclase", "ponderacion_caba"]),
        ) is None

    def test_sin_subclases_en_comun_devuelve_none(self):
        indices = pd.DataFrame({"coicop_subclase": ["99.9.9"], "indice_jevons": [100.0], "n_variedades": [1]})
        ponderaciones = pd.DataFrame({"coicop_subclase": ["01.1.1"], "ponderacion_caba": [1.0]})
        assert eco.agregacion_laspeyres(indices, ponderaciones) is None

    def test_cobertura_baja_devuelve_none(self):
        """Antes del fix, el chequeo comparaba contra 0.0 y nunca disparaba.
        Con config.COBERTURA_MINIMA (0.5 por defecto), una subclase que
        representa poco peso de la canasta no debe publicar índice."""
        indices = pd.DataFrame({
            "coicop_subclase": ["01.1.1"],
            "indice_jevons": [100.0],
            "n_variedades": [1],
        })
        ponderaciones = pd.DataFrame({
            "coicop_subclase": ["01.1.1", "01.1.2", "01.1.3"],
            # 01.1.1 pesa solo 10% de la canasta total -> cobertura 0.10 < COBERTURA_MINIMA
            "ponderacion_caba": [0.10, 0.60, 0.30],
        })
        assert eco.agregacion_laspeyres(indices, ponderaciones) is None

    def test_cobertura_suficiente_calcula(self):
        indices = pd.DataFrame({
            "coicop_subclase": ["01.1.1", "01.1.2"],
            "indice_jevons": [100.0, 100.0],
            "n_variedades": [1, 1],
        })
        ponderaciones = pd.DataFrame({
            "coicop_subclase": ["01.1.1", "01.1.2", "01.1.3"],
            "ponderacion_caba": [0.30, 0.30, 0.40],  # cobertura = 0.60 >= 0.5
        })
        resultado = eco.agregacion_laspeyres(indices, ponderaciones)
        assert resultado is not None
        assert resultado["cobertura_ponderacion"] == pytest.approx(0.60)

    def test_renormaliza_pesos_a_subclases_disponibles(self):
        indices = pd.DataFrame({
            "coicop_subclase": ["01.1.1", "01.1.2"],
            "indice_jevons": [110.0, 130.0],
            "n_variedades": [1, 1],
        })
        ponderaciones = pd.DataFrame({
            "coicop_subclase": ["01.1.1", "01.1.2", "01.1.3"],
            "ponderacion_caba": [0.3, 0.3, 0.4],  # 01.1.3 sin dato este periodo
        })
        resultado = eco.agregacion_laspeyres(indices, ponderaciones)
        # peso renormalizado: 0.3/0.6=0.5 y 0.3/0.6=0.5 (excluye 01.1.3)
        esperado = 110.0 * 0.5 + 130.0 * 0.5
        assert resultado["indice_general"] == pytest.approx(esperado)
