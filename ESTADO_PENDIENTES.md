# Estado de pendientes (julio 2026)

Actualizado 2026-09-03 — confirmado el deploy en Railway (Postgres + web +
cron de ingesta diaria) y deshabilitada la ingesta diaria por GitHub Actions
por redundante; ver secciones 5-7. Entrada original 2026-08-01: decisión de
metodología sobre el período base tras la primera corrida real de
`calcular_indice_mensual.py 2026-07`.

## -1. `PERIODO_BASE` redefinido a julio 2026 (primer mes real)

**Estado: aplicado.**

Al correr `python calcular_indice_mensual.py 2026-07` (con `PERIODO_BASE =
"2026-06"` todavía) el cálculo dio "Sin índices elementales calculados". El
mensaje de log apuntaba al diccionario COICOP, pero la causa real es otra:
junio 2026 es 100% sintético (`sembrar_desarrollo.py`, 21 EAN inventados
`9990000000001`..`21`), y julio es 100% real (SEPA) — como el merge de
`econometria.indice_jevons_por_subclase` es por EAN exacto, y ningún EAN
sintético existe en el mundo real, el cruce entre julio y esa base daba 0
filas antes incluso de mirar el diccionario. No era arreglable cargando más
EANs en `diccionario_coicop.csv`.

Decisión: julio 2026 pasa a ser la base real (`config.PERIODO_BASE =
"2026-07"`, config.py). No hay ningún mes real anterior contra el cual
comparar julio — julio ES el primer dato real, no un dato para comparar
hacia atrás. La primera variación % real (agosto vs. julio) va a salir sola
el 2/09 con `calcular_indice_mensual.yml`. Los índices sintéticos de
abril-mayo-junio ya calculados (contra la base anterior) quedan en
`indice_calculado` como históricos, marcados `sintetico_dev` en
`origen_datos` — no se borran ni se recalculan.

## 0. BUG CRÍTICO encontrado y corregido — `config.DATA_DIR` apuntaba fuera del repo

**Estado: corregido en esta entrega.**

`config.py` calculaba `DATA_DIR = os.path.join(BASE_DIR, "../data")` (con
`"../"`). Como `BASE_DIR` es la carpeta donde vive `config.py` (la raíz del
repo, donde también vive `data/`), ese `"../"` de más hacía que **todos**
los scripts (vía `config.DATA_DIR` / `config.DB_PATH`) leyeran y escribieran
en una carpeta `data/` **hermana** de la raíz del repo, no en
`<repo>/data/`.

Impacto concreto en los 4 workflows: los 4 hacen `git add data/indice_caba.sqlite ...`
relativo a la raíz del checkout — es decir, el archivo versionado con LFS.
Pero como cada corrida (en un runner efímero de GitHub Actions, o en
Windows local) escribía en la carpeta hermana en vez de `<repo>/data/`, ese
`git add` nunca veía cambios reales: probablemente por eso las corridas
mostraban "OK" (sin error) pero también es consistente con `git diff --cached`
saliendo vacío silenciosamente en más de una corrida. Esto explica por qué
es tan importante el pendiente "probar que el deploy en Railway levante con
datos" — con este bug, un deploy fresco en Railway habría arrancado con una
base sqlite nueva y vacía en vez de la real.

Fix aplicado: `DATA_DIR = os.path.join(BASE_DIR, "data")` (una línea, en
`config.py`). Verificado que ahora resuelve exactamente a `<repo>/data/`.

**Acción recomendada antes de confiar en las últimas corridas de los 4
workflows:** re-disparar cada uno manualmente (Actions → Run workflow) con
el fix aplicado y confirmar que esta vez sí generan un commit con cambios
reales en `data/indice_caba.sqlite`.

## 1. Automatizaciones — confirmadas funcionando (con el fix de arriba)

Los 4 workflows ya están commiteados en `.github/workflows/` y no requieren
corrida manual salvo para forzar algo fuera de fecha:

- **`ingesta_diaria.yml`**: todos los días 04:00 ART (07:00 UTC). Junta los
  precios reales del SEPA.
- **`calcular_indice_mensual.yml`**: día 2 de cada mes. Calcula el mes que
  acaba de cerrar (ej. 2/08 calcula julio con precios reales del scraper).
- **`actualizar_series_oficiales.yml`**: día 16 de cada mes, 09:00 UTC
  (~06:00 ART). Trae las series INDEC/GCBA nuevas.
- **`recalcular_sintetico.yml`**: manual únicamente (`workflow_dispatch`).
  Se dispara a mano desde la pestaña Actions cuando el INDEC publique un
  mes que hoy está estimado.

Corridas registradas hasta el 14–17/07: ingesta diaria OK (scheduled),
cálculo de índice mensual corrido 3 veces a mano el 14/07 (2 OK, 1 falló —
revisar el log de esa corrida si hace falta certeza, aunque la siguiente
salió bien), recálculo sintético abr-may-jun OK el 14/07 12:45 PM. Con el
bug de arriba sin corregir todavía en esas corridas, conviene no asumir que
lo commiteado ese día refleja los datos reales hasta re-correrlas.

