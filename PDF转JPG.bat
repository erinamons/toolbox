@echo off
setlocal
title Toolbox
cd /d "%~dp0"

rem Use the interpreter that already has PyMuPDF + PySide6 installed.
set "PY=C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem No argument -> open toolbox GUI; files dropped -> convert directly.
if "%~1"=="" (
    "%PY%" "%~dp0toolbox.py"
) else (
    "%PY%" "%~dp0pdf2jpg.py" %*
)
echo.
pause
