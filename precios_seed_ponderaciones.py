"""
seed_ponderaciones.py — Carga REAL de ponderaciones COICOP desde el INDEC

Descubrimiento (2026-07-02): a diferencia de lo que se pensó inicialmente,
el INDEC SÍ publica un archivo descargable con ponderaciones reales de la
canasta, por región, hasta nivel de "grupo" COICOP (ej. 01.1.1 "Pan y
cereales"). No es la ENGHo cruda, pero es la estructura de pesos que el
propio INDEC usa para calcular el IPC oficial — y es tan real y citable
como el IPC en sí.

Fuente: https://www.indec.gob.ar/ftp/cuadros/economia/sh_ipc_aperturas.xls
        (hoja "Ponderaciones", tabla "según principales aperturas")
Clasificador de referencia: https://www.indec.gob.ar/ftp/cuadros/menusuperior/clasificadores/coicop_argentina_2019.xls

Importante — limitación real, no inventada: esta tabla del INDEC solo
publica los grupos que superan un umbral de peso (2%, o 1.5% para
Alimentos/Bebidas y Regulados) dentro de su categoría. Por eso, la suma de
los pesos cargados acá no llega al 100% de las divisiones 01+02 — quedan
afuera categorías chicas como "Pescados y mariscos" u "Otros alimentos",
que el INDEC no desagrega en esta publicación. econometria.py ya maneja
esto correctamente: renormaliza los pesos disponibles antes de agregar
(ver agregacion_laspeyres), en vez de asumir que suman 1.0.

La región usada es GBA (Gran Buenos Aires, que incluye CABA) — es la
apertura regional más específica que el INDEC publica; no hay una apertura
exclusiva de CABA en este archivo.

Uso:
    python seed_ponderaciones.py
"""
import io
import logging

import pandas as pd
import requests

import config
from models import PonderacionCoicop, SessionLocal, crear_tablas

logger = logging.getLogger("seed_ponderaciones")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

URL_APERTURAS_INDEC = "https://www.indec.gob.ar/ftp/cuadros/economia/sh_ipc_aperturas.xls"

# Mapeo nombre de fila (tal como aparece en la hoja "Ponderaciones" del
# INDEC) -> código COICOP de grupo (nivel 4), verificado contra
# coicop_argentina_2019.xls. Es la única parte que necesitaría ajuste si el
# INDEC cambia los nombres de fila en una futura versión del archivo.
MAPEO_FILA_A_CODIGO = {
    "Pan y cereales": "01.1.1",
    "Carnes y derivados": "01.1.2",
    "Leche, productos lácteos y huevos": "01.1.4",
    "Aceites, grasas y manteca": "01.1.5",
    "Frutas": "01.1.6",
    "Verduras, tubérculos y legumbres": "01.1.7",
    "Azúcar, dulces, chocolate, golosinas, etc.": "01.1.8",
    "Café, té, yerba y cacao": "01.2.1",
    "Aguas minerales, bebidas gaseosas y jugos": "01.2.2",
    "Bebidas alcohólicas": "02.1",     # agregado — el INDEC no desagrega espirituosas/vinos/cerveza en esta tabla
    "Tabaco": "02.2.1",
}


def descargar_ponderaciones_indec(columna_region: str = "GBA") -> pd.DataFrame:
    """
    Descarga sh_ipc_aperturas.xls, extrae la sección "según principales
    aperturas" de la hoja Ponderaciones, y devuelve un DataFrame con
    columnas: coicop_subclase, descripcion_rubro, ponderacion_caba, division.
    """
    logger.info(f"Descargando {URL_APERTURAS_INDEC} ...")
    resp = requests.get(URL_APERTURAS_INDEC, headers={"User-Agent": config.USER_AGENT}, timeout=30)
    resp.raise_for_status()

    df_raw = pd.read_excel(io.BytesIO(resp.content), sheet_name="Ponderaciones", header=None)

    # Localizar la fila de encabezado de la tabla "según principales aperturas"
    fila_header = df_raw[df_raw[0].astype(str).str.contains("Descripcion", na=False)].index
    if len(fila_header) == 0:
        raise ValueError("No se encontró la tabla 'según principales aperturas' — "
                          "el INDEC pudo haber cambiado el formato del archivo.")
    idx_header = fila_header[0]
    columnas = df_raw.loc[idx_header].tolist()
    columnas[0] = "descripcion"

    bloque = df_raw.loc[idx_header + 1:].copy()
    bloque.columns = columnas
    # cortar en la primera fila vacía o de "Fuente:" (fin de la tabla)
    fin = bloque[bloque["descripcion"].astype(str).str.startswith("Fuente", na=False)].index
    if len(fin):
        bloque = bloque.loc[: fin[0] - 1]

    filas = []
    for _, fila in bloque.iterrows():
        nombre = str(fila["descripcion"]).strip()
        codigo = MAPEO_FILA_A_CODIGO.get(nombre)
        if codigo is None:
            continue  # fila no relevante (otra división, subtotal, etc.)
        peso = fila.get(columna_region)
        if pd.isna(peso):
            continue
        filas.append({
            "coicop_subclase": codigo,
            "descripcion_rubro": nombre,
            "ponderacion_caba": float(peso),
            "division": codigo[:2],
        })

    df_pond = pd.DataFrame(filas)
    logger.info(f"{len(df_pond)} grupos con ponderación real extraídos (región {columna_region})")
    return df_pond


def guardar_ponderaciones(df_pond: pd.DataFrame):
    crear_tablas()
    db = SessionLocal()
    try:
        actualizados, nuevos = 0, 0
        for _, fila in df_pond.iterrows():
            existente = db.query(PonderacionCoicop).filter_by(coicop_subclase=fila["coicop_subclase"]).first()
            if existente:
                existente.descripcion_rubro = fila["descripcion_rubro"]
                existente.ponderacion_caba = fila["ponderacion_caba"]
                existente.division = fila["division"]
                existente.fuente = "INDEC - sh_ipc_aperturas.xls (región GBA)"
                actualizados += 1
            else:
                db.add(PonderacionCoicop(
                    coicop_subclase=fila["coicop_subclase"],
                    descripcion_rubro=fila["descripcion_rubro"],
                    ponderacion_caba=fila["ponderacion_caba"],
                    division=fila["division"],
                    fuente="INDEC - sh_ipc_aperturas.xls (región GBA)",
                ))
                nuevos += 1
        db.commit()
        logger.info(f"Listo — {nuevos} ponderaciones nuevas, {actualizados} actualizadas")
        suma = df_pond["ponderacion_caba"].sum()
        logger.info(
            f"Suma de pesos cargados: {suma:.3f} (no llega a 0.267 = división 01+02 "
            f"completa porque el INDEC no desagrega categorías chicas como 'Pescados "
            f"y mariscos' en esta tabla — ver docstring del módulo)"
        )
    finally:
        db.close()


if __name__ == "__main__":
    df_pond = descargar_ponderaciones_indec()
    print(df_pond.to_string(index=False))
    guardar_ponderaciones(df_pond)
