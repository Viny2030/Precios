"""
barrer_semana.py — Corre el pipeline diario para los 7 días de la semana en
una sola pasada. Útil para:

  1. Setup inicial: ingestar de golpe los ~6-7 dumps disponibles en CKAN.
  2. Recuperar cobertura: si el diccionario COICOP se amplió después de un
     barrido previo, correr de nuevo re-ingresa esos EANs recién clasificados
     desde los ZIPs ya cacheados en data/manual/.

Como CKAN sobrescribe los recursos semanalmente (el recurso "Lunes" contiene
SIEMPRE el dump del último lunes), este script solo tiene sentido para el
setup y para recorridas puntuales — el flujo permanente es la tarea
programada diaria con main.py.

Uso:
    python barrer_semana.py
    python barrer_semana.py --dias Lunes Martes Miercoles   # solo algunos

Notas:
  * Cada día que falle (WAF bloqueando, sin datos) se registra pero no
    interrumpe los otros.
  * Al final imprime un resumen con qué días entraron y cuáles fallaron.
"""
from __future__ import annotations

import argparse
import logging
import sys

import config
from main import ejecutar_pipeline_diario

logger = logging.getLogger("barrer_semana")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def barrer(dias: list[str]) -> dict[str, str]:
    """Corre ejecutar_pipeline_diario para cada día. Devuelve {dia: estado}."""
    resultados: dict[str, str] = {}
    for dia in dias:
        logger.info(f"═══ Barriendo {dia} ═══")
        try:
            ejecutar_pipeline_diario(dia)
            resultados[dia] = "OK"
        except Exception as e:
            logger.error(f"Falló {dia}: {e}")
            resultados[dia] = f"ERROR: {e}"
    return resultados


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dias", nargs="+", default=None,
        help="Lista de días a barrer (por defecto: los 7 de config.DIAS_SEPA)",
    )
    args = parser.parse_args()

    dias = args.dias or list(config.DIAS_SEPA)
    logger.info(f"Iniciando barrido de {len(dias)} día(s): {', '.join(dias)}")

    resultados = barrer(dias)

    logger.info("═══ RESUMEN ═══")
    ok = [d for d, r in resultados.items() if r == "OK"]
    fallos = [(d, r) for d, r in resultados.items() if r != "OK"]
    logger.info(f"OK: {len(ok)}/{len(dias)} — {', '.join(ok) if ok else '(ninguno)'}")
    if fallos:
        logger.warning(f"Fallaron {len(fallos)}:")
        for dia, motivo in fallos:
            logger.warning(f"  {dia}: {motivo}")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()