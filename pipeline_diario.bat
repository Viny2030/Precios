@echo off
REM ─────────────────────────────────────────────────────────────────────
REM  pipeline_diario.bat — Ejecuta la ingesta diaria del SEPA.
REM
REM  Programado con "Programador de tareas" de Windows para correr
REM  todos los días a las 04:00 AM. Escribe log en logs\pipeline_YYYY-MM-DD.log
REM ─────────────────────────────────────────────────────────────────────

SETLOCAL

REM Ajustar esta ruta si movés el proyecto.
SET PROYECTO=C:\Users\ASUS\PycharmProjects\Precios

CD /D "%PROYECTO%"

REM Crear carpeta de logs si no existe.
IF NOT EXIST logs MKDIR logs

REM Fecha para nombre de log (formato YYYY-MM-DD, agnostico de locale).
FOR /F "tokens=2 delims==" %%I IN ('wmic os get localdatetime /value ^| find "="') DO SET DT=%%I
SET FECHA=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%

SET LOGFILE=logs\pipeline_%FECHA%.log

echo === Inicio pipeline diario %FECHA% === >> "%LOGFILE%"

REM Activar venv y correr main.py.
REM IMPORTANTE: para que esto escriba en la base de PRODUCCION (Postgres,
REM Railway) y no en un sqlite local aparte, la variable de entorno
REM DATABASE_URL tiene que estar seteada a nivel de usuario/sistema en esta
REM PC (setx DATABASE_URL "postgresql://..."). Sin eso, main.py cae al
REM sqlite local por defecto y el sitio en produccion no ve los datos nuevos.
CALL "%PROYECTO%\.venv\Scripts\activate.bat"
python main.py >> "%LOGFILE%" 2>&1

echo === Fin pipeline diario %FECHA% (exit code %ERRORLEVEL%) === >> "%LOGFILE%"

REM AGREGADO 2026-08-31: subir a git el diccionario COICOP y la lista de
REM pendientes de clasificar (los precios en si ya quedaron en Postgres de
REM produccion arriba, asi que NO hace falta subir ningun sqlite). Esto
REM reemplaza al workflow ingesta_diaria.yml de GitHub Actions, que se
REM desactivo (ver .github/workflows/ingesta_diaria.yml) porque: (a) el WAF
REM de datos.produccion.gob.ar bloquea las descargas desde IPs de la nube
REM de GitHub, y (b) esta PC esta apagada a las 4 AM, hora del cron. Con el
REM Programador de tareas de Windows (ver automatizacion.md, "iniciar la
REM tarea lo antes posible") esto corre igual apenas se prende la PC.
echo === Subiendo diccionario/clasificacion a git === >> "%LOGFILE%"
git add data\diccionario_coicop.csv data\clasificacion_pendiente.csv >> "%LOGFILE%" 2>&1
git diff --cached --quiet
IF ERRORLEVEL 1 (
    git commit -m "Ingesta SEPA %FECHA% (diccionario/clasificacion actualizados)" >> "%LOGFILE%" 2>&1
    git push >> "%LOGFILE%" 2>&1
    echo === Cambios commiteados y pusheados === >> "%LOGFILE%"
) ELSE (
    echo Sin cambios en diccionario/clasificacion para commitear. >> "%LOGFILE%"
)

ENDLOCAL