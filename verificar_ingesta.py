"""
verificar_ingesta.py — Chequeo rápido de si la ingesta diaria (cron
`ingesta_diaria` en Railway) viene funcionando, para correr a mano desde
PyCharm.

AGREGADO 2026-09-04: alternativa a mirar los logs. El CLI de Railway
(`railway logs`) no devuelve nada para `ingesta_diaria` con ninguna
combinación de flags probada (-s, -n, --since, --latest, deployment ID
directo, con el CLI en su versión más reciente) — parece una limitación
real de Railway con los Cron Jobs como recurso de primera clase, no algo
de cómo se configuró el proyecto. El dashboard web de Railway sigue
mostrando los logs bien; este script es un camino alternativo que no
depende ni del CLI ni de entrar al dashboard: se conecta directo a la
misma base que usa producción y compara la fecha más reciente con datos
contra la fecha de hoy (hora Argentina).

Para apuntar a Postgres de producción desde tu PC, seteá la variable de
entorno DATABASE_URL con la cadena PÚBLICA de conexión de Postgres
(Railway → servicio Postgres → pestaña Variables → la que suele llamarse
DATABASE_PUBLIC_URL o tener un host con dominio *.proxy.rlwy.net — la
DATABASE_URL interna que usan Precios/ingesta_diaria entre sí no es
alcanzable desde afuera de la red privada de Railway). Sin esa variable
seteada, este script revisa tu sqlite local en vez de producción — mismo
comportamiento que el resto del repo (ver config.py).

Uso:
    python verificar_ingesta.py         # últimos 7 días
    python verificar_ingesta.py 14      # últimos 14 días
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import config
from models import RegistroPrecio, SessionLocal


def _hoy_ar() -> date:
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()


def verificar(dias_atras: int = 7) -> bool:
    """Devuelve True si el último día con datos está a lo sumo 1 día de hoy."""
    hoy = _hoy_ar()
    usando_postgres = config.DATABASE_URL.startswith("postgresql://")
    print(f"Conectado a: {'Postgres' if usando_postgres else 'SQLite LOCAL — no es la base de producción, ver DATABASE_URL'}")
    print(f"Hoy (Argentina): {hoy.isoformat()}\n")

    db = SessionLocal()
    try:
        query = (
            db.query(RegistroPrecio.fecha, RegistroPrecio.ean)
            .filter(RegistroPrecio.fecha >= hoy - timedelta(days=dias_atras))
        )
        df = pd.read_sql(query.statement, db.bind)
    finally:
        db.close()

    if df.empty:
        print(f"ALERTA: no hay ningún precio cargado en los últimos {dias_atras} días.")
        return False

    por_dia = df.groupby("fecha").size().sort_index()
    print(f"Registros de precio por día (últimos {dias_atras} días):")
    for fecha, cantidad in por_dia.items():
        print(f"  {fecha} — {cantidad:,} registros")

    ultima_fecha = por_dia.index.max()
    dias_sin_datos = (hoy - ultima_fecha).days

    print()
    if dias_sin_datos >= 2:
        print(
            f"ALERTA: el último día con datos es {ultima_fecha} — hace {dias_sin_datos} días. "
            f"Puede ser el WAF del SEPA bloqueando la descarga, el proxy residencial caído, o "
            f"algo roto en 'ingesta_diaria'. Revisá el log de esa corrida en el dashboard de "
            f"Railway (railway.com → proyecto zonal-harmony → servicio ingesta_diaria → Deployments)."
        )
        return False

    print(f"OK — último día con datos: {ultima_fecha} ({dias_sin_datos} día(s) atrás, esperable).")
    return True


if __name__ == "__main__":
    dias = int(sys.argv[1]) if len(sys.argv) >= 2 else 7
    ok = verificar(dias)
    sys.exit(0 if ok else 1)
