"""
ingesta.py — Capa A: Descarga y filtrado del SEPA (Precios Claros)

ESTRUCTURA REAL DEL DUMP (verificada 2026-07-03 con inspeccionar_interno.py
sobre el ZIP real de "Jueves", 285 MB):

  sepa_jueves.zip
  └── 2026-07-02/                          ← carpeta con la fecha del relevamiento
      ├── sepa_1_comercio-sepa-8_...zip    ← UN ZIP POR COMERCIO (anidado)
      │   ├── comercio.csv                 ← razón social y bandera(s)
      │   ├── sucursales.csv               ← acá está la PROVINCIA (ISO 3166-2)
      │   └── productos.csv                ← precios (el archivo grande)
      └── ...

Detalles confirmados contra los archivos reales:
  * Separador: pipe "|". Algunos archivos traen BOM → encoding="utf-8-sig".
  * Al final de cada CSV hay líneas basura ("Última actualización: ...") que
    se descartan validando que id_comercio sea numérico.
  * La provincia viene en sucursales.csv como código ISO 3166-2 ("AR-C" =
    CABA, "AR-X" = Córdoba, etc.) — NO el código INDEC "02".
  * EL EAN REAL ESTÁ EN id_producto. La columna productos_ean es un FLAG:
    1 = id_producto es un EAN/GTIN genuino, 0 = código interno del comercio.
  * productos.csv no trae fecha: la fecha sale del nombre de la carpeta.

Sobre la descarga: el dominio datos.produccion.gob.ar tiene un WAF que a
veces devuelve 403 a pedidos automatizados (verificado 2026-07-02; el
2026-07-03 la descarga automática SÍ funcionó — el bloqueo es intermitente).
Este módulo intenta la descarga honesta, cachea el resultado en data/manual/
y, si el WAF bloquea, usa el ZIP cargado manualmente en esa misma carpeta.
Si el bloqueo persistiera en producción, el protocolo correcto (Ley 27.275)
es solicitar el dump vía TAD — ver README.md.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

import config

logger = logging.getLogger("ingesta")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MANUAL_DIR = Path(config.DATA_DIR) / "manual"
MANUAL_DIR.mkdir(parents=True, exist_ok=True)

# Código ISO 3166-2 de CABA (lo que usa realmente el SEPA en sucursales.csv).
# Si lo agregás a config.py como CODIGO_PROVINCIA_CABA_ISO, se usa ese valor.
PROVINCIA_CABA_ISO = getattr(config, "CODIGO_PROVINCIA_CABA_ISO", "AR-C")

# Columnas reales confirmadas en los CSV del SEPA (2026-07-03).
COL_EAN_FLAG = "productos_ean"          # 1 = id_producto es EAN genuino
COL_ID_PRODUCTO = "id_producto"         # acá vive el código de barras real
COL_PRECIO = "productos_precio_lista"
COL_DESCRIPCION = "productos_descripcion"
COL_MARCA = "productos_marca"
COL_CANTIDAD = "productos_cantidad_presentacion"
COL_UNIDAD = "productos_unidad_medida_presentacion"
CLAVE_SUCURSAL = ["id_comercio", "id_bandera", "id_sucursal"]


# ─────────────────────────── descarga / caché ───────────────────────────────

def _descargar_zip_dia(dia: str) -> Optional[bytes]:
    """Descarga vía catálogo CKAN. Devuelve None si el WAF bloquea (403)."""
    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    try:
        r = requests.get(
            config.CKAN_API_SEPA,
            params={"id": config.CKAN_DATASET_SEPA},
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        recursos = r.json()["result"]["resources"]
    except Exception as e:
        logger.error(f"No se pudo consultar el catálogo CKAN: {e}")
        return None

    url_dia = next((rec["url"] for rec in recursos if rec.get("name", "").lower() == dia.lower()), None)
    if not url_dia:
        logger.error(f"No se encontró el recurso '{dia}' en el catálogo CKAN")
        return None

    try:
        resp = requests.get(url_dia, headers=headers, timeout=300)
        if resp.status_code == 403:
            logger.warning(
                f"El servidor bloqueó la descarga automática de '{dia}' (403 — WAF). "
                f"Modo manual: descargá {url_dia} desde un navegador y guardalo "
                f"en {MANUAL_DIR / (dia.lower() + '.zip')}"
            )
            return None
        resp.raise_for_status()
        # Cachear para no volver a bajar 285 MB en la próxima corrida del día.
        (MANUAL_DIR / f"{dia.lower()}.zip").write_bytes(resp.content)
        logger.info(f"Descarga OK ({len(resp.content)/1e6:.0f} MB) — cacheada en data/manual/")
        return resp.content
    except Exception as e:
        logger.error(f"Error al descargar '{dia}': {e}")
        return None


def _fecha_interna_zip(zip_bytes: bytes) -> Optional[date]:
    """Lee la fecha del relevamiento desde el nombre de la carpeta interna."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for nombre in z.namelist():
                m = re.match(r"(\d{4}-\d{2}-\d{2})/", nombre)
                if m:
                    return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except Exception:
        pass
    return None


