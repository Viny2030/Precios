# Despliegue en Railway — estado actual y cómo migrar el resto de la automatización

Este documento describe la infraestructura tal como está desplegada en
Railway **hoy** (proyecto `zonal-harmony`, environment `production`). La
mayor parte de esta configuración (cron de `ingesta_diaria`, variables de
entorno, qué servicio apunta a qué comando) se hizo a mano desde el
dashboard de Railway y no vive como código versionado — así que este
documento es la referencia escrita de esa configuración. Si algo cambia en
el dashboard, actualizá este archivo en el mismo commit/PR.

> **⚠️ Encontrado 2026-09-03: existe un `railway.json` en la carpeta local
> del proyecto (`C:\Users\ASUS\PycharmProjects\Precios\railway.json`)
> pero nunca llegó a GitHub.** El `.gitignore` tiene una regla `*.json`
> (pensada para no versionar JSONs de datos/cache) que de paso ignora
> también este archivo — nunca se commiteó, así que Railway (que despliega
> desde el repo de GitHub, no desde tu disco) nunca lo vio. Ver la sección
> 1.1 para el contenido y qué se corrigió.

## 1. Qué hay desplegado hoy

Tres servicios en el mismo proyecto/environment:

| Servicio | Tipo | Fuente | Qué corre | Estado |
|---|---|---|---|---|
| `Postgres` | Base de datos (plugin de Railway) | — | Postgres administrado, con volumen persistente (`postgres-volume`) | Online, siempre arriba |
| `Precios` | Web service | GitHub `Viny2030/Precios`, rama `main`, auto-deploy en cada push | `uvicorn api:app --host 0.0.0.0 --port $PORT` (ver `Procfile` y `railway.json`) — sirve la API REST y el dashboard (`/dashboard`) | Online, siempre arriba |
| `ingesta_diaria` | Cron job | Mismo repo `Viny2030/Precios`, rama `main` | `python main.py` (pipeline diario: descarga SEPA del día, filtra CABA, clasifica COICOP, persiste — y, día 2 o día 16, también cierra el índice mensual o refresca series oficiales, ver sección 3) | Cron activo — "Last run succeeded", próxima corrida en el horario configurado |

`Precios` e `ingesta_diaria` son **dos servicios Railway separados apuntando
al mismo repo**, cada uno con su propio comando de arranque y sus propias
variables de entorno — así es como Railway permite tener un proceso web
siempre activo y un job que corre una vez al día sin pagar por un dyno
prendido 24/7 para el segundo.

### 1.1 `railway.json` — existe local, no estaba en git (corregido)

Contenido del `railway.json` que había en la carpeta local del proyecto:

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "uvicorn api:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

Es la config declarativa del servicio `Precios`: mismo `startCommand` que ya
tenía el `Procfile`, más una política de reintentos (`ON_FAILURE`, hasta 10
veces) que el `Procfile` no puede expresar. Como el archivo nunca se
commiteó, Railway nunca lo leyó — el `Procfile` sí está versionado y es
probablemente lo que Railway usó para el `startCommand`; la política de
reintentos, si está aplicada, se configuró aparte a mano en el dashboard
(Settings → Deploy → Restart Policy del servicio `Precios`), no por este
archivo.

**Se corrigió en este commit:** se agregó `!railway.json` al `.gitignore`
(excepción a la regla `*.json`, mismo patrón que ya se usa para los CSV de
`data/`) para que de acá en más sí quede versionado y Railway pueda leerlo
directo del repo si en algún momento se activa "Config as code" en el
servicio. No se tocó el resto de `.gitignore`.

### Por qué `ingesta_diaria` corre en Railway y no en GitHub Actions

El workflow `.github/workflows/ingesta_diaria.yml` quedó **deshabilitado**
(2026-09, vía el toggle de GitHub Actions, no se borró el archivo). Motivo:

- El WAF de `datos.produccion.gob.ar` bloquea las descargas del SEPA desde
  cualquier IP de datacenter/nube — confirmado que bloquea tanto
  `ubuntu-latest` de GitHub Actions como un cron corriendo en Railway (ver
  el comentario de `PROXY_URL` en `config.py`).
