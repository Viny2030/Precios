# Estado de pendientes (julio 2026)

Seguimiento de los 3 puntos que no eran accionables como cambio de código
inmediato, para no perderlos de vista.

## 1. Julio no calcula contra la base sintética de junio

**Estado: bloqueado hasta que cierre julio — no accionable hoy.**

0 EANs en común entre julio y la base sintética de junio no es un problema
de datos incompletos: es esperado mientras julio siga corriendo con su
propio relevamiento y junio siga siendo sintético/de referencia.

Acción a tomar (recién cuando julio cierre completo, coincide con la corrida
automática del 2/08 — ver `.github/workflows/recalcular_sintetico.yml`):

1. Confirmar que el INDEC ya publicó julio real (día 14/08 es la fecha
   habitual de publicación — verificar que efectivamente haya salido antes
   de tocar nada).
2. Redefinir `config.PERIODO_BASE` (hoy `"2026-06"`) con el nuevo período
   base oficial y la canasta real (no sintética).
3. Correr `sembrar_desarrollo.py` + `calcular_indice_mensual.py` para
   recalcular abril–julio con la base nueva (mismo flujo que ya usa
   `recalcular_sintetico.yml`).
4. Verificar en `/comparativo/evolucion/general` que julio ya compare con
   `origen_datos = "real"` y no `"sintetico_dev"`.

No se toca `config.py` en esta entrega porque hacerlo antes de que cierre
julio dejaría el sistema calculando contra una base que todavía no existe.

## 2. Clasificación pendiente (262 EANs sin `coicop_subclase`)

**Estado: no bloqueante, sigue pendiente de tiempo humano.**

`data/clasificacion_pendiente.csv` (801 filas totales) tiene 262 filas sin
`coicop_subclase` completado:
- 208 ambiguos reales (necesitan criterio humano — no hay fuente pública
  EAN→COICOP, ver `generar_lista_clasificacion.py`).
- 54 ya marcados como no-alimento (no rompen el pipeline; `autoclasificar_resto.py`
  y `econometria.py` los ignoran correctamente).

Flujo para seguir clasificando (sin código nuevo, ya existe):

```bash
python generar_lista_clasificacion.py   # refresca la lista con los EANs más relevantes del último dump
python clasificar_interactivo.py        # clasifica desde la terminal (reanudable, salta lo ya hecho)
python actualizar_diccionario.py        # vuelca lo confirmado a data/diccionario_coicop.csv
```

## 3. Tamaño del sqlite en Git LFS

**Estado: a monitorear, sin acción todavía.**

`data/indice_caba.sqlite` se versiona vía Git LFS (`.gitattributes`) y crece
~170MB/semana según lo reportado. Se agregó `monitorear_tamano_lfs.py` —
corrida manual (o desde una Action si se quiere automatizar más adelante)
que imprime el tamaño actual del archivo y el historial de tamaños en LFS
(`git lfs ls-files -s`), con aviso si supera un umbral configurable.

Uso:
```bash
python monitorear_tamano_lfs.py
```

Si el crecimiento se mantiene, las dos salidas más razonables a evaluar más
adelante (no decididas todavía, requieren tu criterio sobre presupuesto/cuota
de LFS):
- Migrar `DATABASE_URL` a Postgres (ya soportado por `config.py` — el switch
  es solo variable de entorno) y dejar el sqlite solo para desarrollo local.
- Podar historial de LFS (`git lfs prune`) si lo que crece es el historial
  de versiones y no el archivo en sí.
