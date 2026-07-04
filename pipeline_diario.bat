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
CALL "%PROYECTO%\.venv\Scripts\activate.bat"
python main.py >> "%LOGFILE%" 2>&1

echo === Fin pipeline diario %FECHA% (exit code %ERRORLEVEL%) === >> "%LOGFILE%"

ENDLOCAL