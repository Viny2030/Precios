# Automatización vía GitHub Actions — Ingesta diaria SEPA

Reemplaza al Programador de tareas de Windows (`automatizacion.md`) por un
workflow de GitHub Actions: corre en la nube, no depende de que tu PC esté
prendido, y deja el resultado (`data/indice_caba.sqlite`,
`data/diccionario_coicop.csv`, `data/clasificacion_pendiente.csv`)
commiteado directo en el repo.

## 0. Qué se agregó / cambió en el código

- **Bug corregido en `ingesta.py`**: `config.DIAS_SEPA` tiene "Miercoles" y
  "Sabado" sin tilde, pero el catálogo CKAN publica los recursos como
  "Miércoles" y "Sábado". La comparación exacta anterior fallaba SIEMPRE
  para esos dos días (silenciosamente — no rompía el pipeline, solo no
  encontraba el recurso). Ahora la comparación ignora tildes/mayúsculas.
  Sin este fix, 2 de cada 7 días de ingesta se perdían todas las semanas.
- **`.gitignore` actualizado**: antes ignoraba `data/` entero (nunca se
  hubiera podido versionar la base). Ahora ignora todo dentro de `data/`
  EXCEPTO `indice_caba.sqlite`, `diccionario_coicop.csv` y
  `clasificacion_pendiente.csv` — que es justo lo que la Action necesita
  leer y (en el caso de la base) actualizar y commitear cada día. Los
  dumps crudos del SEPA (`data/manual/`, cientos de MB) siguen sin
  versionarse.
- **`.github/workflows/ingesta_diaria.yml`**: corre todos los días a las
  04:00 hora Argentina (07:00 UTC) — mismo horario que ya usaba
  `pipeline_diario.bat`. Instala dependencias, corre `main.py` (día de
  hoy), y si hay precios nuevos los commitea y pushea.
- **`.github/workflows/recalcular_sintetico.yml`**: solo manual. Para
  cuando el INDEC publique junio real (~14/07): re-corre
  `sembrar_desarrollo.py` + `calcular_indice_mensual.py` para abr/may/jun
  y commitea.

## 1. Subir el repo a GitHub (una sola vez)

```powershell
cd C:\Users\ASUS\PycharmProjects\Precios
git init
git add .
git commit -m "Estado inicial: pipeline SEPA + GitHub Actions"
```

Creá el repo vacío en https://github.com/new (sin README, sin .gitignore,
sin licencia — ya los tenés localmente). Después:

```powershell
git remote add origin https://github.com/<TU_USUARIO>/Precios.git
git branch -M main
git push -u origin main
```

## 2. Habilitar que la Action pueda commitear (una sola vez)

En GitHub: **Settings → Actions → General → Workflow permissions** →
marcar **"Read and write permissions"** → Save.

Sin este paso, el `git push` del workflow falla con 403 (el token por
defecto de Actions viene de solo lectura).

## 3. Backfill inicial — recuperar julio desde el 1/7

CKAN sobrescribe los recursos cada semana, así que los días que estén
disponibles HOY van a desaparecer la semana que viene. Para no perderlos:

1. Pestaña **Actions** → workflow **"Ingesta diaria SEPA"** → **Run workflow**.
2. En el campo **dias**, poné los nombres de los días que ya sean de julio
   (revisá cuáles son consultando el catálogo, o simplemente poné los 7:
   `Lunes Martes Miercoles Jueves Viernes Sabado Domingo` — los que caigan
   en junio no rompen nada, solo agregan datos reales de esos días).
3. Run workflow. Mirá el log en vivo desde la misma pestaña.

De ahí en más, la corrida automática diaria (04:00 ART) se encarga sola de
sumar el día que corresponda, sin tocar lo ya cargado.

## 4. Verificar que corre bien

- **Actions** → cada corrida muestra su log completo (mismo contenido que
  antes veías en `logs/pipeline_YYYY-MM-DD.log`).
- Si un día no hay commit nuevo: puede ser que el WAF de
  datos.produccion.gob.ar bloqueó la descarga esa vez (pasa
  intermitentemente, ver `ingesta.py`), o que ese día el recurso no tenía
  datos nuevos. No es necesariamente un error — revisá el log del run.

## 5. Cuando el INDEC publique junio real (~14/07)

Pestaña **Actions** → workflow **"Recalcular sintético abril-mayo-junio"**
→ **Run workflow**. Reemplaza la estimación de junio (2.31%) por el dato
real y recalcula los 3 índices. No toca julio en adelante.

## 6. Cambiar el horario

Editá el `cron` en `.github/workflows/ingesta_diaria.yml` (está en UTC).
Formato: `minuto hora * * *`. Ejemplo, 06:30 ART = 09:30 UTC → `"30 9 * * *"`.
