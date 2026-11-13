@echo off
cd /d "%~dp0"
title RD Stems
if not exist app.py goto nozip
if not exist .venv\Scripts\python.exe goto noinstall
.venv\Scripts\python.exe -c "import PySide6" 2>nul || goto noinstall
echo Abriendo RD Stems... no cierres esta ventana mientras uses la app.
.venv\Scripts\python.exe app.py
if errorlevel 1 goto fallo
exit /b

:nozip
echo No encuentro app.py junto a este archivo.
echo Seguramente abriste run.bat desde dentro del zip sin extraerlo.
echo Clic derecho en el zip, Extraer todo, y corre install.bat y run.bat desde la carpeta extraida.
pause
exit /b

:noinstall
echo La instalacion no esta completa o es de una version anterior de la app.
echo Corre install.bat desde esta misma carpeta y vuelve a intentar.
pause
exit /b

:fallo
echo.
echo La app se cerro con un error. Toma captura de lo de arriba y mandalo.
pause