- La solución que se probó primero (commit `c66d2c5`) fue un **runner
  self-hosted instalado en la PC del proyecto**, para salir por la IP
  residencial de esa PC. Funciona, pero obliga a tener esa PC prendida y
  conectada para que la ingesta diaria no se corte.
- El commit `bf3cb1b` agregó soporte de proxy (`PROXY_URL` en `config.py` /
  `ingesta.py`): si se define esa variable con un proxy residencial,
  `ingesta.py` sale por ahí en vez de conexión directa. Con eso, la ingesta
  puede volver a correr 100% en la nube (Railway) sin depender de ninguna PC
  prendida — que es justo lo que hace hoy el servicio `ingesta_diaria`.

Por eso el workflow de GitHub quedó redundante y se deshabilitó: la misma
tarea (`python main.py`, todos los días) ahora la hace el cron de Railway,
con `PROXY_URL` seteada, sin depender del Programador de tareas de Windows
ni de un runner self-hosted. `GITHUB_ACTIONS.md` documenta el enfoque viejo
(self-hosted) por si hace falta volver atrás; llegado el caso, la variable
`PROXY_URL` también sirve ahí sin cambios de código.

## 2. Configuración del servicio `ingesta_diaria` (referencia para replicar)

En el dashboard de Railway, servicio `ingesta_diaria`:

- **Source**: GitHub → `Viny2030/Precios` → rama `main`.
- **Settings → Deploy → Custom Start Command**: `python main.py`
  (pisa el `Procfile`, que es para el servicio web).
- **Settings → Cron Schedule**: expresión cron en UTC. **Corrección
  2026-09-04:** este documento decía `0 7 * * *` (07:00 UTC / 04:00 ART,
  el horario que usaba `pipeline_diario.bat`/`ingesta_diaria.yml`), pero
  `railway status` muestra que el cron real configurado en el dashboard es
  `0 0 * * *` (medianoche UTC = 21:00 ART del día anterior) — quedó
  desactualizado respecto al dashboard. No rompe nada (`main.py` calcula
  la fecha de Argentina explícitamente, ver `_fecha_hoy_ar()`), pero si se
  quiere volver al horario de madrugada hay que cambiarlo a mano en
  Settings → Cron Schedule. Railway corre el start command una vez por
  disparo y apaga el contenedor al terminar — no queda un proceso vivo
  entre corridas.
- **Variables** (Settings → Variables), heredables o propias del servicio:
  - `DATABASE_URL` → referencia al plugin `Postgres` (Railway la inyecta
    automáticamente si conectás el servicio a la base desde la pestaña
    Variables, botón "Add Reference").
  - `PROXY_URL` → credenciales del proxy residencial (`http://usuario:pass@host:puerto`).
    Sin esto, `ingesta.py` vuelve a pegar directo y el WAF lo bloquea.
  - `USANDO_POSTGRES=true` — la usan los workflows de GitHub Actions para
    decidir si commitear `data/indice_caba.sqlite` o no; no la lee ningún
    script de Python directamente (lo que decide sqlite vs. Postgres ahí es
    la presencia de `DATABASE_URL`, ver `config.py`). Conviene seguir
    seteándola igual en Railway por si en algún momento se vuelve a correr
    alguno de estos workflows en GitHub.
- **nixpacks.toml**: instala `git-lfs` y corre `git lfs pull` antes de
  `pip install`, porque `data/indice_caba.sqlite` está versionado con Git
  LFS. Con `DATABASE_URL` apuntando a Postgres, ese sqlite del repo queda
  como semilla/backup local — no es la fuente de verdad en producción — pero
  igual hace falta bajarlo con LFS para que el build no falle.

## 3. Cómo migrar el resto de los workflows a cron de Railway

Los otros 3 workflows de `.github/workflows/` siguen corriendo hoy en
GitHub Actions. De los tres, `calcular_indice_mensual` y
`actualizar_series_oficiales` **ya están migrados** (2026-09-04) — no como
servicios Railway nuevos, sino integrados directo en `main.py`, el script
que ya corre el servicio `ingesta_diaria`. `recalcular_sintetico` sigue sin
migrar (ver 3.3, no hace falta).

