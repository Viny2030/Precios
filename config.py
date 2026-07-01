import os

# --- FUENTES DE DATOS PÚBLICOS (LEY 27.275) ---
# URLs base extraídas del portal oficial
URL_BASE_DATOS_GOV = "https://datos.gob.ar/dataset/produccion-precios-claros---base-sepa"

# Diccionario de URLs de descarga directa diaria (reemplazar con los tokens reales del portal)
URLS_DIARIAS_SEPA = {
    "lunes": "https://datos.gob.ar/dataset/.../precios-sepa-minoristas-lunes.zip",
    "martes": "https://datos.gob.ar/dataset/.../precios-sepa-minoristas-martes.zip",
    "miercoles": "https://datos.gob.ar/dataset/.../precios-sepa-minoristas-miercoles.zip",
    "jueves": "https://datos.gob.ar/dataset/.../precios-sepa-minoristas-jueves.zip",
    "viernes": "https://datos.gob.ar/dataset/.../precios-sepa-minoristas-viernes.zip"
}

# Padrón de supermercados de CABA (BA Data)
URL_SUCURSALES_CABA = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/supermercados/supermercados.csv"

# --- CONFIGURACIÓN DE ALMACENAMIENTO ---
# Por defecto usamos SQLite para desarrollo local ágil
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "indice_caba.sqlite")
ENGINE_STR = f"sqlite:///{DB_PATH}"

# --- PARÁMETROS ECONOMÉTRICOS ---
# Período base para el cálculo del índice (ej. Año 2026 = 100)
PERIODO_BASE = "2026-01"
