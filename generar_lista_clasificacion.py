"""
generar_lista_clasificacion.py — Prepara la clasificación manual EAN→COICOP

Genera data/clasificacion_pendiente.csv con los N EANs más relevantes del
último dump de CABA (priorizados por presencia en sucursales y cadenas),
cada uno con una SUGERENCIA de subclase COICOP por palabras clave.

El trabajo humano queda reducido a: abrir el CSV, revisar la columna
`coicop_sugerido`, copiar/corregir el valor en `coicop_subclase`, y volcar
las filas confirmadas a data/diccionario_coicop.csv.

La sugerencia es solo eso — una sugerencia. La clasificación válida es la
que confirma una persona (no hay fuente pública EAN→COICOP; ver README).
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

import config
from ingesta import procesar_dia_sepa

N_TOP = 800  # cuántos EANs incluir en la lista de trabajo

# Palabras clave → subclase COICOP (División 01 Alimentos y 02 Bebidas/Tabaco).
# Se evalúan EN ORDEN: la primera que matchea gana, así que las reglas más
# específicas van antes (ej. "PAN RALLADO" antes de que "PAN" solo).
REGLAS_COICOP = [
    # 02.2.1 Tabaco
    (r"\bCIGARRILLO|\bTABACO\b", "02.2.1"),
    # 02.1 Bebidas alcohólicas
    (r"\bCERVEZA|\bVINO\b|FERNET|APERITIVO|WHISKY|VODKA|\bGIN\b|\bRON\b|SIDRA|ESPUMANTE|CHAMPA|LICOR|MALBEC|CABERNET|GINEBRA", "02.1"),
    # 01.2.1 Café, té, yerba y cacao
    (r"\bCAFE\b|CAPSULA.*CAFE|\bTE\b|\bYERBA|MATE COCIDO|\bCACAO|CHOCOLATADA|SAQUITO", "01.2.1"),
    # 01.2.2 Aguas, gaseosas y jugos
    (r"\bAGUA\b|GASEOSA|\bJUGO|COCA COLA|SPRITE|FANTA|PEPSI|\bSODA\b|ISOTONIC|ENERGIZANTE|\bPOMELO\b.*(LATA|BOT)|AMARGO.*SIN ALCOHOL", "01.2.2"),
    # 01.1.5 Aceites, grasas y manteca
    (r"\bACEITE|MANTECA|MARGARINA|\bGRASA\b", "01.1.5"),
    # 01.1.4 Leche, lácteos y huevos
    (r"\bLECHE|YOGUR|\bQUESO|CREMA DE LECHE|\bHUEVO|DULCE DE LECHE|CASANCREM|FINLANDIA|DANONINO|LECHE POLVO", "01.1.4"),
    # 01.1.2 Carnes y derivados
    (r"\bCARNE|VACUN|POLLO|CERDO|HAMBURGUES|SALCHICHA|JAMON|SALAM|MORTADELA|CHORIZO|MILANESA|BONDIOLA|\bPATY\b|NALGA|PECETO|\bASADO|MATAMBRE|CUADRIL|ROAST BEEF|PICADA ESPECIAL|SUPREMA", "01.1.2"),
    # 01.1.3 Pescados (sin ponderación propia en la tabla INDEC — ver seed)
    (r"PESCADO|\bATUN\b|MERLUZA|CABALLA|SARDINA|CAMARON|CALAMAR|SALMON", "01.1.3"),
    # 01.1.1 Pan y cereales
    (r"PAN RALLADO|\bPAN\b|GALLET|HARINA|\bARROZ\b|FIDEO|CEREAL|AVENA|TOSTADA|BIZCOCH|PREMEZCLA|ÑOQUI|TAPA.*(EMPANADA|PASCUALINA)|BUDIN|MAGDALENA|MADALENA|POLENTA|PASTA SECA|RAVIOL|LASAÑA|GRISIN|MEDIALUNAS?", "01.1.1"),
    # 01.1.7 Verduras, tubérculos y legumbres
    (r"\bPAPA\b|CEBOLLA|TOMATE|LECHUGA|ZANAHORIA|ZAPALLO|LENTEJA|ARVEJA|GARBANZO|POROTO|ACELGA|ESPINACA|MORRON|CHOCLO|BATATA|PURE DE TOMATE|VERDURA", "01.1.7"),
    # 01.1.6 Frutas
    (r"MANZANA|BANANA|NARANJA|\bPERA\b|LIMON|FRUTILLA|DURAZNO|\bUVA\b|MANDARINA|PALTA|ANANA|KIWI|CIRUELA|FRUTA", "01.1.6"),
    # 01.1.8 Azúcar, dulces, chocolate, golosinas
    (r"AZUCAR|MERMELADA|CHOCOLATE|GOLOSINA|CARAMELO|CHICLE|ALFAJOR|HELADO|\bMIEL\b|CONFITE|TURRON|GELATINA|POSTRE|BOMBON|OBLEA|PASTILLA|EDULCORANTE", "01.1.8"),
]

DESCRIPCION_SUBCLASE = {
    "01.1.1": "Pan y cereales",
    "01.1.2": "Carnes y derivados",
    "01.1.3": "Pescados y mariscos",
    "01.1.4": "Leche, productos lácteos y huevos",
    "01.1.5": "Aceites, grasas y manteca",
    "01.1.6": "Frutas",
    "01.1.7": "Verduras, tubérculos y legumbres",
    "01.1.8": "Azúcar, dulces, chocolate, golosinas, etc.",
    "01.2.1": "Café, té, yerba y cacao",
    "01.2.2": "Aguas minerales, bebidas gaseosas y jugos",
    "02.1": "Bebidas alcohólicas",
    "02.2.1": "Tabaco",
}


def sugerir_coicop(nombre: str) -> str:
    if not isinstance(nombre, str):
        return ""
    n = nombre.upper()
    for patron, subclase in REGLAS_COICOP:
        if re.search(patron, n):
            return subclase
    return ""  # no alimento/bebida reconocible — probablemente fuera del índice


def main() -> None:
    # Permite forzar un día distinto al de hoy (útil si el recurso del día
    # actual no está publicado, o para usar el caché de un día previo).
    import sys
    if len(sys.argv) > 1:
        dia = sys.argv[1]
    else:
        dia = config.DIAS_SEPA[date.today().weekday() % 7]
    print(f"Leyendo dump de '{dia}' (usa el caché local si existe)...")
    df = procesar_dia_sepa(dia)
    if df.empty:
        print("Sin datos — correr ingesta primero.")
        return

    df = df[df["ean_valido"]].copy()

    print("Agregando por EAN...")
    agg = (
        df.groupby("ean")
        .agg(
            descripcion=("nombre", lambda s: s.mode().iat[0] if not s.mode().empty else ""),
            marca=("marca", lambda s: s.mode().iat[0] if not s.mode().empty else ""),
            n_sucursales=("sucursal", "nunique"),
            n_cadenas=("cadena", "nunique"),
            precio_mediano=("precio", "median"),
        )
        .reset_index()
        .sort_values(["n_cadenas", "n_sucursales"], ascending=False)
        .head(N_TOP)
    )

    agg["coicop_sugerido"] = agg["descripcion"].map(sugerir_coicop)
    agg["rubro_sugerido"] = agg["coicop_sugerido"].map(DESCRIPCION_SUBCLASE).fillna("")
    agg["coicop_subclase"] = ""  # ← columna que completa el humano

    salida = Path(config.DATA_DIR) / "clasificacion_pendiente.csv"
    # utf-8-sig + ';' para que Excel en español lo abra bien de un doble clic
    agg.to_csv(salida, index=False, sep=";", encoding="utf-8-sig")

    con_sugerencia = int((agg["coicop_sugerido"] != "").sum())
    print(f"\nListo: {salida}")
    print(f"{len(agg)} EANs priorizados — {con_sugerencia} con sugerencia COICOP automática "
          f"({con_sugerencia/len(agg)*100:.0f}%), el resto probablemente no es alimento/bebida.")
    print("\nCómo trabajar la lista:")
    print(" 1. Abrí el CSV (Excel o PyCharm).")
    print(" 2. Revisá cada fila: si `coicop_sugerido` está bien, copialo a `coicop_subclase`;")
    print("    si está mal, escribí la subclase correcta; si el producto no es")
    print("    alimento/bebida (ej. desodorante), dejala vacía.")
    print(" 3. Las filas con `coicop_subclase` completa se vuelcan a diccionario_coicop.csv.")
    print("\nResumen de sugerencias por rubro:")
    resumen = agg[agg["rubro_sugerido"] != ""]["rubro_sugerido"].value_counts()
    print(resumen.to_string())


if __name__ == "__main__":
    main()