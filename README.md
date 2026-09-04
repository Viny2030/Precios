# Analizador de Precios CABA - Nueva Canasta COICOP

Este sistema automatizado realiza el *Nowcasting* y cálculo mensual del Índice de Precios de Alimentos y Bebidas para la Ciudad Autónoma de Buenos Aires (CABA). 

El motor está diseñado bajo estrictas pautas metodológicas utilizando la **Nueva Canasta de Consumo (ENGHo 2017-2018)** y la clasificación internacional **COICOP**, adelantándose al empalme oficial del INDEC.

📄 **Metodología completa (citable):** ver [`METODOLOGIA.md`](METODOLOGIA.md) — fuentes, fórmulas, período base, cobertura de la canasta y limitaciones conocidas, en un solo documento.

📊 **Manual de uso del sitio/API:** ver [`MANUAL_USO_SITIO.md`](MANUAL_USO_SITIO.md).

## ⚖️ Marco Legal y Transparencia
De acuerdo con la **Ley N° 27.275 de Derecho de Acceso a la Información Pública**, este desarrollo se nutre exclusivamente de fuentes de información oficiales, transparentes y en formatos abiertos provistas por el Ministerio de Economía de la Nación y el Portal BA Data. No utiliza datos sintéticos ni simulados (salvo abril-mayo-junio 2026, marcados explícitamente como `SINTETICO_DEV` mientras no había historial real — ver `METODOLOGIA.md`).

## 🚀 Arquitectura del Pipeline
1. **Ingesta:** Descarga diaria automatizada de los Dumps masivos (`.zip`) del SEPA (Precios Claros).
2. **Filtrado:** Procesamiento por bloques (`chunks`) en Pandas para aislar únicamente las sucursales de CABA, protegiendo el consumo de memoria RAM.
3. **Clasificación:** Mapeo taxonómico mediante códigos universales de barra (EAN/GTIN) hacia las subclases COICOP.
4. **Cálculo:** Agregación estadística utilizando la **Fórmula de Jevons** (media geométrica) para índices elementales y ponderaciones fijas de Laspeyres.

## 🗂️ Scripts principales

| Script | Qué hace | Cuándo corre |
|---|---|---|
| `main.py` | Orquesta el pipeline diario: ingesta del día → transformación → persistencia | Diario (cron `ingesta_diaria` en Railway) |
| `calcular_indice_mensual.py <YYYY-MM>` | Calcula el índice del mes indicado (Fases I/II/III, `econometria.py`) | Día 2 de cada mes (GitHub Actions, self-hosted) |
| `actualizar_series_oficiales.py` | Trae las series INDEC/GCBA nuevas para el comparativo | Día 16 de cada mes (GitHub Actions, `ubuntu-latest`) |
| `sembrar_desarrollo.py` + `recalcular_sintetico` | Re-calibra abril/mayo/junio 2026 con datos reales a medida que el INDEC los publica | Manual (`workflow_dispatch`) |
| `api.py` | API REST + dashboard (`/dashboard`, `rubros.html`) | Siempre activo (servicio web `Precios` en Railway) |
| `barrer_semana.py` | Backfill: ingesta los 7 días disponibles del catálogo CKAN de una sola pasada | Manual, para setup inicial o recuperar días antes de que CKAN los pise |
| `migrar_a_postgres.py <url>` | Migra los datos de `data/indice_caba.sqlite` a Postgres | Manual, una vez, al migrar de SQLite a Postgres |
| `verificar_ingesta.py` | Chequeo rápido OK/ALERTA: compara la fecha más reciente con datos en la base contra hoy | Manual, para controlar la ingesta diaria desde PyCharm sin entrar al dashboard de Railway — ver `DEPLOY_RAILWAY.md` §3.5 |

## 🛠️ Instalación y uso local

1. Clonar el repositorio y abrirlo en PyCharm (o el editor que prefieras).
2. Instalar las dependencias del entorno virtual:
   ```bash
   pip install -r requirements.txt
   ```
3. Correr el pipeline diario una vez (día de hoy, según `config.DIAS_SEPA`):
   ```bash
   python main.py
   ```
4. Calcular el índice de un mes ya cerrado:
   ```bash
   python calcular_indice_mensual.py 2026-08
   ```