## 2. INDEC todavía no publicó junio en la API de series

**Estado: bloqueado, no accionable hoy.**

Último dato disponible en la API de series oficiales: 2026-05. Volver a
correr `python actualizar_series_oficiales.py` (o esperar la corrida
automática del día 16) en unos días.

Cuando julio cierre (~14/08): redefinir `config.PERIODO_BASE` con datos
reales, no antes — ver el punto 1 de la versión anterior de este documento
para el detalle del procedimiento (`sembrar_desarrollo.py` +
`calcular_indice_mensual.py`, verificar `origen_datos = "real"` en
`/comparativo/evolucion/general`).

## 3. Clasificación pendiente — 208 EANs ambiguos

**Estado: no bloqueante, sigue pendiente de tiempo humano.**

`data/clasificacion_pendiente.csv` tiene 208 EANs que necesitan criterio
humano (no hay fuente pública EAN→COICOP). Seguir con
`clasificar_interactivo.py` cuando haya tiempo:

```bash
python generar_lista_clasificacion.py
python clasificar_interactivo.py
python actualizar_diccionario.py
```

## 4. Tamaño del sqlite en Git LFS

**Estado: a monitorear, sin acción todavía.**

Seguir corriendo `monitorear_tamano_lfs.py` de tanto en tanto. Si el
crecimiento (~170MB/semana reportado) se mantiene, evaluar migrar
`DATABASE_URL` a Postgres (ya soportado, es solo variable de entorno) o
podar historial de LFS.

## 5. Deploy en Railway — confirmado funcionando (actualizado 2026-09-03)

**Estado: hecho.** Deploy confirmado en el proyecto `zonal-harmony`,
environment `production`: servicio `Postgres` (con volumen), servicio web
`Precios` (API + dashboard, auto-deploy desde `main`) y servicio cron
`ingesta_diaria` (`python main.py` disparado por Cron Schedule de Railway,
con `PROXY_URL` seteada para esquivar el WAF del SEPA). Los tres están
online y la última corrida de `ingesta_diaria` fue exitosa. Detalle completo
de la configuración (no versionada como código, solo en el dashboard de
Railway) en [`DEPLOY_RAILWAY.md`](DEPLOY_RAILWAY.md).

Como consecuencia, `.github/workflows/ingesta_diaria.yml` se deshabilitó
(sigue en el repo, solo apagado desde la pestaña Actions) — ver la nota al
principio de `GITHUB_ACTIONS.md`.

## 6. Migrar el resto de los workflows a cron de Railway

**Estado: hecho para 2 de los 3 (2026-09-04), falta apagar los workflows
viejos.** `calcular_indice_mensual` y `actualizar_series_oficiales` ya no
necesitan un servicio Railway propio: se integraron directo en `main.py`
(el mismo script que corre `ingesta_diaria` a diario), gateados por un
chequeo de fecha (día 2 y día 16 respectivamente — ver
`_ejecutar_tareas_mensuales()` en `main.py` y la sección 3 de
[`DEPLOY_RAILWAY.md`](DEPLOY_RAILWAY.md) para el detalle y el motivo de
este enfoque en vez de crear servicios nuevos).

Los workflows de GitHub Actions correspondientes **siguen activos** por
ahora — no se tocaron todavía:

- `calcular_indice_mensual.yml` (runner self-hosted) — apagar una vez que
  se confirme una corrida día 2 en Railway con el fix de arriba andando.
- `actualizar_series_oficiales.yml` (`ubuntu-latest`) — apagar una vez que
  se confirme una corrida día 16 en Railway.
- `recalcular_sintetico.yml` — solo manual (`workflow_dispatch`), se usa
  pocas veces. Recomendación: dejarlo tal cual en GitHub Actions, no vale
  la pena migrarlo a un servicio de Railway (ver sección 3.3 de
  `DEPLOY_RAILWAY.md`).

Mientras no se apaguen los dos workflows migrados, las tareas van a correr
por duplicado (Railway + GitHub Actions) los días 2 y 16 — no debería
romper nada porque ambos scripts son idempotentes, pero es redundante.

## 7. Alertas de ingesta vacía — conexión eliminada (resuelto 2026-09-03)

**Estado: hecho (se sacó, no se reemplazó).** `main.py` ya no llama a
`alertas.py` (era un mecanismo pensado para la rutina diaria de Windows,
que ya no existe — la reemplazó el cron de `ingesta_diaria` en Railway).
`alertas.py` queda huérfano en el repo, sin importar desde ningún script.
La única señal de una ingesta vacía hoy es el `logger.warning(...)` de
`main.py` en el log de esa corrida en el dashboard de Railway — no hay
aviso activo. Si en algún momento se quiere una alerta de verdad (webhook a
Slack/Discord, o que el pipeline salga con código de error para que Railway
marque la corrida en rojo), las opciones evaluadas quedan documentadas en
la sección 4 de [`DEPLOY_RAILWAY.md`](DEPLOY_RAILWAY.md).
