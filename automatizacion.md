# Automatización diaria — Ingesta SEPA

Este documento explica cómo dejar corriendo la ingesta diaria del SEPA
automáticamente en Windows.

## Qué se automatiza

El script `pipeline_diario.bat` corre todos los días `main.py`, que:
1. Descarga el dump SEPA del día de la semana actual desde CKAN.
2. Filtra a CABA y clasifica por COICOP.
3. Persiste en la base los precios de EANs que estén en el diccionario.

El log de cada corrida queda en `logs/pipeline_YYYY-MM-DD.log`.

## Configurar la tarea programada

1. Abrí **Programador de tareas** (buscar en el menú Inicio).
2. Panel derecho → **Crear tarea básica...**
3. Nombre: `Precios CABA — Ingesta diaria`. Descripción: la que quieras.
4. Desencadenador: **Diariamente**, hora **04:00 AM**.
   (04 AM porque los dumps se publican durante la madrugada y a esa hora
   ya están disponibles sin competir con horario laboral por ancho de banda.)
5. Acción: **Iniciar un programa**.
   * Programa/script: `C:\Users\ASUS\PycharmProjects\Precios\pipeline_diario.bat`
   * Iniciar en (opcional): `C:\Users\ASUS\PycharmProjects\Precios`
6. Al finalizar el asistente, marcá **"Abrir el cuadro de diálogo Propiedades
   cuando haga clic en Finalizar"** y hacé clic en Finalizar.
7. En Propiedades → pestaña **General**:
   * Marcá **"Ejecutar tanto si el usuario inició sesión como si no"**.
   * Marcá **"Ejecutar con los privilegios más altos"**.
8. En pestaña **Condiciones**:
   * Destildá "Iniciar la tarea solo si el equipo está conectado a la red de CA"
     si querés que corra también con batería.
   * Tildá "Reactivar el equipo para ejecutar esta tarea" si querés que
     encienda la PC desde suspensión (opcional).
9. En pestaña **Configuración**:
   * "Si la tarea no se ejecuta según lo programado, iniciarla lo antes posible" → SÍ.
     (Útil si la PC estaba apagada a las 4 AM.)
10. Aceptar → te va a pedir la contraseña de tu usuario de Windows.

## Verificar que quedó bien

1. En el Programador de tareas, click derecho en la tarea → **Ejecutar**.
2. Después de 1-2 minutos, revisá `logs/pipeline_YYYY-MM-DD.log`.
3. Deberías ver algo terminando con:
   ```
   Listo — N productos nuevos, M precios insertados
   === Fin pipeline diario 2026-07-04 (exit code 0) ===
   ```

## Setup inicial: correr los 6 días disponibles ahora

CKAN sobrescribe los recursos semanalmente. Los 6-7 días que están hoy
en el catálogo desaparecen la semana que viene. Para no perderlos, corré
una vez el barredor semanal:

```powershell
python barrer_semana.py
```

Esto ingesta los 7 días de una pasada. A partir de mañana, la tarea
programada se encarga de agregar el día que corresponda.

## Si ampliás el diccionario COICOP

Cuando agregues nuevas clasificaciones EAN→COICOP, corré:

```powershell
python barrer_semana.py
```

Los ZIPs cacheados en `data/manual/` se reprocesan y esta vez incluyen los
EANs recién clasificados.

## Troubleshooting

**El log dice "El servidor bloqueó la descarga automática (403 — WAF)":**
El WAF de datos.produccion.gob.ar bloquea a veces. Descargá el ZIP a mano
desde el navegador y guardalo en `data/manual/{Dia}.zip`. Corré main.py
otra vez — va a usar el ZIP local.

**El log dice "Sin datos para 'Xxx'. Devolviendo DataFrame vacío":**
El recurso puede no existir para ese día en CKAN (raro pero pasa los
domingos). No es un error real.

**La tarea no corre:**
En el Programador de tareas, click derecho → **Historial**. Si dice
"El usuario no ha iniciado sesión", volvé a Propiedades y asegurate de
que "Ejecutar tanto si el usuario inició sesión como si no" esté tildado.