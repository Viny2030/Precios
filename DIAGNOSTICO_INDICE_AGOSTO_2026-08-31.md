# Diagnóstico: por qué no hay datos de agosto (31/08/2026)

## Resumen

No existe ni un solo registro de precios posterior al **13/07/2026** en la
base (`data/indice_caba.sqlite`), ni local ni en el repo remoto de GitHub.
La ingesta diaria automática lleva **más de 7 semanas fallando en
silencio** — sin ningún error visible en Actions — y el workflow que
calcularía el índice de agosto también tiene un bug que le haría calcular
el mes equivocado incluso si hubiera datos. Se encontraron y corrigieron
2 causas raíz distintas. Falta una acción manual de tu parte para que
quede aplicada del todo (ver "Qué falta hacer vos").

## 1. Confirmado: cero datos desde el 13/07

Consulta directa sobre `data/indice_caba.sqlite`:

```
SELECT substr(fecha,1,7), COUNT(*), COUNT(DISTINCT ean)
FROM registro_precios GROUP BY 1;
→ ('2026-07', 1578976, 263)   -- única fila

SELECT MIN(fecha), MAX(fecha) FROM registro_precios;
→ ('2026-07-07', '2026-07-13')
```

Clonando el repo público desde GitHub y comparando: el sqlite remoto es
**idéntico** al local (mismo último commit que lo tocó). Y en todo el
historial de git no existe **ni un solo commit** con el mensaje
`"Ingesta SEPA ..."` que el workflow diario usa cuando sí encuentra datos
nuevos — a pesar de que ese workflow corre todos los días desde
mediados de julio. Último commit al repo en general: 16/08 (series
oficiales INDEC/GCBA, no relacionado con la ingesta).

## 2. Causa raíz #1 (la principal): el dataset de CKAN cambió de slug

`ingesta.py` primero consulta el catálogo CKAN para encontrar la URL del
ZIP del día:

```python
requests.get(config.CKAN_API_SEPA, params={"id": config.CKAN_DATASET_SEPA})
```

con `CKAN_DATASET_SEPA = "produccion-precios-claros---base-sepa"` (el
valor que vos habían verificado el 02/07 y que funcionaba entonces).
Probé exactamente esa misma llamada hoy:

```
GET https://datos.gob.ar/api/3/action/package_show?id=produccion-precios-claros---base-sepa
→ HTTP 404 {"error": {"message": "No encontrado"}}
```

Buscando en el catálogo (`package_search`) encontré que el dataset sigue
existiendo pero con **otro slug**: `precios-claros-base-sepa`. Su
`metadata_modified` es **2026-08-03**, lo que coincide con una fecha
plausible para cuando el gobierno lo renombró.

Esto explica por qué la ingesta falla **desde el primer paso, todos los
días, sin excepción**: `_descargar_zip_dia()` nunca llega siquiera a
pedirle el ZIP al servidor — el catálogo le devuelve 404 antes. Como el
código atrapa esa falla con un `except` y solo loguea un error (no
lanza excepción), `main.py` lo interpreta como "0 registros hoy" y
termina "exitosamente" — por eso Actions nunca mostró una corrida en rojo.

**Ya corregido** en `config.py` (te lo envié y ya está escrito en tu
carpeta): `CKAN_DATASET_SEPA = "precios-claros-base-sepa"`.

## 3. Un segundo problema, independiente: el WAF sigue bloqueando

Aún con el slug correcto, probé descargar el recurso real (el ZIP del
día "Lunes", ~285MB) con el mismo User-Agent que usa el código:

```
GET https://datos.produccion.gob.ar/dataset/.../resource/0a90
→ HTTP 403 (bloqueado por el WAF)
```

Esto es el comportamiento que `ingesta.py` ya documenta y maneja
("a veces" bloquea pedidos automatizados) — el código cachea en
`data/manual/` y usa ese archivo si existe. El problema es que en un
runner efímero de GitHub Actions no hay ningún ZIP pre-cacheado en
`data/manual/`, así que si el WAF bloquea ese día puntual, la corrida de
ese día se pierde igual (sin error visible, mismo mecanismo). Esto no lo
puedo arreglar desde acá — es intermitente y depende del servidor del
gobierno — pero con el slug ya corregido, al menos ahora **algunos**
días van a lograr pasar (antes era 0% de los días, garantizado).

