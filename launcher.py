"""RD Stems.exe: abre app.py con el entorno .venv que está junto al .exe.

La primera vez instala ese entorno con install.bat, en una ventana visible para que se vea el avance, y después
abre la app. El .exe solo lanza: PyTorch con CUDA (~3 GB) se queda en .venv, porque empaquetarlo todo daría un .exe
de varios GB que tardaría en abrir cada vez."""
import ctypes
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
pythonw = os.path.join(here, '.venv', 'Scripts', 'pythonw.exe')
stamp = os.path.join(here, '.venv', 'instalado')  # lo escribe install.bat al terminar bien


def installed():
    """Instalación completa y al día: install.bat terminó después del último cambio a lo que instala. Si se cortó a
    medias o cambió requirements.txt, se vuelve a correr (uv solo baja lo que falta)."""
    try:
        return os.path.getmtime(stamp) >= max(os.path.getmtime(os.path.join(here, f))
                                             for f in ('install.bat', 'requirements.txt'))
    except OSError:
        return False


def say(text):
    ctypes.windll.user32.MessageBoxW(None, text, 'RD Stems', 0x10)


if not os.path.exists(os.path.join(here, 'app.py')):
    say('No encuentro los archivos de RD Stems junto a este programa.\n\n'
        'Si lo abriste desde dentro del zip: clic derecho en el zip, "Extraer todo", y abre RD Stems.exe '
        'desde la carpeta extraída.')
elif not installed():
    # Primera vez, instalación cortada o requirements.txt cambió: instala (baja Python, PyTorch y las librerías; unos minutos) y abre la app al terminar
    done = subprocess.run(['cmd', '/c', os.path.join(here, 'install.bat')], cwd=here,
                          creationflags=subprocess.CREATE_NEW_CONSOLE).returncode == 0
    if done and os.path.exists(pythonw):
        subprocess.Popen([pythonw, os.path.join(here, 'app.py'), *sys.argv[1:]], cwd=here)
    else:
        say('La instalación no terminó. Revisa la ventana de instalación o corre install.bat a mano.')
else:
    subprocess.Popen([pythonw, os.path.join(here, 'app.py'), *sys.argv[1:]], cwd=here)
