"""
diagnostico_cobertura_coicop.py — ¿Qué subclases de la canasta ENGHo 2017-18
todavía no tienen ningún EAN clasificado+con precio real?

Contexto: el índice general no publica si la cobertura de ponderación cae
por debajo de config.COBERTURA_MINIMA (agregacion_laspeyres en
econometria.py), y aunque hoy pase el mínimo (92.7% en julio 2026), solo 10
de las subclases con ponderación tienen dato real — el resto del peso se
está renormalizando sobre menos categorías de las que existen. Antes de que
esto salga en la prensa/universidad conviene saber EXACTAMENTE qué falta:

  1. Subclases con ponderación INDEC (ponderaciones_coicop) que NO tienen
     ningún EAN clasificado+con precio real en el período — priorizar estas
     para clasificar_interactivo.py, ordenadas por cuánto peso recuperarían.
  2. Subclases clasificadas en diccionario_coicop.csv que NO tienen
     ponderación INDEC (ej. 01.1.3 Pescados y mariscos, 01.1.9 Otros
     alimentos) — clasificar EANs ahí NO mejora el índice general (el INDEC
     no publica esa ponderación, ver METODOLOGIA.md sección 3). Se informan
     aparte para no gastar tiempo humano clasificando algo que no suma.

Uso:
    python diagnostico_cobertura_coicop.py            # último período con precios
    python diagnostico_cobertura_coicop.py 2026-07     # período puntual
"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd

import config
from models import PonderacionCoicop, RegistroPrecio, SessionLocal
from transform import _canon_ean, cargar_diccionario_coicop


def _periodo_a_rango(periodo: str) -> tuple[date, date]:
    anio, mes = map(int, periodo.split("-"))
    inicio = date(anio, mes, 1)
    fin = date(anio + (mes == 12), (mes % 12) + 1, 1)
    return inicio, fin


def _ultimo_periodo_con_precios(db) -> str:
    ultima_fecha = db.query(RegistroPrecio.fecha).order_by(RegistroPrecio.fecha.desc()).first()
    if not ultima_fecha:
        raise SystemExit("No hay ningún RegistroPrecio en la base — nada para diagnosticar.")
    f = ultima_fecha[0]
    return f"{f.year:04d}-{f.month:02d}"


def main():
    periodo = sys.argv[1] if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        periodo = periodo or _ultimo_periodo_con_precios(db)
        inicio, fin = _periodo_a_rango(periodo)
        print(f"Diagnóstico de cobertura COICOP — período {periodo}\n")

        # 1) Ponderaciones reales (INDEC, GBA) cargadas.
        ponderaciones = pd.read_sql(
            db.query(PonderacionCoicop).statement, db.bind
        )
        if ponderaciones.empty:
            raise SystemExit(
                "ponderaciones_coicop está vacía — correr precios_seed_ponderaciones.py primero."
            )
        peso_total = ponderaciones["ponderacion_caba"].astype(float).sum()

        # 2) Diccionario EAN -> subclase.
        diccionario = cargar_diccionario_coicop()  # {ean_canon: subclase}
        subclase_por_ean = diccionario

        # 3) EAN con precio real en el período.
        eans_con_precio = pd.read_sql(
            db.query(RegistroPrecio.ean).filter(
                RegistroPrecio.fecha >= inicio, RegistroPrecio.fecha < fin
            ).distinct().statement,
            db.bind,
        )["ean"]
        eans_con_precio_canon = {_canon_ean(e) for e in eans_con_precio}
        eans_con_precio_canon.discard(None)

        # 4) Para cada subclase clasificada, ¿cuántos EAN clasificados tienen
        #    precio este período?
        conteo_por_subclase: dict[str, int] = {}
        for ean_canon, subclase in subclase_por_ean.items():
            if ean_canon in eans_con_precio_canon:
                conteo_por_subclase[subclase] = conteo_por_subclase.get(subclase, 0) + 1

        # 5) Cruce con ponderaciones: qué pesa y qué tiene dato.
        filas = []
        for _, p in ponderaciones.iterrows():
            sub = p["coicop_subclase"]
            n_eans = conteo_por_subclase.get(sub, 0)
            filas.append({
                "coicop_subclase": sub,
                "descripcion": p["descripcion_rubro"],
                "ponderacion_caba": float(p["ponderacion_caba"]),
                "pct_de_la_canasta": float(p["ponderacion_caba"]) / peso_total * 100 if peso_total else 0.0,
                "eans_con_precio_este_periodo": n_eans,
                "cubierta": n_eans > 0,
            })
        df = pd.DataFrame(filas).sort_values("ponderacion_caba", ascending=False)

        cubiertas = df[df["cubierta"]]
        faltantes = df[~df["cubierta"]]
        peso_cubierto = cubiertas["ponderacion_caba"].sum()
        cobertura_pct = peso_cubierto / peso_total * 100 if peso_total else 0.0

        print(f"Cobertura de ponderación total: {cobertura_pct:.1f}% "
              f"({len(cubiertas)}/{len(df)} subclases con al menos 1 EAN clasificado+con precio)\n")

        print("── Subclases CUBIERTAS (tienen dato este período) ──────────────")
        for _, r in cubiertas.iterrows():
            print(f"  [OK] {r['coicop_subclase']:<8} {r['descripcion']:<45} "
                  f"peso={r['pct_de_la_canasta']:5.1f}%  eans={r['eans_con_precio_este_periodo']}")

        print("\n── Subclases FALTANTES (prioridad de clasificación, por peso) ───")
        if faltantes.empty:
            print("  (ninguna — cobertura completa de las subclases con ponderación INDEC)")
        for _, r in faltantes.iterrows():
            print(f"  [FALTA] {r['coicop_subclase']:<8} {r['descripcion']:<45} "
                  f"peso={r['pct_de_la_canasta']:5.1f}%  <- clasificar EANs de esta subclase "
                  f"en clasificar_interactivo.py suma esto al índice")

        # 6) Subclases clasificadas en el diccionario que NO tienen ponderación
        #    INDEC — clasificar ahí no mejora el índice general.
        subclases_con_peso = set(ponderaciones["coicop_subclase"])
        subclases_clasificadas_sin_peso = sorted(
            {s for s in subclase_por_ean.values() if s not in subclases_con_peso}
        )
        if subclases_clasificadas_sin_peso:
            print("\n── Subclases clasificadas SIN ponderación INDEC (no suman al índice general) ──")
            for s in subclases_clasificadas_sin_peso:
                n = sum(1 for v in subclase_por_ean.values() if v == s)
                print(f"  {s}: {n} EAN clasificados — el INDEC no publica ponderación para esta "
                      f"subclase (ver METODOLOGIA.md sección 3), queda fuera del índice general "
                      f"aunque tenga precio.")

        print(f"\nTotal EAN clasificados en el diccionario: {len(subclase_por_ean)}")
        print("Próximo paso sugerido: priorizar clasificación en las subclases FALTANTES de arriba "
              "(mayor peso primero) con clasificar_interactivo.py.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
