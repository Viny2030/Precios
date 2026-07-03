"""
config.py — Configuración central del Analizador de Precios CABA

Todas las URLs de este archivo fueron verificadas manualmente el 2026-07-02
contra las fuentes reales (no se copiaron de un documento sin probar).
Ver las notas junto a cada una para lo que se confirmó y lo que no.
"""
import os

# ── FUENTES DE DATOS PÚBLICOS (LEY 27.275) ──────────────────────────────────

# Portal CKAN del Ministerio de Producción — dataset "Precios Claros - Base SEPA".
# El dominio de descarga real (datos.produccion.gob.ar) tiene un WAF que devuelve
# 403 a pedidos automatizados (verificado: tanto la página del dataset como los
# recursos ZIP/XLSX individuales). El mirror datos.gob.ar SÍ permite consultar
# el listado de recursos vía su API (no descargar los archivos en sí).
# ver ingesta.py para cómo se maneja esto en la práctica (intento automático +
# fallback a carga manual).
CKAN_API_SEPA = "https://datos.gob.ar/api/3/action/package_show"
CKAN_DATASET_SEPA = "produccion-precios-claros---base-sepa"

# Días de la semana tal como los nombra el dataset (recursos "Lunes".."Domingo").
DIAS_SEPA = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]

# Código de provincia INDEC para Ciudad Autónoma de Buenos Aires (Resolución
# INDEC 55/2019, Anexo I). El dataset SEPA no tiene un dataset separado de
# "sucursales CABA" en BA Data con ese nombre — en cambio, cada fila del SEPA
# ya trae su propio código de provincia, así que filtramos directo por acá.
CODIGO_PROVINCIA_CABA = "02"

# API de Series de Tiempo del Ministerio de Economía — para comparar contra el
# IPC oficial. Se usan DOS series reales y vigentes (verificadas 2026-07-02):
#   - IPC-GBA Alimentos y Bebidas (INDEC, base dic-2016, mensual): la serie
#     regional que más se acerca a CABA en las estadísticas nacionales.
#   - IPC Alimentos y Bebidas no alcohólicas de la Ciudad de Buenos Aires
#     (Dirección Gral. de Estadística y Censos GCBA): específica de CABA.
SERIES_API_BASE = "https://apis.datos.gob.ar/series/api/series/"
SERIE_IPC_GBA_ALIMENTOS = "101.1_I2AB_2016_M_26"       # INDEC, IPC-GBA Alimentos y Bebidas
SERIE_IPC_CABA_ALIMENTOS = "193.2_ALIMENTOS_CAS_2021_0_32_80"  # GCBA, específica de CABA

# --- CONFIGURACIÓN DE ALMACENAMIENTO ---
# Por defecto usamos SQLite para desarrollo local ágil. En producción, seteá
# DATABASE_URL como variable de entorno (postgresql://...).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "indice_caba.sqlite")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
if DATABASE_URL.startswith("postgres://"):
    # Railway/Heroku entregan el prefijo viejo; SQLAlchemy 2.x quiere postgresql://
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# --- PARÁMETROS ECONOMÉTRICOS ---
# Período base para el cálculo del índice (ej. Enero 2026 = 100).
PERIODO_BASE = "2026-01"

# Divisiones COICOP relevantes (01 = Alimentos, 02 = Bebidas alcohólicas y tabaco)
DIVISIONES_COICOP = ["01", "02"]

# Umbral de outliers: si el precio de un día para un EAN se desvía más de este
# múltiplo respecto a la mediana del EAN en ese mes, se descarta como error de
# carga antes de calcular la media geométrica mensual (Fase I).
UMBRAL_OUTLIER_RATIO = 5.0

# User-Agent honesto para las descargas — identifica el proyecto, no intenta
# hacerse pasar por un navegador para evadir controles anti-bot.
USER_AGENT = "AnalizadorPreciosCABA/1.0 (+proyecto de monitoreo de precios bajo Ley 27.275)"