def _obtener_zip_dia(dia: str) -> Optional[bytes]:
    """
    Estrategia: usar el ZIP cacheado/manual si es fresco (≤7 días); si es
    viejo o no existe, intentar descarga; si la descarga falla, usar lo que
    haya en manual aunque sea viejo (con advertencia).
    """
    candidato = MANUAL_DIR / f"{dia.lower()}.zip"
    zip_local = candidato.read_bytes() if candidato.exists() else None

    if zip_local:
        fecha = _fecha_interna_zip(zip_local)
        if fecha and (date.today() - fecha) <= timedelta(days=7):
            logger.info(f"Usando ZIP local {candidato} (relevamiento {fecha})")
            return zip_local
        logger.info(f"ZIP local de '{dia}' es viejo (relevamiento {fecha}) — intento re-descargar")

    descargado = _descargar_zip_dia(dia)
    if descargado:
        return descargado
    if zip_local:
        logger.warning(f"Descarga falló — uso el ZIP local viejo de '{dia}' como último recurso")
        return zip_local
    return None


# ─────────────────────────── parseo de CSVs SEPA ────────────────────────────

def _leer_csv_sepa(zf: zipfile.ZipFile, nombre: str, **kwargs) -> pd.DataFrame:
    """Lee un CSV interno del SEPA: pipe, BOM, y descarta las líneas basura
    del final ('Última actualización: ...') validando id_comercio numérico."""
    with zf.open(nombre) as f:
        df = pd.read_csv(
            f, sep="|", encoding="utf-8-sig", dtype=str,
            on_bad_lines="skip", **kwargs,
        )
    if "id_comercio" in df.columns:
        df = df[pd.to_numeric(df["id_comercio"], errors="coerce").notna()]
    return df


def _col_provincia(df_suc: pd.DataFrame) -> Optional[str]:
    """Encuentra la columna de provincia en sucursales.csv: por nombre, y si
    no, por contenido (valores que arrancan con 'AR-')."""
    for c in df_suc.columns:
        if "provincia" in c.lower():
            return c
    for c in df_suc.columns:
        vals = df_suc[c].dropna().astype(str).head(50)
        if len(vals) and (vals.str.match(r"AR-[A-Z]").mean() > 0.8):
            return c
    return None


