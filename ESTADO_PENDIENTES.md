# Estado de pendientes (julio 2026)

Actualizado 2026-07-17 tras revisión de código y confirmación del estado de
las 4 automatizaciones en GitHub Actions.

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

## 5. Deploy en Railway — todavía no probado

**Estado: pendiente, ahora más importante por el bug del punto 0.**

Falta hacer el deploy en sí y confirmar que la API levante con datos
reales (no una base vacía). Con el fix de `config.DATA_DIR` aplicado, el
`nixpacks.toml` (que instala `git-lfs` y corre `git lfs pull` antes de
`pip install`) debería dejar `data/indice_caba.sqlite` real en
`<repo>/data/`, que es donde el `config.py` corregido ahora sí busca la
base. Antes de este fix, un deploy fresco habría arrancado con la base
vacía sin ningún error visible.
