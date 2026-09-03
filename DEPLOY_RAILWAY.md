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
| `ingesta_diaria` | Cron job | Mismo repo `Viny2030/Precios`, rama `main` | `python main.py` (pipeline diario: descarga SEPA del día, filtra CABA, clasifica COICOP, persiste) | Cron activo — "Last run succeeded", próxima corrida en el horario configurado |

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
- **Settings → Cron Schedule**: expresión cron en UTC, equivalente al
  horario que usaba `pipeline_diario.bat`/`ingesta_diaria.yml` (04:00 ART =
  07:00 UTC → `0 7 * * *`). Railway corre el start command una vez por
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
GitHub Actions y **no están migrados todavía**. Esto es la propuesta para
llevarlos al mismo esquema que `ingesta_diaria`, sumando un servicio nuevo
por cada uno (mismo repo, distinto comando y cron):

### 3.1 `calcular_indice_mensual` → nuevo servicio cron

Hoy corre en un runner **self-hosted** (`calcular_indice_mensual.yml`), pero
a diferencia de la ingesta, este script **no descarga nada del SEPA** — solo
lee de la base y calcula (Fases I/II/III de `econometria.py`). No hay motivo
técnico para que dependa de la PC del proyecto; quedó en self-hosted "para no
mantener dos configuraciones de runner distintas" (comentario en el propio
workflow), no por el WAF. Es un buen candidato para migrar primero.

- **Add → GitHub Repo** → mismo repo `Viny2030/Precios`, rama `main`.
- **Custom Start Command**: `python calcular_indice_mensual.py` (sin
  argumento de período → sería recalcular con el mes por defecto que use el
  script; revisar si conviene envolverlo en un wrapper que calcule "mes
  calendario anterior a hoy" igual que hace hoy el paso de PowerShell del
  workflow, ya que `calcular_indice_mensual.py` solo, sin `sys.argv`,
  probablemente no resuelve el período solo — conviene un pequeño script
  Python de una línea, ej. `calcular_periodo_actual.py`, que calcule el mes
  anterior y llame a la función, para no reimplementar esa lógica en shell).
- **Cron Schedule**: día 2 de cada mes, 08:00 UTC → `0 8 2 * *` (igual al
  actual).
- **Variables**: `DATABASE_URL` (referencia a Postgres, igual que
  `ingesta_diaria`). No necesita `PROXY_URL` (no descarga nada externo).
- Una vez confirmado que corre bien un par de meses seguidos, deshabilitar
  `calcular_indice_mensual.yml` en GitHub Actions (mismo mecanismo que se
  usó para `ingesta_diaria.yml`: toggle "Disable workflow", no borrar el
  archivo, así queda como referencia y se puede reactivar sin reescribir
  nada).

### 3.2 `actualizar_series_oficiales` → nuevo servicio cron

Este ya corre en `ubuntu-latest` (nube) sin problema, porque
`apis.datos.gob.ar/series` no tiene el WAF que bloquea al SEPA. Migrarlo es
más por consolidar todo en un solo lugar (un dashboard, Railway, en vez de
dos) que por necesidad técnica.

- **Custom Start Command**: `python actualizar_series_oficiales.py`.
- **Cron Schedule**: día 16 de cada mes, 09:00 UTC → `0 9 16 * *` (igual al
  actual).
- **Variables**: `DATABASE_URL`.
- Mismo criterio: confirmar un par de corridas y después deshabilitar
  `actualizar_series_oficiales.yml` en GitHub.

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
