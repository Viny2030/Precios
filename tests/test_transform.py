"""
tests/test_transform.py — Tests unitarios de transform.py (normalización de
variedades y mapeo COICOP).

Corré con: pytest tests/ -v
"""
from __future__ import annotations

import pandas as pd
import pytest

import config
import transform


# ── _canon_ean ───────────────────────────────────────────────────────────

class TestCanonEan:
    def test_string_normal(self):
        assert transform._canon_ean("7790895000997") == "7790895000997"

    def test_quita_ceros_a_la_izquierda(self):
        assert transform._canon_ean("0022000006653") == "22000006653"

    def test_float_serializado_por_pandas(self):
        assert transform._canon_ean("7790895000997.0") == "7790895000997"

    def test_float_python(self):
        assert transform._canon_ean(7790895000997.0) == "7790895000997"

    def test_quita_caracteres_no_numericos(self):
        assert transform._canon_ean("779-089-5000997") == "7790895000997"

    def test_none_devuelve_none(self):
        assert transform._canon_ean(None) is None

    def test_nan_devuelve_none(self):
        assert transform._canon_ean(float("nan")) is None

    def test_todo_ceros_devuelve_none(self):
        assert transform._canon_ean("0000") is None

    def test_string_vacio_devuelve_none(self):
        assert transform._canon_ean("") is None

    def test_normaliza_a_la_misma_forma_canonica(self):
        # Este es el caso real que main.py/transform.py necesitan: el mismo
        # producto llega distinto desde Excel/CSV y desde la BD, pero debe
        # matchear igual.
        a = transform._canon_ean("0007790895000997")
        b = transform._canon_ean(7790895000997.0)
        assert a == b == "7790895000997"


# ── extraer_contenido_neto ───────────────────────────────────────────────

class TestExtraerContenidoNeto:
    @pytest.mark.parametrize("nombre,esperado_valor,esperado_unidad", [
        ("Leche entera sachet 1L", 1.0, "l"),
        ("Fideos guisero 500g", 0.5, "kg"),
        ("Agua mineral 2.25L", 2.25, "l"),
        ("Yerba mate 1kg", 1.0, "kg"),
        ("Gaseosa cola 2,25 L", 2.25, "l"),
        ("Aceite girasol 900ml", 0.9, "l"),
        ("Huevos docena 12u", 12.0, "unidad"),
        ("Manteca 200 gr", 0.2, "kg"),
    ])
    def test_formatos_comunes(self, nombre, esperado_valor, esperado_unidad):
        valor, unidad = transform.extraer_contenido_neto(nombre)
        assert valor == pytest.approx(esperado_valor)
        assert unidad == esperado_unidad

    def test_sin_patron_reconocible(self):
        valor, unidad = transform.extraer_contenido_neto("Producto sin contenido")
        assert valor is None
        assert unidad is None

    def test_input_no_string(self):
        valor, unidad = transform.extraer_contenido_neto(None)
        assert valor is None
        assert unidad is None

    def test_unidad_no_reconocida_devuelve_none(self):
        valor, unidad = transform.extraer_contenido_neto("Producto 500xyz")
        assert valor is None
        assert unidad is None


# ── normalizar_precios ───────────────────────────────────────────────────

class TestNormalizarPrecios:
    def test_normaliza_correctamente(self):
        df = pd.DataFrame({
            "nombre": ["Leche 1L", "Fideos 500g"],
            "precio": [1500.0, 1350.0],
        })
        resultado = transform.normalizar_precios(df)
        assert resultado.loc[0, "precio_normalizado"] == pytest.approx(1500.0)  # 1500/1
        assert resultado.loc[1, "precio_normalizado"] == pytest.approx(2700.0)  # 1350/0.5

    def test_sin_columna_nombre(self):
        df = pd.DataFrame({"precio": [100.0]})
        resultado = transform.normalizar_precios(df)
        assert resultado["precio_normalizado"].isna().all()
        assert resultado["contenido_neto"].isna().all()

    def test_sin_columna_precio(self):
        df = pd.DataFrame({"nombre": ["Leche 1L"]})
        resultado = transform.normalizar_precios(df)
        assert resultado["precio_normalizado"].isna().all()

    def test_fila_sin_contenido_detectable_queda_nan(self):
        df = pd.DataFrame({
            "nombre": ["Producto sin gramaje"],
            "precio": [500.0],
        })
        resultado = transform.normalizar_precios(df)
        assert pd.isna(resultado.loc[0, "precio_normalizado"])


