"""
actualizar_diccionario.py — Vuelca la clasificación manual confirmada al
diccionario EAN→COICOP.

Lee data/clasificacion_pendiente.csv (generado por
generar_lista_clasificacion.py y completado a mano en la columna
`coicop_subclase`), valida las subclases, y agrega las filas confirmadas a
data/diccionario_coicop.csv sin duplicar ni pisar clasificaciones previas
distintas (los conflictos se informan y se respeta lo que ya estaba,
salvo que corras con --pisar).

Uso:
    python actualizar_diccionario.py           # agrega lo nuevo
    python actualizar_diccionario.py --pisar   # ante conflicto, gana el CSV nuevo
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

import config

PENDIENTE = Path(config.DATA_DIR) / "clasificacion_pendiente.csv"
DICCIONARIO = Path(config.DATA_DIR) / "diccionario_coicop.csv"

SUBCLASES_VALIDAS = {
    "01.1.1", "01.1.2", "01.1.3", "01.1.4", "01.1.5", "01.1.6", "01.1.7",
    "01.1.8", "01.1.9", "01.2.1", "01.2.2", "02.1", "02.2.1",
}


def canon_ean(valor) -> str | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    s = str(valor).strip()
    if s.endswith(".0"):
        s = s[:-2]
    digitos = re.sub(r"\D", "", s).lstrip("0")
    return digitos or None


def main() -> None:
    pisar = "--pisar" in sys.argv

    if not PENDIENTE.exists():
        print(f"No existe {PENDIENTE} — corré primero generar_lista_clasificacion.py")
        return

    # El pendiente se generó con ';' y utf-8-sig para Excel
    pend = pd.read_csv(PENDIENTE, sep=";", encoding="utf-8-sig", dtype=str)
    pend["coicop_subclase"] = pend["coicop_subclase"].fillna("").str.strip()
    confirmadas = pend[pend["coicop_subclase"] != ""].copy()

    if confirmadas.empty:
        print("No hay filas con coicop_subclase completa todavía. Nada que hacer.")
        return

    # Validar códigos de subclase
    invalidas = confirmadas[~confirmadas["coicop_subclase"].isin(SUBCLASES_VALIDAS)]
    if not invalidas.empty:
        print(f"⚠ {len(invalidas)} filas con subclase NO válida — se saltean:")
        for _, r in invalidas.head(10).iterrows():
            print(f"   EAN {r['ean']}: '{r['coicop_subclase']}' ({str(r.get('descripcion',''))[:50]})")
        confirmadas = confirmadas[confirmadas["coicop_subclase"].isin(SUBCLASES_VALIDAS)]

    confirmadas["ean_canon"] = confirmadas["ean"].map(canon_ean)
    confirmadas = confirmadas.dropna(subset=["ean_canon"]).drop_duplicates("ean_canon", keep="first")

    # Diccionario existente
    if DICCIONARIO.exists():
        dicc = pd.read_csv(DICCIONARIO, dtype=str)
    else:
        dicc = pd.DataFrame(columns=["ean", "coicop_subclase"])
    if dicc.empty:
        dicc = pd.DataFrame(columns=["ean", "coicop_subclase"])
    dicc["ean_canon"] = dicc.get("ean", pd.Series(dtype=str)).map(canon_ean)
    existentes = dict(zip(dicc["ean_canon"], dicc["coicop_subclase"]))

    nuevos, conflictos, sin_cambio = [], [], 0
    for _, r in confirmadas.iterrows():
        ean, sub = r["ean_canon"], r["coicop_subclase"]
        if ean not in existentes:
            nuevos.append({"ean": ean, "coicop_subclase": sub, "ean_canon": ean})
        elif existentes[ean] == sub:
            sin_cambio += 1
        else:
            conflictos.append((ean, existentes[ean], sub, str(r.get("descripcion", ""))[:50]))

    if conflictos:
        print(f"⚠ {len(conflictos)} conflictos (ya clasificados distinto):")
        for ean, viejo, nuevo, desc in conflictos[:10]:
            print(f"   EAN {ean}: diccionario={viejo} vs nuevo={nuevo} ({desc})")
        if pisar:
            print("   --pisar activo: gana la clasificación nueva.")
            for ean, _, nuevo, _ in conflictos:
                dicc.loc[dicc["ean_canon"] == ean, "coicop_subclase"] = nuevo
        else:
            print("   Se respeta lo que ya estaba (usá --pisar para reemplazar).")

    if nuevos:
        dicc = pd.concat([dicc, pd.DataFrame(nuevos)], ignore_index=True)

    dicc = dicc.dropna(subset=["ean_canon"]).drop_duplicates("ean_canon", keep="first")
    dicc["ean"] = dicc["ean_canon"]
    dicc[["ean", "coicop_subclase"]].to_csv(DICCIONARIO, index=False)

    print(
        f"\nListo: {len(nuevos)} EANs nuevos agregados, {sin_cambio} ya estaban igual, "
        f"{len(conflictos)} conflictos. Diccionario total: {len(dicc)} EANs → {DICCIONARIO}"
    )
    print("Ahora corré: python main.py")


if __name__ == "__main__":
    main()