## 4. Causa raíz #2: el workflow mensual calcularía el mes equivocado

`.github/workflows/calcular_indice_mensual.yml` corre el **día 2** de
cada mes y calculaba el período automáticamente así:

```bash
PERIODO=$(date -u -d "yesterday" +%Y-%m)
```

Eso solo da el mes anterior si corre el día 1. Corriendo el día 2,
"ayer" cae en el día 1 del **mismo** mes: el 2 de septiembre habría
calculado `"2026-09"` (mes en curso, sin cerrar) en vez de `"2026-08"`
(el mes que realmente querés cerrar). Ya lo corregí a una fórmula que da
el mes anterior sin importar qué día del mes corra:

```bash
PERIODO=$(date -u -d "$(date -u +%Y-%m-01) -1 day" +%Y-%m)
```

Verificado contra varios casos (día 1, día 2, día 15, cruce de año):
siempre da el mes calendario anterior correcto.

**Este archivo no lo pude escribir yo directamente** — GitHub Actions
workflows (`.github/workflows/*.yml`) están protegidos y no se pueden
modificar por esta vía. Te lo mandé por separado en el chat
(`calcular_indice_mensual.yml`); reemplazá el archivo actual en
`.github/workflows/` por ese.

## 5. Riesgo de tiempo: CKAN pisa los recursos cada semana

Tu propio `GITHUB_ACTIONS.md` ya lo advierte: "CKAN sobrescribe los
recursos cada semana". Si la ingesta viene fallando desde el 13/07, es
probable que gran parte de los datos crudos de julio-agosto que el SEPA
publicó día a día **ya no estén disponibles** para recuperar — cada
semana que pasó, se perdió la ventana para ese día en particular. Los
resources que vi hoy en el catálogo (Lunes..Domingo) tienen fechas de
`last_modified` de principios de julio, consistente con que el dataset
no se viene actualizando con normalidad para vos. No hay forma de
recuperar retroactivamente esos días — la prioridad ahora es que la
ingesta vuelva a andar cuanto antes para no seguir perdiendo días de
agosto.

## Qué falta hacer vos

1. **`config.py`** ya está corregido en tu carpeta (`CKAN_DATASET_SEPA`
   correcto) — solo falta que lo commitees y pushees.
2. **Reemplazar manualmente** `.github/workflows/calcular_indice_mensual.yml`
   por el archivo que te mandé en el chat (no lo pude escribir directo
   por protección de archivos de Actions).
3. En PowerShell, desde `C:\Users\ASUS\PycharmProjects\Precios`:
   ```powershell
   git add config.py .github/workflows/calcular_indice_mensual.yml
   git commit -m "Fix: slug CKAN correcto (404->ok) + fecha mes anterior en calculo mensual"
   git push
   ```
4. **Disparar la ingesta manualmente** para probar ya mismo que el fix
   funciona y capturar hoy mismo (31/08, día "Lunes") antes de que este
   recurso también se pierda: en GitHub → pestaña **Actions** → workflow
   **"Ingesta diaria SEPA"** → **Run workflow** (dejá el campo `dias`
   vacío para que corra `main.py` con el día de hoy). Revisá el log: si
   sigue sin traer nada, lo más probable es que el WAF haya bloqueado
   justo esa corrida (403 intermitente) — probá correrlo de nuevo en un
   rato.
5. Considerá correr también un backfill manual (`dias` con varios
   nombres de día a la vez) para intentar rescatar lo que todavía quede
   disponible de agosto en el catálogo, antes de que CKAN lo pise.
6. Una vez que haya datos reales de agosto, el índice de agosto (base
   julio) va a calcularse solo el **2 de septiembre** con el workflow ya
   corregido — o lo podés forzar antes vía `workflow_dispatch` con
   `periodo=2026-08` una vez que haya cobertura suficiente
   (`COBERTURA_MINIMA = 0.5`, al menos la mitad del peso de la canasta).
