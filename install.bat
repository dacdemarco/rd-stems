@echo off
cd /d "%~dp0"
echo === RD Stems: instalacion ===

rem Todo queda dentro de esta carpeta: uv, su propio Python 3.14 y las librerias.
rem No se registra en Windows ni toca el Python que ya tengas instalado.
set "UV=%~dp0tools\uv.exe"
set "UV_PYTHON_INSTALL_DIR=%~dp0python"
set UV_PYTHON_INSTALL_REGISTRY=0
set UV_PYTHON_INSTALL_BIN=0

if exist "%UV%" goto venv
echo Descargando uv (instalador de Python y librerias)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_INSTALL_DIR='%~dp0tools'; $env:UV_NO_MODIFY_PATH='1'; irm https://astral.sh/uv/install.ps1 | iex"
if not exist "%UV%" if exist "%~dp0tools\bin\uv.exe" set "UV=%~dp0tools\bin\uv.exe"
if not exist "%UV%" goto fallo

:venv
if not exist .venv\Scripts\python.exe "%UV%" venv .venv --python 3.14 --managed-python || goto fallo

rem PyTorch segun la tarjeta de este equipo: con NVIDIA baja la version CUDA que acepta su driver; sin NVIDIA, la de CPU
rem 2.11: la version probada con esta app; sin fijarla, torchaudio queda de otra version que torch
"%UV%" pip install --python .venv "torch==2.11.*" "torchaudio==2.11.*" --torch-backend=auto || goto fallo
"%UV%" pip install --python .venv -r requirements.txt || goto fallo
rem YouTube: yt-dlp y deno (resuelve sus retos de JavaScript) siempre a la ultima, porque YouTube cambia seguido
"%UV%" pip install --python .venv -U "yt-dlp[default]" deno || goto fallo
rem --no-deps: audio-separator pide diffq y basic-pitch pide TensorFlow, que no existen para 3.14 y aqui no se usan; beat-this pide torchaudio, que ya va arriba junto a torch y del mismo indice
"%UV%" pip install --python .venv --no-deps audio-separator==0.47.0 basic-pitch==0.4.0 beat-this==1.1.0 || goto fallo
.venv\Scripts\python -c "import PySide6, sounddevice, librosa, audio_separator.separator, basic_pitch.inference, engine; hw = engine.hardware(); print('Equipo:', hw['name'], '| VRAM', round(hw['vram']), 'GB | RAM', round(hw['ram']), 'GB')" || goto fallo

rem marca de instalacion completa: sin ella (o si cambia requirements.txt) RD Stems.exe vuelve a instalar
type nul > .venv\instalado

rem ojo: en .bat el signo de porcentaje se come el texto; no usarlo dentro de python -c
rem RD Stems.exe: lanzador con el logo; la app sigue usando .venv
if exist "RD Stems.exe" goto listo
"%UV%" pip install --python .venv pyinstaller || goto fallo
.venv\Scripts\pyinstaller --noconfirm --onefile --noconsole --name "RD Stems" --icon "%~dp0assets\logo.ico" --distpath "%~dp0." --workpath build --specpath build launcher.py || goto fallo
rmdir /s /q build

:listo
echo.
echo Listo. Desde ahora RD Stems se abre con "RD Stems.exe" (si la instalacion la empezo el .exe, la app se abre al presionar una tecla).
pause
exit /b

:fallo
echo.
echo La instalacion fallo. Toma captura de lo de arriba y mandalo.
pause
exit /b 1