def _procesar_zip_comercio(
    zip_bytes: bytes, nombre: str, fecha: Optional[date], chunksize: int
) -> pd.DataFrame:
    """Procesa el ZIP de UN comercio: si tiene sucursales en CABA, devuelve
    sus productos filtrados a esas sucursales; si no, DataFrame vacío."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        nombres = {n.lower().rsplit("/", 1)[-1]: n for n in z.namelist()}
        if "sucursales.csv" not in nombres or "productos.csv" not in nombres:
            logger.warning(f"  {nombre}: sin sucursales.csv/productos.csv — salteado")
            return pd.DataFrame()

        # 1) Sucursales: ¿este comercio tiene presencia en CABA?
        suc = _leer_csv_sepa(z, nombres["sucursales.csv"])
        col_prov = _col_provincia(suc)
        if col_prov is None:
            logger.warning(f"  {nombre}: no se detectó columna de provincia — salteado")
            return pd.DataFrame()
        suc_caba = suc[suc[col_prov].astype(str).str.strip() == PROVINCIA_CABA_ISO]
        if suc_caba.empty:
            return pd.DataFrame()  # comercio sin CABA: no leemos sus productos

        claves_caba = set(map(tuple, suc_caba[CLAVE_SUCURSAL].astype(str).values))
        logger.info(f"  {nombre}: {len(claves_caba)} sucursales CABA — leyendo productos")

        # 2) Nombre de bandera para trazabilidad (cadena)
        banderas = {}
        if "comercio.csv" in nombres:
            com = _leer_csv_sepa(z, nombres["comercio.csv"])
            if {"id_comercio", "id_bandera", "comercio_bandera_nombre"} <= set(com.columns):
                banderas = {
                    (r["id_comercio"], r["id_bandera"]): r["comercio_bandera_nombre"]
                    for _, r in com.iterrows()
                }

        # 3) Productos por chunks, filtrando a las sucursales CABA
        bloques = []
        with z.open(nombres["productos.csv"]) as f:
            for chunk in pd.read_csv(
                f, sep="|", encoding="utf-8-sig", dtype=str,
                on_bad_lines="skip", chunksize=chunksize,
            ):
                chunk = chunk[pd.to_numeric(chunk.get("id_comercio"), errors="coerce").notna()]
                if chunk.empty or not set(CLAVE_SUCURSAL) <= set(chunk.columns):
                    continue
                mask = [
                    tuple(v) in claves_caba
                    for v in chunk[CLAVE_SUCURSAL].astype(str).values
                ]
                filtrado = chunk[mask]
                if not filtrado.empty:
                    bloques.append(filtrado)

        if not bloques:
            return pd.DataFrame()
        df = pd.concat(bloques, ignore_index=True)

    # 4) Normalizar a nuestro esquema interno estándar
    out = pd.DataFrame()
    # EAN real: id_producto, pero SOLO cuando el flag productos_ean == 1.
    flag_ean = pd.to_numeric(df.get(COL_EAN_FLAG), errors="coerce").fillna(0) == 1
    out["ean"] = df[COL_ID_PRODUCTO].where(flag_ean)
    out["ean_valido"] = flag_ean.values
    out["precio"] = pd.to_numeric(df[COL_PRECIO], errors="coerce")
    out["nombre"] = df.get(COL_DESCRIPCION)
    out["marca"] = df.get(COL_MARCA)
    out["cantidad_presentacion"] = df.get(COL_CANTIDAD)
    out["unidad_presentacion"] = df.get(COL_UNIDAD)
    out["sucursal"] = df["id_sucursal"]
    out["cadena"] = [
        banderas.get((c, b), f"comercio_{c}")
        for c, b in zip(df["id_comercio"], df["id_bandera"])
    ]
    out["id_comercio"] = df["id_comercio"]
    out["provincia"] = PROVINCIA_CABA_ISO
    out["fecha"] = pd.Timestamp(fecha) if fecha else pd.NaT
    out = out.dropna(subset=["precio"])
    return out


def procesar_dia_sepa(dia: str, chunksize: int = 200_000) -> pd.DataFrame:
    """
    Obtiene el ZIP del SEPA para `dia` (ej. "Jueves") y devuelve un DataFrame
    con todos los precios de sucursales de CABA, en el esquema estándar:
    ean, ean_valido, precio, nombre, marca, cantidad_presentacion,
    unidad_presentacion, sucursal, cadena, id_comercio, provincia, fecha.
    """
    zip_bytes = _obtener_zip_dia(dia)
    if not zip_bytes:
        logger.error(f"Sin datos para '{dia}'. Devolviendo DataFrame vacío.")
        return pd.DataFrame()

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as externo:
            internos = [
                n for n in externo.namelist()
                if n.lower().endswith(".zip") and externo.getinfo(n).file_size > 0
            ]
            if not internos:
                logger.error(f"El ZIP de '{dia}' no contiene ZIPs internos de comercios")
                return pd.DataFrame()

            fecha = _fecha_interna_zip(zip_bytes)
            logger.info(f"'{dia}': {len(internos)} comercios en el dump (relevamiento {fecha})")

            resultados = []
            for i, nombre in enumerate(internos, 1):
                try:
                    contenido = externo.read(nombre)
                    df_com = _procesar_zip_comercio(contenido, Path(nombre).name, fecha, chunksize)
                    if not df_com.empty:
                        resultados.append(df_com)
                except zipfile.BadZipFile:
                    logger.warning(f"  {nombre}: ZIP interno corrupto — salteado")
                if i % 10 == 0:
                    total = sum(len(r) for r in resultados)
                    logger.info(f"  [{i}/{len(internos)}] comercios — {total:,} registros CABA hasta ahora")

        if not resultados:
            logger.warning(f"'{dia}': 0 registros de CABA encontrados")
            return pd.DataFrame()

        df_caba = pd.concat(resultados, ignore_index=True)
        sin_ean = int((~df_caba["ean_valido"]).sum())
        logger.info(
            f"'{dia}' completo: {len(df_caba):,} registros de CABA "
            f"({sin_ean:,} con código interno no-EAN, quedarán sin clasificar COICOP)"
        )
        return df_caba

    except zipfile.BadZipFile:
        logger.error(f"El archivo de '{dia}' no es un ZIP válido (¿descarga incompleta o bloqueada?)")
        return pd.DataFrame()


def ingestar_semana_completa() -> pd.DataFrame:
    """Corre procesar_dia_sepa() para los 7 días y concatena el resultado."""
    dfs = []
    for dia in config.DIAS_SEPA:
        logger.info(f"=== Procesando {dia} ===")
        df_dia = procesar_dia_sepa(dia)
        if not df_dia.empty:
            df_dia["dia_semana"] = dia
            dfs.append(df_dia)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


if __name__ == "__main__":
    df = procesar_dia_sepa(config.DIAS_SEPA[date.today().weekday() % 7])
    print(f"\nRegistros CABA obtenidos: {len(df)}")
    if not df.empty:
        print(df.head())
        print("\nCadenas encontradas en CABA:")
        print(df["cadena"].value_counts().head(15))