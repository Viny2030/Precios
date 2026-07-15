"""
monitorear_tamano_lfs.py — Chequeo rápido del tamaño de data/indice_caba.sqlite
en Git LFS.

Pendiente #3: el sqlite crece ~170MB por semana. Este script no automatiza
nada todavía (no hay acción "correcta" definida — depende de si conviene
podar historial, mover a Postgres, o solo seguir mirando) — es una foto
rápida para decidir con datos cuándo actuar.

Uso (parado en la raíz del repo, con git-lfs instalado):
    python monitorear_tamano_lfs.py

Qué hace:
1. Tamaño actual del archivo en disco (data/indice_caba.sqlite).
2. Tamaño total que Git LFS tiene almacenado para ese archivo a través del
   historial (`git lfs ls-files -s`) — si viene creciendo semana a semana,
   ahí se ve.
3. Umbral de aviso: si el archivo local supera UMBRAL_AVISO_MB, imprime una
   advertencia (no falla el script — es informativo).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import config

UMBRAL_AVISO_MB = 500  # ajustar según cuánto espacio de LFS gratuito quede disponible


def tamano_actual_mb() -> float:
    ruta = Path(config.DB_PATH)
    if not ruta.exists():
        print(f"No se encontró {ruta} (¿corriste 'git lfs pull'?)")
        return 0.0
    return ruta.stat().st_size / (1024 * 1024)


def tamano_historico_lfs() -> None:
    try:
        salida = subprocess.run(
            ["git", "lfs", "ls-files", "-s"], capture_output=True, text=True, check=True
        )
        print("Archivos en Git LFS:")
        print(salida.stdout.strip() or "(sin salida — ¿el repo no tiene LFS configurado acá?)")
    except FileNotFoundError:
        print("git-lfs no está instalado en este entorno — no se puede consultar el historial.")
    except subprocess.CalledProcessError as e:
        print(f"'git lfs ls-files' falló: {e.stderr}")


def main() -> None:
    mb = tamano_actual_mb()
    print(f"Tamaño actual de data/indice_caba.sqlite: {mb:.1f} MB")
    if mb >= UMBRAL_AVISO_MB:
        print(f"⚠️  Supera el umbral de aviso ({UMBRAL_AVISO_MB} MB) — "
              f"revisar plan de Git LFS (cuota de almacenamiento/ancho de banda) "
              f"y evaluar mover a Postgres si el crecimiento semanal se mantiene.")
    print()
    tamano_historico_lfs()


if __name__ == "__main__":
    main()
