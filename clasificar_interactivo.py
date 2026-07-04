"""
clasificar_interactivo.py — Clasificación de EANs desde la terminal.

Alternativa a completar clasificacion_pendiente.csv a mano en Excel.
Trabaja SOBRE ese mismo CSV: lo lee, te va preguntando, y lo guarda al final
(o cuando salís con 'q'). Reanudable: si volvés a correrlo, salta las
filas que ya tengan coicop_subclase completado.

Flujo:
  1. FASE POR LOTE: para cada rubro sugerido, muestra ejemplos y pregunta
     "¿aceptar las N filas sugeridas como <rubro>? [s/n/r]".
       s = aceptar todas (rápido)
       n = rechazar todas (dejar vacías)
       r = revisar una por una
  2. FASE INDIVIDUAL: sobre las que quedaron (rechazadas o sin sugerencia),
     para cada fila:
       [Enter] = aceptar sugerencia (si la hay)
       01.1.1  = poner ese código
       n       = dejar vacía (no es alimento/bebida)
       s       = saltar por ahora (queda pendiente para próxima corrida)
       q       = salir guardando lo hecho hasta acá

Cuando termines, corré:
    python actualizar_diccionario.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import config

CSV_PATH = Path(config.DATA_DIR) / "clasificacion_pendiente.csv"

SUBCLASES_VALIDAS = {
    "01.1.1", "01.1.2", "01.1.3", "01.1.4", "01.1.5", "01.1.6", "01.1.7",
    "01.1.8", "01.1.9", "01.2.1", "01.2.2", "02.1", "02.2.1",
}

DESCRIPCIONES = {
    "01.1.1": "Pan y cereales",
    "01.1.2": "Carnes y derivados",
    "01.1.3": "Pescados y mariscos",
    "01.1.4": "Leche, productos lácteos y huevos",
    "01.1.5": "Aceites, grasas y manteca",
    "01.1.6": "Frutas",
    "01.1.7": "Verduras, tubérculos y legumbres",
    "01.1.8": "Azúcar, dulces, chocolate, golosinas",
    "01.1.9": "Otros productos alimenticios",
    "01.2.1": "Café, té, yerba y cacao",
    "01.2.2": "Aguas, gaseosas y jugos",
    "02.1":   "Bebidas alcohólicas",
    "02.2.1": "Tabaco",
}


def cargar_csv() -> pd.DataFrame:
    if not CSV_PATH.exists():
        print(f"No existe {CSV_PATH}. Corré primero: python generar_lista_clasificacion.py Jueves")
        raise SystemExit(1)
    df = pd.read_csv(CSV_PATH, sep=";", dtype={"ean": str})
    if "coicop_subclase" not in df.columns:
        df["coicop_subclase"] = ""
    df["coicop_subclase"] = df["coicop_subclase"].fillna("").astype(str)
    df["coicop_sugerido"] = df["coicop_sugerido"].fillna("").astype(str)
    return df


def guardar_csv(df: pd.DataFrame):
    df.to_csv(CSV_PATH, sep=";", index=False)
    print(f"\nGuardado {CSV_PATH}")


def mostrar_referencia():
    print("\n── Códigos COICOP válidos ─────────────────────────────────")
    for cod, desc in DESCRIPCIONES.items():
        print(f"  {cod:<8} {desc}")
    print("──────────────────────────────────────────────────────────\n")


def fase_por_lote(df: pd.DataFrame) -> pd.DataFrame:
    """Recorre rubros sugeridos y ofrece aceptar/rechazar el lote entero."""
    pendientes = df[(df["coicop_subclase"] == "") & (df["coicop_sugerido"] != "")]
    if pendientes.empty:
        print("Fase por lote: no hay filas con sugerencia pendientes.")
        return df

    print("\n══ FASE 1/2: revisión por lote ══════════════════════════════")
    print(f"Hay {len(pendientes)} filas con sugerencia COICOP automática, "
          f"agrupadas en {pendientes['coicop_sugerido'].nunique()} rubros.\n")

    for rubro_cod, subset in pendientes.groupby("coicop_sugerido"):
        rubro_desc = DESCRIPCIONES.get(rubro_cod, rubro_cod)
        print(f"── {rubro_cod} · {rubro_desc} · {len(subset)} EANs sugeridos ──")
        for _, fila in subset.head(6).iterrows():
            desc = (str(fila["descripcion"]) or "")[:70]
            print(f"    · {desc}")
        if len(subset) > 6:
            print(f"    ... y {len(subset) - 6} más")

        while True:
            resp = input(f"  ¿Aceptar los {len(subset)} como {rubro_cod}? [s]í / [n]o / [r]evisar / [q]uit: ").strip().lower()
            if resp in ("s", "n", "r", "q", ""):
                break
            print("  Respuesta no válida.")

        if resp == "s" or resp == "":
            df.loc[subset.index, "coicop_subclase"] = rubro_cod
            print(f"  ✓ {len(subset)} filas marcadas como {rubro_cod}\n")
        elif resp == "n":
            print(f"  · lote rechazado (se quedan sin clasificar)\n")
        elif resp == "r":
            df = fase_individual(df, indices=subset.index.tolist())
        elif resp == "q":
            return df

    return df


def fase_individual(df: pd.DataFrame, indices: list | None = None) -> pd.DataFrame:
    """Revisión fila por fila. Si `indices` es None, revisa todo lo pendiente."""
    if indices is None:
        pendientes = df[df["coicop_subclase"] == ""]
        indices = pendientes.index.tolist()

    if not indices:
        return df

    print(f"\n── Revisión individual · {len(indices)} filas ─────────────────")
    print("  [Enter] aceptar sugerencia · <código> · [n] no clasificar · [s] saltar · [?] códigos · [q] salir guardando\n")

    for i, idx in enumerate(indices, 1):
        fila = df.loc[idx]
        desc = str(fila.get("descripcion") or "")
        marca = str(fila.get("marca") or "")
        sug = fila.get("coicop_sugerido") or ""
        sug_txt = f" [sug: {sug} · {DESCRIPCIONES.get(sug, '?')}]" if sug else " [sin sugerencia]"

        print(f"[{i}/{len(indices)}] {desc}")
        if marca and marca != "nan":
            print(f"         marca: {marca}")

        while True:
            resp = input(f"    {sug_txt}: ").strip()
            resp_lower = resp.lower()

            if resp_lower == "q":
                return df
            if resp_lower == "?":
                mostrar_referencia()
                continue
            if resp_lower == "s":
                break
            if resp_lower == "n":
                df.loc[idx, "coicop_subclase"] = ""
                # Marcamos con un tag especial para no re-preguntar
                # (dejamos vacío pero registramos el rechazo con un flag,
                # o si preferís: dejamos vacío y la próxima corrida vuelve a
                # preguntar. Por simplicidad, dejamos vacío y ya.)
                break
            if resp == "":  # aceptar sugerencia
                if sug and sug in SUBCLASES_VALIDAS:
                    df.loc[idx, "coicop_subclase"] = sug
                    print(f"    ✓ {sug}")
                    break
                else:
                    print("    (no hay sugerencia — poné código o 'n' para dejar sin clasificar)")
                    continue
            if resp in SUBCLASES_VALIDAS:
                df.loc[idx, "coicop_subclase"] = resp
                print(f"    ✓ {resp}")
                break
            print(f"    Código '{resp}' no válido. Usá '?' para ver la lista.")

    return df


def main():
    df = cargar_csv()
    total = len(df)
    ya_hechas = (df["coicop_subclase"] != "").sum()
    con_sug = (df["coicop_sugerido"] != "").sum()

    print(f"Total: {total} EANs · Ya clasificadas: {ya_hechas} · Con sugerencia auto: {con_sug}")

    if ya_hechas == total:
        print("¡Todo clasificado! Ya podés correr: python actualizar_diccionario.py")
        return

    try:
        df = fase_por_lote(df)

        pendientes = df[df["coicop_subclase"] == ""]
        if not pendientes.empty:
            while True:
                resp = input(f"\nQuedan {len(pendientes)} filas sin clasificar. ¿Revisar una por una? [s/n]: ").strip().lower()
                if resp in ("s", "n"):
                    break
            if resp == "s":
                df = fase_individual(df)
    finally:
        guardar_csv(df)
        clasificadas = (df["coicop_subclase"] != "").sum()
        print(f"\nEstado final: {clasificadas}/{total} EANs clasificados.")
        if clasificadas > ya_hechas:
            print("Próximo paso: python actualizar_diccionario.py")


if __name__ == "__main__":
    main()