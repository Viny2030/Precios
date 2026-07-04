"""
autoclasificar_resto.py — Segunda pasada automática sobre los EANs que
quedaron sin clasificar tras clasificar_interactivo.py.

Aplica reglas ampliadas (mucho más agresivas que las de
generar_lista_clasificacion.py):

  * Keywords POSITIVAS: mapean descripciones a subclase COICOP.
  * Keywords NEGATIVAS: si matchean, el producto NO es alimento/bebida
    (limpieza, higiene, mascotas, papelería, etc.) — se deja sin clasificar
    para que no entre al diccionario.
  * Lo que no matchea nada → queda vacío y va a un resumen "ambiguos"
    que podés revisar aparte con clasificar_interactivo.py.

Este script solo TOCA filas con coicop_subclase vacía. Las que ya
clasificaste antes no se pisan.

Uso:
    python autoclasificar_resto.py             # aplica y muestra resumen
    python autoclasificar_resto.py --dry-run   # solo muestra qué haría
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

import config

CSV_PATH = Path(config.DATA_DIR) / "clasificacion_pendiente.csv"

# Reglas POSITIVAS: primera que matchea gana (por eso van más específicas primero).
REGLAS_POSITIVAS = [
    # 02.2.1 Tabaco
    (r"CIGARRILLO|TABACO|MARLBORO|PHILIP MORRIS|LUCKY|CAMEL|PARLIAMENT", "02.2.1"),

    # 02.1 Bebidas alcohólicas (además de las que ya cazaba el generador)
    (r"CHAMPAGNE|CHAMPA|TEQUILA|FERNET|CAMPARI|GANCIA|SMIRNOFF|BACARDI|"
     r"BRANCA|CYNAR|HESPERIDINA|APEROL|MARTINI|BAILEYS|CERVEZA|BIRRA|"
     r"HEINEKEN|QUILMES|CORONA|STELLA|BRAHMA|SCHNEIDER|LATA.*CERV|"
     r"VINO ROSADO|VINO TINTO|VINO BLANCO|\bLICOR\b", "02.1"),

    # 01.2.2 Aguas, gaseosas, jugos, isotónicas, energizantes
    (r"POWERADE|GATORADE|RED BULL|MONSTER|SPEED|BEBID.*ISOT|BEB.*ISOT|"
     r"ISOTON|ENERGIZ|SEVEN UP|7UP|SCHWEPPES|PASO.*TOROS|MIRINDA|"
     r"GASE\b|GASEOSA|LEVITE|\bSER\b|VILLAVICENCIO|BAGGIO|CEPITA|CITRIC|"
     r"NARANJADA|LIMONADA|TERMAS|GLACIAR|SODA\b|ECO DE LOS ANDES", "01.2.2"),

    # 01.2.1 Café, té, yerba, cacao
    (r"NESCAFE|NESQUIK|TARAGUI|ROSAMONTE|PLAYADITO|CBSE|CANARIAS|"
     r"CACHAMATE|LIPTON|GREEN HILLS|INFUSION|TERMOGENIC", "01.2.1"),

    # 01.1.1 Pan, cereales, pastas, masas
    (r"OBLEA|GRISSINI|MASA.*PIZZA|PREPIZZA|PIZZETTA|CROISSANT|CROISANT|"
     r"FACTURA\b|LACTAL|MULTICEREAL|INTEGRAL|SEMOLA|ÑOQU|CANELON|"
     r"TAPA.*(TARTA|EMPANADA|PASCUALINA)|PAN\b|BUDIN|FIDEO|SPAGUETTI|"
     r"SPAGHETTI|MOSTACHOL|PENNE|TIRABUZ|MUNICI|CEREAL|GRANOLA|"
     r"AVENA|MUESLI|COPOS", "01.1.1"),

    # 01.1.2 Carnes y derivados (incluye fiambres)
    (r"ALBONDIG|ARROLLADO|FIAMBRE|CHACINAD|LEBERWURST|MORCILLA|"
     r"BONDIOLA|SUPREMA|MILANESA|NUGGET|BASTON.*POLLO|CROQUETA", "01.1.2"),

    # 01.1.4 Lácteos, huevos, quesos
    (r"RICOT+A|MOZZA?RELLA|MUZZA?RELLA|PARMES|CREMOSO|TYBO|"
     r"PORT SALUT|GOUDA|GRUYERE|\bFETA\b|PROVOLONE|POSTRE\b|"
     r"FLAN\b|DULCE.*LECHE|LECHE.*COND|LECHE.*POLVO|LECHE ",  "01.1.4"),

    # 01.1.5 Aceites, grasas, manteca
    (r"OLIVA|GIRASOL|CANOLA|ROCIO.*VEG|MANTECA\b", "01.1.5"),

    # 01.1.6 Frutas (frescas + secas)
    (r"HIGO\b|DAMASCO|\bPASA\b|CIRUELA\b|FRUTOS SECOS|ARANDANO|"
     r"FRAMBUESA|MORA\b|CEREZA|SANDIA|MELON|POMELO\b|MANDARINA|"
     r"FRUTA DESH|NUEZ|ALMENDRA|CASTAÑA|MANI\b|PISTACH", "01.1.6"),

    # 01.1.7 Verduras, tubérculos, legumbres
    (r"SOJA\b|LENTEJA|ARVEJA|PORORO|CHOCLO|BROTE|GARBANZO|"
     r"CHAMPI|HONGO|CHUCRUT|PEPINILLO|ACEITUNA|ALCAPARRA|"
     r"CHOUCROUT|SUCEDAN.*CARNE", "01.1.7"),

    # 01.1.8 Golosinas, dulces, helados, chocolates
    (r"BOMBON|HELADO|CHUPETIN|CHICLE|CHICLETS|MASTICABLE|"
     r"BAZOOKA|MERMELADA|JALEA|MENTA\b|GARRAPINADA|CONFITE|"
     r"BANDA\b|OBLEA CHOC|CHOC\b", "01.1.8"),

    # 01.1.9 Otros alimentos: sal, condimentos, salsas, mayonesa
    (r"\bSAL\b|PIMIENTA|OREGANO|ESPECIA|CONDIMENT|VINAGRE|MOSTAZA|"
     r"MAYONESA|KETCHUP|SALSA|ADEREZO|ADOBO|SAZONADOR|CUBITO|"
     r"CALDO|SOPA|PROVENZAL|CHIMICHURRI|AJI MOL|LEVADURA|"
     r"POLVO.*HORNEAR|BICARBONATO|GELATINA|GELATIN|BALSA", "01.1.9"),
]

# Reglas NEGATIVAS: si matchea, marcar como NO ALIMENTO (dejamos vacío
# pero además añadimos un tag en una columna auxiliar para que no vuelva a
# aparecer en clasificar_interactivo.py si el usuario prefiere).
REGLAS_NO_ALIMENTO = re.compile(
    r"SHAMPOO|SHAMP\b|ACONDICIONADOR|CREMA.*ENJUAGUE|"
    r"DETERGENTE|LAVANDINA|DESINFECT|LIMPIA|LIMPIADOR|\bCIF\b|"
    r"ODORIZ|SUAVIZ|JABON|PASTA DENTAL|DENTIFRICO|CEPILLO|ENJUAGUE BUC|"
    r"PAÑAL|PANAL\b|PAÑUELO|PANUELO|TOALL|PAPEL HIG|ROLLO COCIN|"
    r"DESODOR|TALCO|PERFUME|COLONIA|CREMA CORPORAL|CREMA FACIAL|"
    r"CREMA MANOS|LOCION|MAQUILLAJE|LABIAL|PROTECTOR SOLAR|"
    r"ALIM.*GATO|ALIM.*PERRO|COMIDA.*(GATO|PERRO|MASCOTA)|"
    r"MASCOTA|SNACK.*(GATO|PERRO)|COLLAR|CORREA|"
    r"BOLSA\b|FILM\b|FILM PVC|PAPEL FILM|ROLLO ALUM|ALUMIN\b|"
    r"FOSFORO|VELA\b|ENCENDEDOR|NAFTA|LUBRIC|"
    r"BOMBILLA|\bTERMO\b|VAJILLA|SERVILL|MANTEL|"
    r"PILA\b|BATERIA|CARGADOR|"
    r"PRESERV|TAMPON|TOALLA FEM|PROTECTOR DIA|COPA MENSTR|"
    r"REPELE|INSECTIC|\bMATA\b|MATAMOSCAS|MATAINSECTOS|"
    r"CIGARRERA|ENCEND",
    re.IGNORECASE,
)


def clasificar_descripcion(desc: str) -> tuple[str, str]:
    """Devuelve (subclase_coicop, motivo). Si no se puede clasificar como
    alimento pero es claramente no alimento: ('', 'no_alimento').
    Si no matchea nada: ('', 'ambiguo')."""
    if not desc:
        return "", "vacio"
    desc_upper = str(desc).upper()

    # Negativas primero: si es evidentemente NO alimento, salir.
    if REGLAS_NO_ALIMENTO.search(desc_upper):
        return "", "no_alimento"

    # Positivas: primera que matchea gana.
    for patron, subclase in REGLAS_POSITIVAS:
        if re.search(patron, desc_upper):
            return subclase, "match"

    return "", "ambiguo"


def main(dry_run: bool = False):
    if not CSV_PATH.exists():
        print(f"No existe {CSV_PATH}. Corré primero: python generar_lista_clasificacion.py Jueves")
        raise SystemExit(1)

    df = pd.read_csv(CSV_PATH, sep=";", dtype={"ean": str})
    df["coicop_subclase"] = df["coicop_subclase"].fillna("").astype(str)

    pendientes = df[df["coicop_subclase"] == ""].copy()
    if pendientes.empty:
        print("Todo clasificado. Nada para hacer.")
        return

    print(f"Analizando {len(pendientes)} filas sin clasificar...\n")

    resultados = pendientes["descripcion"].fillna("").apply(clasificar_descripcion)
    pendientes["nueva_subclase"] = [r[0] for r in resultados]
    pendientes["motivo"] = [r[1] for r in resultados]

    resumen_match = pendientes[pendientes["motivo"] == "match"]["nueva_subclase"].value_counts()
    n_no_alim = (pendientes["motivo"] == "no_alimento").sum()
    n_ambiguo = (pendientes["motivo"] == "ambiguo").sum()

    print("── Resultado ────────────────────────────────────")
    print(f"  ✓ Clasificados por regla:  {len(pendientes) - n_no_alim - n_ambiguo}")
    for sub, n in resumen_match.items():
        print(f"      {sub}  →  {n}")
    print(f"  ✗ Marcados como NO alimento (limpieza, higiene, etc.): {n_no_alim}")
    print(f"  ? Quedan ambiguos (revisar aparte):                    {n_ambiguo}")

    if n_ambiguo > 0 and n_ambiguo <= 30:
        print("\nAmbiguos (para revisión manual con clasificar_interactivo.py):")
        for _, fila in pendientes[pendientes["motivo"] == "ambiguo"].head(30).iterrows():
            print(f"  · {fila['descripcion']}")

    if dry_run:
        print("\n[dry-run] No se guardó nada.")
        return

    # Aplicar sobre el df original SOLO donde encontramos una subclase.
    aplicar = pendientes[pendientes["nueva_subclase"] != ""]
    df.loc[aplicar.index, "coicop_subclase"] = aplicar["nueva_subclase"]

    df.to_csv(CSV_PATH, sep=";", index=False)
    print(f"\nGuardado {CSV_PATH}")
    print(f"Total clasificados ahora: {(df['coicop_subclase'] != '').sum()}/{len(df)}")
    print("\nPróximo paso: python actualizar_diccionario.py")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)