### 3.1 y 3.2 `calcular_indice_mensual` y `actualizar_series_oficiales` — migrados a `main.py` (2026-09-04)

Se descartó la idea original de crear un servicio Railway nuevo por
workflow (cada uno con su propio cron). En cambio, como `ingesta_diaria`
**ya** corre todos los días (`python main.py`), se aprovechó ese mismo
disparador: `main.py` ahora llama a `calcular_indice_mensual.py` cuando la
fecha de Argentina es día 2, y a `actualizar_series_oficiales.py` cuando es
día 16 (ver `_ejecutar_tareas_mensuales()` en `main.py`). El resto de los
días esas dos ramas no hacen nada.

Por qué este enfoque en vez de servicios separados:

- Un solo servicio cron (`ingesta_diaria`) en vez de tres — menos superficie
  para configurar y monitorear en el dashboard de Railway.
- No cambia la frecuencia real de ninguna tarea: el chequeo de fecha adentro
  de Python reemplaza uno por uno a los `cron:` de cada workflow (día 2,
  08:00 UTC para el índice; día 16, 09:00 UTC para las series oficiales),
  solo que ahora el "disparador de verdad" es el cron diario único de
  Railway (`0 7 * * *`) y la fecha se filtra en código.
- `calcular_indice_mensual.py` ya traía `_mes_anterior()`, escrita
  justamente para no depender de un `sys.argv` ni de lógica de fecha en
  shell — se reusa tal cual desde `main.py`.
- Ninguna de las dos tareas necesita `PROXY_URL` ni ninguna variable nueva:
  como corren dentro del mismo proceso/servicio que la ingesta diaria,
  heredan las mismas variables (`DATABASE_URL`) que ya tiene configuradas
  `ingesta_diaria`.

**Pendiente para terminar la migración:** una vez que el cron de Railway
dispare de verdad un día 2 y un día 16 (o se fuerce un *redeploy* manual del
servicio `ingesta_diaria` en esas fechas) y se confirme en los logs que
corrió bien, deshabilitar `calcular_indice_mensual.yml` y
`actualizar_series_oficiales.yml` en GitHub Actions (mismo mecanismo que se
usó para `ingesta_diaria.yml`: toggle "Disable workflow", no borrar el
archivo). Hasta entonces, las dos vías van a correr en paralelo (Railway +
GitHub Actions self-hosted/ubuntu) — no debería romper nada, porque ambos
scripts son idempotentes (`calcular_y_guardar` hace upsert por período,
`actualizar_todas_las_series` no pisa si no hay dato nuevo), pero es
redundante y conviene no dejarlo así mucho tiempo.

### 3.3 `recalcular_sintetico` — dejarlo manual, no migrar a cron

Este workflow es `workflow_dispatch` puro (sin `schedule`) — se dispara a
mano solo cuando el INDEC publica un mes que hoy está estimado
(sintético). No tiene sentido un cron recurrente para algo que se ejecuta
unas pocas veces en la vida del proyecto.

Dos opciones si se quiere sacarlo igual de GitHub Actions:
1. **Dejarlo tal cual en GitHub Actions** (es la opción más simple: sigue
   siendo `workflow_dispatch`, no depende del WAF, no hace falta tocar
   nada) — recomendado.
2. Si se prefiere centralizar todo en Railway: crear el servicio con
   `Custom Start Command` apuntando a un script que encadene
   `sembrar_desarrollo.py` + los 3 `calcular_indice_mensual.py 2026-0{4,5,6}`,
   **sin** Cron Schedule, y dispararlo a mano desde el dashboard (⋮ del
   servicio → *Redeploy* / *Run*) las pocas veces que haga falta.

### 3.4 Después de migrar

- Actualizar la tabla de la sección 1 de este documento con los servicios
  nuevos.
- En `GITHUB_ACTIONS.md`, agregar la fecha de deshabilitación de cada
  workflow migrado (mismo formato que se usó para `ingesta_diaria.yml`).
- Revisar `ESTADO_PENDIENTES.md` — el punto sobre "automatizaciones
  confirmadas funcionando" tiene que reflejar dónde corre cada una
  (Railway vs. GitHub Actions), no asumir que las 4 siguen en GitHub.

