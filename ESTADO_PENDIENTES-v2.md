# Estado de pendientes (julio 2026)

Actualizado 2026-07-17.

## 0. BUG CRÍTICO encontrado y corregido — `config.DATA_DIR` apuntaba fuera del repo

**Estado: corregido.**

`config.py` calculaba `DATA_DIR = os.path.join(BASE_DIR, "../data")` (con
`"../"` de más). Como `BASE_DIR` es la carpeta donde vive `config.py` (la
raíz del repo, junto a `data/`), todos los scripts leían/escribían en una
carpeta `data/` **hermana** de la raíz del repo, no en `<repo>/data/`. Los
4 workflows hacen `git add data/indice_caba.sqlite` relativo al checkout —
nunca veían cambios reales, probablemente por eso corrían "OK" sin
commitear nada. Fix aplicado: `DATA_DIR = os.path.join(BASE_DIR, "data")`.

## 1. Automatizaciones — confirmadas funcionando (con el fix de arriba)

Los 4 workflows están commiteados en `.github/workflows/`, no requieren
corrida manual salvo para forzar algo fuera de fecha:

- **`ingesta_diaria.yml`**: todos los días 04:00 ART. Junta precios reales del SEPA.
- **`calcular_indice_mensual.yml`**: día 2 de cada mes, calcula el mes recién cerrado.
- **`actualizar_series_oficiales.yml`**: día 16 de cada mes, trae INDEC/GCBA.
- **`recalcular_sintetico.yml`**: manual, para cuando INDEC publique un mes que hoy está estimado.

## 2. INDEC — junio ya publicado, recalibración hecha

**Estado: resuelto.**

INDEC publicó junio real (ambas series: GBA Alimentos y Nivel General
Nacional). Se corrió `sembrar_desarrollo.py` + `calcular_indice_mensual.py`
para abr/may/jun con el dato real. Julio sigue siendo el primer mes 100%
real (precios del scraper diario) — no calcula contra la base sintética de
junio por diseño, no por error. Cuando julio cierre (~14/08) y el INDEC
publique el dato real de julio, ahí sí se evalúa redefinir `config.PERIODO_BASE`.

## 3. Clasificación pendiente — 208 EANs ambiguos

**Estado: no bloqueante, pendiente de tiempo humano.**

```bash
python generar_lista_clasificacion.py
python clasificar_interactivo.py
python actualizar_diccionario.py
```

## 4. Tamaño del sqlite en Git LFS

**Estado: en vías de resolverse — ver punto 6 (migración a Postgres).**

## 5. Migración a Postgres — validada en local, falta Railway

**Estado: local OK, producción pendiente.**

Motivo: cortar de raíz el crecimiento del sqlite en LFS (~170MB/semana)
antes de que sea un problema. `config.py` ya soportaba el switch por
`DATABASE_URL` (variable de entorno) — no hizo falta tocar código de la
app para esto.

Completado:
- **`migrar_a_postgres.py`** (nuevo): copia las 5 tablas de
  `data/indice_caba.sqlite` a una Postgres de destino, en orden seguro
  para foreign keys (`ponderaciones_coicop` → `maestro_productos` →
  `registro_precios`, + 2 tablas independientes). Imprime conteos origen
  vs. destino.
- Postgres local levantado con Docker (puerto 5433 — el 5432 ya lo usaba
  otro container, `marketing_db`, en la misma máquina).
- Migración corrida contra esa base local: **1.580.921 filas migradas**,
  conteos exactos en las 5 tablas.
- API probada localmente con `DATABASE_URL` apuntando a esa Postgres —
  `/dashboard` y `/comparativo/evolucion/por-rubro` levantan igual que con
  sqlite.
- Los 4 `.yml` de `.github/workflows/` ya están preparados: se agregó
  `DATABASE_URL: ${{ secrets.DATABASE_URL }}` a nivel de job en los
  cuatro, y los pasos que commiteaban `data/indice_caba.sqlite` quedaron
  condicionados a una variable de repo `USANDO_POSTGRES` — mientras no
  exista o no sea `"true"`, siguen commiteando el sqlite exactamente como
  antes (cero riesgo mientras no se activa).

Hallazgo durante la migración (no bloqueante, anotado aparte):
- 39 EANs tenían `coicop_subclase = "01.1.9"`, valor que no existe en
  `ponderaciones_coicop` (11 filas). SQLite no valida foreign keys por
  defecto, así que esto ya pasaba antes silenciosamente — esos 39 EANs ya
  estaban excluidos del índice ponderado. Con la migración quedaron con
  `coicop_subclase = NULL` para no perder el producto. Pendiente decidir:
  ¿sumar "01.1.9" a la canasta ENGHo con ponderación real, o reclasificar
  esos EANs a una subclase existente?

Falta para cerrar este punto:
1. Crear la Postgres real en Railway (addon con un click, sin deployar la
   API todavía).
2. Correr `migrar_a_postgres.py` de nuevo apuntando a esa URL de Railway.
3. Cargar `DATABASE_URL` como secret en GitHub (Settings → Secrets and
   variables → Actions) y crear la variable de repo `USANDO_POSTGRES` =
   `true` (misma pantalla, pestaña "Variables") — sin tocar los `.yml` de nuevo.

## 6. Deploy en Railway — todavía no probado

**Estado: pendiente, depende de que cierre el punto 5.**

No mezclar con el punto 5 — son pasos secuenciales. Con Postgres migrado y
el secret/variable cargados en GitHub, se prueba el deploy completo y se
confirma que la API levanta con datos reales (no una base vacía — antes
del fix del punto 0, esto hubiera fallado silenciosamente).