5. Levantar la API + dashboard localmente:
   ```bash
   uvicorn api:app --reload
   ```
   Dashboard en `http://127.0.0.1:8000/dashboard`, Swagger en `http://127.0.0.1:8000/docs`.

Por defecto todo corre contra SQLite (`data/indice_caba.sqlite`). Para usar Postgres en vez de SQLite, seteá la variable de entorno `DATABASE_URL` (ver sección siguiente) — no hace falta cambiar código.

## ☁️ Despliegue actual (Railway)

En producción el proyecto corre en Railway (`zonal-harmony` / `production`), con tres servicios sobre el mismo repo:

- **`Postgres`** — base de datos administrada por Railway, con volumen persistente. Es la fuente de verdad en producción (no el `data/indice_caba.sqlite` versionado en Git, que queda como semilla/backup local).
- **`Precios`** — servicio web, auto-deploy desde `main`, corre `uvicorn api:app --host 0.0.0.0 --port $PORT` (`Procfile`). Sirve la API y el dashboard.
- **`ingesta_diaria`** — servicio de tipo cron (mismo repo, comando propio `python main.py`), dispara el pipeline diario sin necesidad de un proceso siempre prendido.

Ninguna de estas tres configuraciones (comandos de arranque, cron, variables) está en el repo como archivo `railway.json`/`railway.toml` — se hizo desde el dashboard de Railway. El detalle completo, más el plan para llevar el resto de la automatización (`calcular_indice_mensual`, `actualizar_series_oficiales`) al mismo esquema de cron en Railway, está documentado en [`DEPLOY_RAILWAY.md`](DEPLOY_RAILWAY.md).

### Variables de entorno relevantes

| Variable | Para qué sirve | Dónde se usa |
|---|---|---|
| `DATABASE_URL` | Si está seteada, se usa Postgres (`postgresql://...`) en vez de SQLite. Railway la inyecta automáticamente al conectar un servicio al plugin `Postgres`. | `config.py`, todos los scripts |
| `PROXY_URL` | Proxy residencial (`http://usuario:pass@host:puerto`) para que `ingesta.py` esquive el bloqueo por WAF de `datos.produccion.gob.ar` a IPs de datacenter/nube. Sin esto, la descarga del SEPA falla en cualquier entorno cloud (GitHub Actions o Railway). | `ingesta.py`, seteada en el servicio `ingesta_diaria` |
| `USANDO_POSTGRES` | La leen los workflows de GitHub Actions para decidir si commitear `data/indice_caba.sqlite` (solo si NO hay Postgres) | `.github/workflows/*.yml` |

## 🤖 Automatización — dónde corre cada tarea hoy

| Tarea | Dónde corre | Frecuencia | Estado |
|---|---|---|---|
| Ingesta diaria SEPA (`main.py`) | **Railway** (servicio cron `ingesta_diaria`) | Diaria | ✅ Activo. El workflow equivalente de GitHub Actions (`ingesta_diaria.yml`) está **deshabilitado** — ver [`GITHUB_ACTIONS.md`](GITHUB_ACTIONS.md) |
| Cálculo de índice mensual (`calcular_indice_mensual.py`) | GitHub Actions (runner self-hosted) | Día 2 de cada mes | ⚠️ Activo en GitHub, candidato a migrar a Railway — ver [`DEPLOY_RAILWAY.md`](DEPLOY_RAILWAY.md) §3.1 |
| Series oficiales INDEC/GCBA (`actualizar_series_oficiales.py`) | GitHub Actions (`ubuntu-latest`) | Día 16 de cada mes | ⚠️ Activo en GitHub, candidato a migrar a Railway — ver [`DEPLOY_RAILWAY.md`](DEPLOY_RAILWAY.md) §3.2 |
| Recalcular sintético abr-may-jun | GitHub Actions (`ubuntu-latest`) | Manual (`workflow_dispatch`) | ✅ Se deja como está — no amerita cron, ver [`DEPLOY_RAILWAY.md`](DEPLOY_RAILWAY.md) §3.3 |

Para el detalle histórico de por qué se armó así (bugs encontrados, fixes de horario/zona, el problema del WAF, etc.), ver [`GITHUB_ACTIONS.md`](GITHUB_ACTIONS.md), [`automatizacion.md`](automatizacion.md) (enfoque viejo en Windows, hoy en desuso) y [`ESTADO_PENDIENTES.md`](ESTADO_PENDIENTES.md).
