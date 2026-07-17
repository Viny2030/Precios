"""
migrar_a_postgres.py - Migra los datos de data/indice_caba.sqlite (SQLite
local) a una base Postgres nueva (ej. el addon de Railway).
"""
from __future__ import annotations

import sys

import pandas as pd
from sqlalchemy import create_engine

import config
from models import Base

TABLAS_EN_ORDEN = [
    "ponderaciones_coicop",
    "maestro_productos",
    "registro_precios",
    "serie_comparativa_indec",
    "indice_calculado",
]


def main(url_destino: str) -> None:
    origen = create_engine(config.DATABASE_URL)
    destino = create_engine(url_destino)

    print(f"Origen (sqlite):  {config.DATABASE_URL}")
    print(f"Destino (postgres): {url_destino}")
    print()

    print("Creando esquema en destino (Base.metadata.create_all)...")
    Base.metadata.create_all(bind=destino)

    total_origen = 0
    total_destino = 0

    subclases_validas = None

    for tabla in TABLAS_EN_ORDEN:
        df = pd.read_sql_table(tabla, origen)
        n_origen = len(df)
        total_origen += n_origen

        if df.empty:
            print(f"  {tabla}: 0 filas en origen - nada para copiar.")
            continue

        if tabla == "ponderaciones_coicop":
            subclases_validas = set(df["coicop_subclase"])

        if tabla == "maestro_productos" and subclases_validas is not None:
            huerfanos = df[~df["coicop_subclase"].isin(subclases_validas) & df["coicop_subclase"].notna()]
            if not huerfanos.empty:
                subclases_huerfanas = sorted(huerfanos["coicop_subclase"].unique())
                print(f"  AVISO: {len(huerfanos)} EANs con coicop_subclase que no existe en "
                      f"ponderaciones_coicop: {subclases_huerfanas}. Se migran con "
                      f"coicop_subclase=NULL - revisar si hay que sumar esas subclases "
                      f"a la canasta (ENGHo) o reclasificar esos EANs.")
                df.loc[huerfanos.index, "coicop_subclase"] = None

        df.to_sql(tabla, destino, if_exists="append", index=False)

        with destino.connect() as conn:
            n_destino = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {tabla}").scalar()
        total_destino += n_destino

        estado = "OK" if n_destino >= n_origen else "REVISAR - quedaron menos filas que en origen"
        print(f"  {tabla}: {n_origen} filas en origen -> {n_destino} filas en destino [{estado}]")

    print()
    print(f"Total filas origen (sqlite): {total_origen}")
    print("Migracion terminada. Verifica los conteos de arriba antes de cambiar "
          "el DATABASE_URL en GitHub Actions / Railway.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Uso: python migrar_a_postgres.py "postgresql://usuario:pass@host:puerto/db"')
        sys.exit(1)
    main(sys.argv[1])