## 3.5 Control diario sin entrar al dashboard — `railway logs` no funciona con Cron Jobs

**Hallazgo 2026-09-04:** se instaló el Railway CLI (v5.49.1) y se lo
vinculó al proyecto (`railway link` → `zonal-harmony` / `production` /
servicio `ingesta_diaria`) para poder revisar el log de la ingesta diaria
desde la terminal sin abrir el navegador. `railway logs` no devuelve nada
para este servicio con ninguna combinación de flags probada: por defecto,
con `-n`/`--lines`, con `--since 24h`, con `--latest`, ni pasando el
deployment ID directo (`railway logs <id>`). Todas devuelven vacío (solo
el warning de "Config as Code deprecated"). El dashboard web sí muestra
los logs sin problema — parece una limitación real de Railway con los
Cron Jobs como recurso de primera clase (en `railway status` aparecen en
su propia sección "Cron jobs", separados de "Services"), no un error de
configuración de este proyecto.

Mientras Railway no lo resuelva, el control diario queda así:

- **Log completo / debug puntual:** dashboard web de Railway (servicio
  `ingesta_diaria` → pestaña Deployments).
- **Chequeo rápido OK/ALERTA sin abrir el navegador:** `verificar_ingesta.py`
  (nuevo, en la raíz del repo) — se conecta directo a Postgres y compara
  la fecha más reciente con datos contra hoy. Necesita `DATABASE_URL`
  seteada en tu PC con la cadena **pública** de Postgres (Railway →
  servicio Postgres → Variables). Uso: `python verificar_ingesta.py`.

El CLI quedó igual instalado y vinculado (`railway link` ya hecho), así
que si Railway arregla esto en una versión futura, `railway logs -n 100`
debería empezar a andar sin volver a configurar nada.

## 4. Alertas de ingesta vacía — se sacó la conexión (2026-09-03)

`alertas.py` estaba pensado para uso local en Windows: escribía en
`logs/alertas_ingesta.log` (archivo en disco) y disparaba opcionalmente un
toast nativo de Windows (`win10toast`). Ninguna de las dos cosas sirve en
Railway (filesystem efímero entre corridas del cron, sin escritorio) — la
"rutina diaria" de Windows para la que se diseñó (`pipeline_diario.bat` +
Programador de tareas, ver `automatizacion.md`) ya no corre, la reemplazó el
cron de `ingesta_diaria` en Railway.

**Decisión (2026-09-03): se sacó la conexión en vez de reemplazarla.**
`main.py` ya no importa `alertas` ni llama a
`alertas.alertar_ingesta_vacia()` / `alertas.marcar_ingesta_ok()` — esas
llamadas apuntaban a un mecanismo de aviso que dejó de tener sentido. Lo
único que queda como señal de una ingesta vacía es el `logger.warning(...)`
de `main.py`, visible en el log de esa corrida puntual en el dashboard de
Railway (pestaña Deployments → logs del servicio `ingesta_diaria`) — hay
que entrar a mirarlo, no llega ningún aviso activo.

`alertas.py` queda en el repo pero **huérfano** — ningún script lo importa
ya (confirmado con `grep alertas` sobre todo el árbol de `.py`). Se dejó sin
borrar por si se retoma más adelante (por ejemplo, cambiándolo por un
webhook a Slack/Discord en vez de log+toast), pero hoy no lo ejecuta nadie.
Si se prefiere no tener código muerto en el repo, se puede borrar
directamente (`alertas.py` y la carpeta `logs/` si no la usa nada más) —
avisar para hacerlo.

Si más adelante se quiere una alerta activa de verdad, las dos rutas que se
habían evaluado siguen disponibles como referencia:

1. Webhook (Slack/Discord/email) en el lugar donde antes se llamaba a
   `alertas.alertar_ingesta_vacia()` — gateado igual que el toast viejo (si
   no hay URL de webhook seteada, se sigue comportando como hoy).
2. Que `ejecutar_pipeline_diario()` salga con código de error cuando la
   ingesta viene vacía (hoy solo loguea y hace `return`), así el propio
   panel de "Deployments" de Railway marca la corrida en rojo sin lógica
   adicional.
