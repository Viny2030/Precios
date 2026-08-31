"""
alertas.py — Notificaciones cuando la ingesta diaria no trae datos.

Se agregó 2026-08-31 después de detectar que la ingesta venía fallando en
silencio desde el 13/07: main.py solo logueaba un WARNING y terminaba
"exitoso", así que nadie se enteraba sin ir a leer el log a mano. Esto le
da dos capas de aviso, pensadas para uso LOCAL (Windows, via
pipeline_diario.bat + Programador de tareas):

  1. Un registro persistente en logs/alertas_ingesta.log — siempre se
     escribe, no depende de que haya sesión de escritorio ni de tener
     ninguna librería instalada.
  2. Un toast nativo de Windows (requiere `pip install win10toast`,
     opcional) que salta en el momento aunque no estés mirando la
     consola. Si la librería no está instalada, o si esto corre en
     GitHub Actions (Linux, sin escritorio), se salta sola sin romper
     el pipeline — solo queda el registro en el log.

También lleva la cuenta de corridas vacías consecutivas, para poder
distinguir "un día raro" de "algo roto hace una semana" (que es
justamente el patrón que pasó desapercibido la última vez).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("alertas")

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
ARCHIVO_ALERTAS = LOG_DIR / "alertas_ingesta.log"
ARCHIVO_CONSECUTIVOS = LOG_DIR / "_consecutivos_vacios.txt"


def _leer_consecutivos() -> int:
    try:
        return int(ARCHIVO_CONSECUTIVOS.read_text().strip())
    except Exception:
        return 0


def _escribir_consecutivos(n: int) -> None:
    try:
        ARCHIVO_CONSECUTIVOS.write_text(str(n))
    except Exception as e:
        logger.error(f"No se pudo actualizar el contador de vacíos consecutivos: {e}")


def marcar_ingesta_ok() -> None:
    """Llamar cuando la ingesta SÍ trajo datos — resetea el contador de
    corridas vacías consecutivas."""
    _escribir_consecutivos(0)


def alertar_ingesta_vacia(dia: str, motivo: str = "") -> None:
    """
    Llamar cuando procesar_dia_sepa() devolvió 0 registros. Nunca lanza
    excepción — una falla acá no debe tumbar el pipeline principal.
    """
    consecutivos = _leer_consecutivos() + 1
    _escribir_consecutivos(consecutivos)

    ts = datetime.now().isoformat(timespec="seconds")
    linea = f"{ts} | dia={dia} | consecutivos={consecutivos} | {motivo}\n"
    try:
        with open(ARCHIVO_ALERTAS, "a", encoding="utf-8") as f:
            f.write(linea)
    except Exception as e:
        logger.error(f"No se pudo escribir logs/alertas_ingesta.log: {e}")

    titulo = "Ingesta SEPA vacia"
    cuerpo = f"'{dia}': 0 registros de CABA."
    if consecutivos >= 2:
        titulo = f"ALERTA: Ingesta SEPA vacia {consecutivos} dias seguidos"
        cuerpo += f" Van {consecutivos} corridas seguidas sin datos — revisar WAF/CKAN."

    try:
        from win10toast import ToastNotifier  # pip install win10toast
        ToastNotifier().show_toast(titulo, cuerpo, duration=15, threaded=True)
    except ImportError:
        logger.warning(
            f"{titulo}: {cuerpo}  "
            "(instalá 'pip install win10toast' para recibir esto como notificación de Windows)"
        )
    except Exception as e:
        logger.warning(f"{titulo}: {cuerpo}  (no se pudo mostrar el toast: {e})")