# ── cargar_diccionario_coicop ────────────────────────────────────────────

class TestCargarDiccionarioCoicop:
    def test_archivo_inexistente_crea_vacio_y_devuelve_dict_vacio(self, tmp_path, monkeypatch):
        path = tmp_path / "diccionario_coicop.csv"
        monkeypatch.setattr(transform, "DICCIONARIO_COICOP_PATH", path)
        resultado = transform.cargar_diccionario_coicop()
        assert resultado == {}
        assert path.exists()

    def test_carga_y_canonicaliza_eans(self, tmp_path, monkeypatch):
        path = tmp_path / "diccionario_coicop.csv"
        path.write_text("ean,coicop_subclase\n0022000006653,01.1.1\n7790895000997.0,01.2.2\n", encoding="utf-8")
        monkeypatch.setattr(transform, "DICCIONARIO_COICOP_PATH", path)
        resultado = transform.cargar_diccionario_coicop()
        assert resultado == {"22000006653": "01.1.1", "7790895000997": "01.2.2"}

    def test_archivo_vacio_devuelve_dict_vacio(self, tmp_path, monkeypatch):
        path = tmp_path / "diccionario_coicop.csv"
        path.write_text("ean,coicop_subclase\n", encoding="utf-8")
        monkeypatch.setattr(transform, "DICCIONARIO_COICOP_PATH", path)
        resultado = transform.cargar_diccionario_coicop()
        assert resultado == {}

    def test_filas_con_subclase_vacia_se_ignoran(self, tmp_path, monkeypatch):
        path = tmp_path / "diccionario_coicop.csv"
        path.write_text("ean,coicop_subclase\n123,\n456,01.1.1\n", encoding="utf-8")
        monkeypatch.setattr(transform, "DICCIONARIO_COICOP_PATH", path)
        resultado = transform.cargar_diccionario_coicop()
        assert resultado == {"456": "01.1.1"}


# ── clasificar_coicop ────────────────────────────────────────────────────

class TestClasificarCoicop:
    def test_clasifica_por_ean_canonico(self, tmp_path, monkeypatch):
        path = tmp_path / "diccionario_coicop.csv"
        path.write_text("ean,coicop_subclase\n7790895000997,01.2.2\n", encoding="utf-8")
        monkeypatch.setattr(transform, "DICCIONARIO_COICOP_PATH", path)

        df = pd.DataFrame({"ean": ["0007790895000997", "1111111111111"]})
        resultado = transform.clasificar_coicop(df)
        assert resultado.loc[0, "coicop_subclase"] == "01.2.2"
        assert pd.isna(resultado.loc[1, "coicop_subclase"])

    def test_sin_columna_ean(self):
        df = pd.DataFrame({"otra": [1, 2]})
        resultado = transform.clasificar_coicop(df)
        assert resultado["coicop_subclase"].isna().all()


# ── filtrar_division_alimentos_bebidas ──────────────────────────────────

class TestFiltrarDivisionAlimentosBebidas:
    def test_filtra_por_division(self):
        df = pd.DataFrame({
            "ean": [1, 2, 3],
            "coicop_subclase": ["01.1.1", "02.1", "05.3.2"],
        })
        resultado = transform.filtrar_division_alimentos_bebidas(df)
        assert set(resultado["coicop_subclase"]) == {"01.1.1", "02.1"}
        assert set(resultado["ean"]) == {1, 2}

    def test_sin_columna_coicop_devuelve_vacio(self):
        df = pd.DataFrame({"ean": [1, 2]})
        resultado = transform.filtrar_division_alimentos_bebidas(df)
        assert resultado.empty

    def test_respeta_config_divisiones_coicop(self, monkeypatch):
        monkeypatch.setattr(config, "DIVISIONES_COICOP", ["01"])
        df = pd.DataFrame({
            "ean": [1, 2],
            "coicop_subclase": ["01.1.1", "02.1"],
        })
        resultado = transform.filtrar_division_alimentos_bebidas(df)
        assert list(resultado["ean"]) == [1]
