"""RD Stems (Ruido Diario Stems): separador de stems y análisis de frecuencias. Interfaz en PySide6.
La estética, los temas día/noche, el splash y los componentes vienen de RD E.Sample."""
import json
import math
import random
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

if sys.stderr is None:  # pythonw / .exe sin consola; tqdm necesita dónde escribir
    sys.stderr = sys.stdout = open(os.devnull, 'w')

if os.name == 'nt':  # ffmpeg (audio-separator, pydub) es de consola: sin esto cada llamada abre una ventana negra
    _popen_init = subprocess.Popen.__init__

    def _no_window(self, *a, **k):
        k['creationflags'] = k.get('creationflags', 0) | 0x08000000  # CREATE_NO_WINDOW
        _popen_init(self, *a, **k)
    subprocess.Popen.__init__ = _no_window

import numpy as np
import soundfile as sf
from PySide6.QtCore import (QEasingCurve, QElapsedTimer, QFile, QMimeData, QObject, QPoint, QPointF, QPropertyAnimation,
                            QRectF, QSettings, QSize, QSizeF, QStandardPaths, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGradient, QIcon, QImage, QKeySequence, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap, QPolygonF, QRadialGradient, QShortcut)
from PySide6.QtWidgets import (QApplication, QInputDialog, QButtonGroup, QCheckBox, QDialog, QDoubleSpinBox, QSpinBox, QFileDialog, QFrame, QGraphicsOpacityEffect,
                               QGridLayout, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton, QScrollBar, QSizePolicy, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

import engine

# =====================================================================================
# Colores, letra y textos de la interfaz.
# Colores, tipografía y etiquetas viven aquí; ningún color fuera de esta tabla.
# =====================================================================================

THEMES = {
    'night': dict(PAPER='#070E0A', PANEL='#0D1812', INK='#35F28E', MUTED='#A8A6C2', TITLE='#DDE4C6',
                  ACCENT='#1450C8', ACTION='#2BE36F', ON_ACTION='#06120B', DATA='#6CB2EE', RULE='#145A33',
                  CONTROL='#22B865', DANGER='#FF3A2E', FRINGE=('#F2F21C', '#1CE6F2'), FRINGE_A=140,
                  SCAN=.06, GRAIN=.11, VIGNETTE=(0, 0, 0, 158),
                  SPECTRUM=('#070E0A', '#1450C8', '#6CB2EE', '#DDE4C6')),
    'day': dict(PAPER='#E2E7CF', PANEL='#ECF0DD', INK='#0A2A18', MUTED='#4B4868', TITLE='#0A2A18',
                ACCENT='#A3C3F2', ACTION='#1450C8', ON_ACTION='#EEF2DE', DATA='#1450C8', RULE='#B3C1A0',
                CONTROL='#4E7A5D', DANGER='#C21C14', FRINGE=('#B8A800', '#0090A8'), FRINGE_A=115,
                SCAN=.03, GRAIN=.075, VIGNETTE=(10, 42, 24, 51),
                SPECTRUM=('#E2E7CF', '#A3C3F2', '#1450C8', '#0A2A18')),
}
# ACCENT es solo fondo, nunca texto. Contraste AA comprobado en test_app.py.
PAPER = PANEL = INK = MUTED = TITLE = ACCENT = ACTION = ON_ACTION = DATA = RULE = CONTROL = DANGER = ''
SPECTRUM = ()
globals().update(THEMES['night'])

# Una sola letra, Departure Mono (SIL OFL 1.1), y solo a 11 o 22 px: fuera de su rejilla de píxel se ve borrosa.
MONO = 'Departure Mono'
TYPE = {'small': 11, 'big': 22}  # nombre: píxeles

TXT = dict(
    brand='RD STEMS', yt='YOUTUBE', karaoke='KARAOKE', acapella='VOZ', rhythm='RITMO',
    open='ABRIR', batch='CARPETA', show='MOSTRAR',
    separate='SEPARAR', voice='VOZ', quality='CALIDAD', max='MÁX', fast='RÁPIDA', analyze='ANALIZAR',
    empty='ABRE O SUELTA UN AUDIO', drop='SOLTAR', no_analysis='SIN ANÁLISIS', silent='VACÍO', mix='MEZCLA',
    cpu='CPU', slow='LENTO', done='LISTO', error='ERROR', failed='{} CON ERROR (error.log)',
    tab_stems='STEMS', tab_midi='MIDI',
    midi_busy='CONVIRTIENDO…', notes='{} NOTAS', hits='{} GOLPES',
    midi_none='ABRE O SUELTA UN AUDIO', load_q='¿Cargar "{}"?', load_n='¿Cargar estos {} archivos?',
    busy_now='Espera a que termine la separación.', load_folder='¿Cargar {} archivos?',
    no_more='No volver a mostrar', yes='SÍ', no='NO', ok='OK',
    sep_one='Separar con sus casillas de SEPARAR y VOZ', sep_sel='Separar los marcados (cada uno con sus casillas)',
    dl_stems='Elegir qué stems descargar', dl_stems_sel='Elegir qué stems descargar de los marcados',
    rm_song='Quitar de la lista (los archivos no se borran)', rm_song_sel='Quitar los marcados de la lista',
    not_sep='SIN SEPARAR', sep_done='{} STEMS', sep_now='SEPARANDO…', sep_wait='EN COLA',
    pick_title='DESCARGAR STEMS', pick_hint='Los VACÍO casi no tienen sonido: vienen sin marcar.',
    none='NINGUNO', download='DESCARGAR', cancel='CANCELAR', cancelled='CANCELADO', nothing='Nada que separar: marca algún stem o ANALIZAR.',
    midi_no_drums='SIN NOTAS: SEPARA CON BATERÍA 6',
    kind='TIPO', sens='SENSIBILIDAD', min_len='NOTA MÍNIMA', grid='CUANTIZAR', tempo='TEMPO', bends='PITCH BEND', strength='FUERZA', rests='SILENCIOS', meter='COMPÁS',
    here='AQUÍ', trim='SIN INTRO VACÍA', sheet='PARTITURA', sheets_done='{} PARTITURA(S) JUNTO A SU MIDI',
    keep='CONSERVAR',
    tiles='MOSAICO', rows='LISTA', multi='SELECCIONAR', all='TODO', sel='{} MARCADOS',
    no_midi='SIN MIDI', no_drums_short='USA BATERÍA 6', midi_busy_n='CONVIRTIENDO {}/{}…',
    convert_one='Convertir a MIDI', reconvert='Volver a convertir con los ajustes de abajo',
    convert_sel='Convertir los marcados que no tienen MIDI', dl_sel='Descargar el MIDI de los marcados',
    rm_sel='Eliminar los marcados', dl='Descargar este MIDI',
    rm='Eliminar este MIDI (a la papelera)', rm_audio='Eliminar este stem (a la papelera)',
    rm_opened='Quitar de la lista (el archivo no se borra)',
    rm_q='¿Eliminar?', rm_mid='{} MIDI a la papelera', rm_wav='{} stem(s) a la papelera',
    rm_list='{} quitado(s) de la lista', save_to='GUARDAR EN', always_in='SIEMPRE EN {}', always_pick='SIEMPRE EN LA CARPETA QUE ELIJA',
    trash_fail='No se pudieron mover a la papelera:\n{}',
    play_tip='Escucha la mezcla de los stems marcados en la lista (espacio). Desmarca uno para quitarlo.',
    no_audio='No hay salida de audio disponible.',
)
# Casillas de separación: clave del motor -> (etiqueta, ayuda)
STEM_KEYS = (
    ('voz', 'VOZ', ''), ('bateria', 'BATERÍA', 'Batería completa en un solo archivo.'),
    ('bateria6', 'BATERÍA 6', 'Batería en 6 piezas: bombo, tarola, toms, hihat, ride y crash.'),
    ('bajo', 'BAJO', ''), ('guitarra', 'GUITARRA', ''), ('teclado', 'TECLADO', 'Piano y teclados.'),
    ('sintetizador', 'SINTETIZADOR', 'MEGA'), ('viento', 'VIENTO', 'MEGA'), ('cuerdas', 'CUERDAS', 'MEGA'),
)
MEGA_TIP = ('Usa un modelo de 53 instrumentos (1.3 GB, se baja la primera vez).\n'
            'Es más lento y su calidad es menor que la de voz, bajo o batería.')
VOICE_KEYS = (('coros', 'COROS', 'Separa la voz principal de los coros.'),
              ('sin_reverb', 'SIN REVERB', 'Quita la reverberación de la voz.'),
              ('sin_ruido', 'SIN RUIDO', 'Quita ruido de fondo de la voz.'))
VOICE_DUPES = {'voz_principal', 'coros', 'voz_seca', 'voz_limpia'}  # ya están dentro de VOZ: no suenan por defecto
LABELS = {'voz_principal': 'VOZ PRINCIPAL', 'voz_seca': 'VOZ SIN REVERB', 'voz_limpia': 'VOZ SIN RUIDO',
          'bateria': 'BATERÍA'}
DATA_ROWS = (('TEMPO', 'tempo'), ('TONALIDAD', 'key'), ('ACORDES', 'chords'), ('PICO', 'peak'), ('RMS', 'rms'),
        ('RANGO 90%', 'range'), ('BRILLO', 'centroid'), ('DOMINANTES', 'peaks'))
EXTENSIONS = ('.wav', '.mp3', '.flac', '.m4a', '.aiff', '.aif', '.ogg', '.opus')
HZ_TICKS = (50, 100, 200, 500, 1000, 2000, 5000, 10000)



DB_OFF = -30  # el volumen más bajo del deslizador apaga el stem


def db_txt(v):
    return 'OFF' if v <= DB_OFF else f'{v:+d} DB'


def pan_txt(v):
    return 'C' if not v else f"{'I' if v < 0 else 'D'} {abs(v)}"


def hz(f):
    return f'{f / 1000:.1f}K' if f >= 1000 else f'{f:.0f}'


def qfont(kind):
    f = QFont(MONO)
    f.setPixelSize(TYPE[kind])
    f.setLetterSpacing(QFont.AbsoluteSpacing, round(TYPE[kind] * .06, 2))  # .06 em
    f.setStyleStrategy(QFont.NoAntialias)  # los píxeles de la letra caen en píxeles de la pantalla
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def style():
    return f"""
* {{ font-family: '{MONO}'; font-size: 11px; letter-spacing: .66px; color: {INK}; }}
QMainWindow, QDialog {{ background: {PAPER}; }}
QPushButton {{ background: {PAPER}; border: 1px solid {CONTROL}; border-radius: 0; padding: 0 10px; min-height: 24px; }}
QPushButton[led="true"] {{ padding-left: 14px; }}
QPushButton:hover {{ background: {PANEL}; }}
QPushButton:pressed, QPushButton:checked {{ background: {ACTION}; color: {ON_ACTION}; border-color: {ACTION}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {RULE}; }}
QFrame#panel, QFrame#display {{ background: {PANEL}; border: 1px solid {CONTROL}; }}
QPushButton#tab:checked {{ background: {ACCENT}; color: {TITLE}; border: 1px solid {TITLE}; }}
QPushButton#phone {{ background: {ACCENT}; border: 2px solid {TITLE}; }}
QPushButton#phone:hover {{ border-color: {INK}; }}
QLabel#datum {{ border: 1px solid {CONTROL}; padding: 1px 6px; }}
QFrame#rule {{ background: {RULE}; border: 0; }}
QLabel {{ background: transparent; }}
QLabel#row {{ color: {MUTED}; min-width: 74px; }}
QLabel#title {{ font-size: 22px; letter-spacing: 0; min-height: 32px; }}
QLabel#info, QLabel#value {{ color: {INK}; }}
QLabel#alert {{ background: {DANGER}; color: {PAPER}; padding: 2px 6px; }}
QListWidget {{ background: {PANEL}; border: 1px solid {CONTROL}; outline: 0; }}
QListWidget::item {{ padding: 4px 6px; border-bottom: 1px solid {RULE}; }}
QListWidget::item:selected {{ background: {ACTION}; color: {ON_ACTION}; }}
QListWidget::item:disabled {{ color: {MUTED}; padding-top: 10px; }}
QListWidget::indicator {{ width: 8px; height: 8px; border: 1px solid {CONTROL}; background: {PAPER}; margin-right: 6px; }}
QListWidget::indicator:checked {{ background: {INK}; border-color: {INK}; }}
QListWidget::indicator:selected {{ border-color: {ON_ACTION}; background: {ACTION}; }}
QListWidget::indicator:checked:selected {{ background: {ON_ACTION}; }}
QProgressBar {{ background: {PAPER}; border: 1px solid {CONTROL}; border-radius: 0; max-height: 8px; }}
QProgressBar::chunk {{ background: {ACTION}; }}
QScrollBar:vertical {{ background: {PAPER}; width: 8px; margin: 0; border: 0; }}
QScrollBar:horizontal {{ background: {PAPER}; height: 8px; margin: 0; border: 0; }}
QScrollBar::handle:horizontal {{ min-width: 24px; }}
QScrollBar::handle {{ background: {CONTROL}; border-radius: 0; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QToolTip {{ background: {PANEL}; color: {INK}; border: 1px solid {CONTROL}; padding: 4px 6px; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 8px; height: 8px; border: 1px solid {CONTROL}; background: {PAPER}; }}
QCheckBox::indicator:checked {{ background: {INK}; border-color: {INK}; }}
QLabel#dim {{ color: {MUTED}; }}
QListWidget#tiles::item {{ padding: 0; border: 1px solid {RULE}; }}
QListWidget#tiles::item:selected {{ background: {PAPER}; border: 1px solid {INK}; }}
QFrame#card {{ background: transparent; border: 0; }}
QSlider::groove:horizontal {{ height: 2px; background: {RULE}; }}
QSlider::sub-page:horizontal {{ background: {INK}; }}
QSlider::handle:horizontal {{ background: {INK}; width: 8px; margin: -7px 0; border-radius: 0; }}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{ background: {PAPER}; border: 1px solid {CONTROL}; border-radius: 0;
  padding: 2px 4px; min-height: 22px; selection-background-color: {ACTION}; selection-color: {ON_ACTION}; }}
"""


def palette():
    pal = QPalette()
    for role, c in ((QPalette.Window, PAPER), (QPalette.Base, PAPER), (QPalette.AlternateBase, PANEL),
                    (QPalette.Text, INK), (QPalette.WindowText, INK), (QPalette.ButtonText, INK),
                    (QPalette.Button, PAPER), (QPalette.Highlight, ACTION), (QPalette.HighlightedText, ON_ACTION),
                    (QPalette.ToolTipBase, PANEL), (QPalette.ToolTipText, INK), (QPalette.PlaceholderText, MUTED)):
        pal.setColor(role, QColor(c))
    return pal


def resource_path(rel):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


def load_fonts():
    folder = resource_path('assets/fonts')
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(('.otf', '.ttf')):
            QFontDatabase.addApplicationFont(os.path.join(folder, name))


def yt_dir():
    """Donde queda el audio bajado de YouTube; sus stems quedan al lado, como con cualquier canción."""
    return os.path.join(QStandardPaths.writableLocation(QStandardPaths.MusicLocation), 'RD Stems')


def fmt_time(s):
    m, s = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f'{h}:{m:02}:{s:02}' if h else f'{m:02}:{s:02}'


def settings():
    return QSettings('Ruido Diario', 'RD Stems')


def apply_theme(name):
    globals().update(THEMES[name])
    app = QApplication.instance()
    app.setFont(qfont('small'))
    app.setPalette(palette())
    app.setStyleSheet(style())


def glyph_icon(kind, size=16, color=None):
    """Íconos dibujados con QPainter: tinta normal, fondo cuando la tecla está activa, gris si está apagada."""
    icon = QIcon()
    for mode, state, color in ((QIcon.Normal, QIcon.Off, color or INK), (QIcon.Normal, QIcon.On, PAPER),
                               (QIcon.Disabled, QIcon.Off, MUTED), (QIcon.Disabled, QIcon.On, MUTED)):
        pix = QPixmap(size * 2, size * 2)
        pix.setDevicePixelRatio(2)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        c, s, mid = QColor(color), size, QPointF(size / 2, size / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        if kind == 'stop':
            p.drawRect(QRectF(s * .28, s * .28, s * .44, s * .44))
        elif kind == 'play':
            p.drawPolygon(QPolygonF([QPointF(s * .3, s * .2), QPointF(s * .8, s * .5), QPointF(s * .3, s * .8)]))
        elif kind == 'day':
            p.setPen(QPen(c, 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(mid, s * .2, s * .2)
            for k in range(8):  # rayos, como los del logo
                d = QPointF(math.cos(k * math.pi / 4), math.sin(k * math.pi / 4))
                p.drawLine(mid + d * s * .32, mid + d * s * .45)
        elif kind == 'down':  # flecha hacia una línea: descargar
            p.setPen(QPen(c, 1.5))
            p.drawLine(QPointF(s * .5, s * .16), QPointF(s * .5, s * .66))
            p.drawPolyline(QPolygonF([QPointF(s * .28, s * .44), QPointF(s * .5, s * .66), QPointF(s * .72, s * .44)]))
            p.drawLine(QPointF(s * .22, s * .84), QPointF(s * .78, s * .84))
        elif kind == 'split':  # una línea que se abre en tres: separar
            p.setPen(QPen(c, 1.5))
            top, mid = QPointF(s * .5, s * .14), QPointF(s * .5, s * .46)
            p.drawLine(top, mid)
            for x in (.2, .5, .8):
                p.drawLine(mid, QPointF(s * x, s * .86))
        elif kind == 'note':  # corchea: convertir a MIDI
            p.drawEllipse(QPointF(s * .38, s * .72), s * .16, s * .12)
            p.fillRect(QRectF(s * .5, s * .18, s * .07, s * .54), c)
            p.drawPolygon(QPolygonF([QPointF(s * .5, s * .18), QPointF(s * .8, s * .36), QPointF(s * .8, s * .48),
                                     QPointF(s * .57, s * .34)]))
        elif kind == 'x':
            p.setPen(QPen(c, 1.5))
            p.drawLine(QPointF(s * .28, s * .28), QPointF(s * .72, s * .72))
            p.drawLine(QPointF(s * .72, s * .28), QPointF(s * .28, s * .72))
        else:  # luna: un disco con la mordida en negativo
            p.drawEllipse(mid, s * .36, s * .36)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.drawEllipse(QPointF(s * .68, s * .36), s * .3, s * .3)
        p.end()
        icon.addPixmap(pix, mode, state)
    return icon


def logo_path():
    """El logo como QPainterPath, en el espacio de assets/logo.svg (1024 × 668). Lo usan la barra y el arranque."""
    d = re.search(r' d="([^"]+)"', open(resource_path('assets/logo.svg'), encoding='utf-8').read())[1]
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for poly in re.findall(r'M([^MZ]+)Z', d):  # el SVG es solo polígonos de píxeles: M, números y Z
        n = [float(v) for v in poly.split()]
        path.addPolygon(QPolygonF([QPointF(n[i], n[i + 1]) for i in range(0, len(n), 2)]))
        path.closeSubpath()
    return path


def logo_pixmap(color, height):
    """El logo teñido de un color, a esa altura (nítido en pantallas con escala)."""
    path, ratio = logo_path(), QApplication.instance().devicePixelRatio()
    box = path.boundingRect()
    k = height / box.height()
    pix = QPixmap(round(box.width() * k * ratio), round(height * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(k, k)
    p.translate(-box.topLeft())
    p.fillPath(path, QColor(color))
    p.end()
    return pix


def hatch(p, rect, color, step=6, width=2):
    """Rayado diagonal (en vez de transparencias) para marcar lo que no cuenta."""
    p.save()
    p.setClipRect(rect)
    p.setPen(QPen(QColor(color), width))
    for x in range(int(rect.left() - rect.height()), int(rect.right()) + step, step):
        p.drawLine(QPointF(x, rect.bottom()), QPointF(x + rect.height(), rect.top()))
    p.restore()


class Title(QLabel):
    """Título a 22 px con borde de color: una copia amarilla 1 px a la izquierda y una cian 1 px a la
    derecha, debajo del texto."""

    def __init__(self, text=''):
        super().__init__(text)
        self.setObjectName('title')  # 22 px: la hoja de estilos manda sobre setFont

    def paintEvent(self, e):
        p = QPainter(self)
        p.setFont(self.font())
        r = self.contentsRect()
        for dx, color in ((-1, FRINGE[0]), (1, FRINGE[1])):
            c = QColor(color)
            c.setAlpha(FRINGE_A)
            p.setPen(c)
            p.drawText(r.translated(dx, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.setPen(QColor(TITLE))
        p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, self.text())


class TitleRule(QWidget):
    """Bajo la barra superior: una regla gruesa roja y una fina verde."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(6)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(0, 0, self.width(), 3, QColor(DANGER))
        p.fillRect(0, 5, self.width(), 1, QColor(CONTROL))


class Progress(QProgressBar):
    """Barra de progreso: marco y relleno lavanda y, debajo, una regla graduada cada 10%. Sin rango
    (0, 0) un bloque va y viene mientras trabaja."""

    def __init__(self):
        super().__init__()
        self.setTextVisible(False)
        self.setFixedHeight(16)
        self.tick = QTimer(self, interval=60, timeout=lambda: self.maximum() == self.minimum() and self.update())
        self.tick.start()

    def paintEvent(self, e):
        p = QPainter(self)
        w, lav = self.width(), QColor(MUTED)
        p.setPen(QPen(lav, 1))
        p.drawRect(QRectF(0.5, 0.5, w - 1, 9))
        inner = QRectF(3, 3, w - 6, 4)
        if self.maximum() > self.minimum():
            f = max(0.0, (self.value() - self.minimum()) / (self.maximum() - self.minimum()))
            p.fillRect(QRectF(inner.x(), inner.y(), inner.width() * f, inner.height()), lav)
        else:
            k = time.monotonic() * .8 % 2
            k = k if k < 1 else 2 - k
            p.fillRect(QRectF(inner.x() + inner.width() * .75 * k, inner.y(), inner.width() * .25, inner.height()), lav)
        for i in range(11):
            x = round((w - 1) * i / 10) + 0.5
            p.setPen(QPen(lav if i % 5 == 0 else QColor(RULE), 1))
            p.drawLine(QPointF(x, 11), QPointF(x, 16 if i % 5 == 0 else 13))


class Surface(QWidget):
    """Capa encima de todo y sin recibir clics: grano de color (nuevo al abrir,
    movido a 10 cuadros por segundo), viñeta y líneas de barrido estáticas."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        noise = np.random.default_rng().integers(0, 256, (256, 256, 4), dtype=np.uint8)
        self.grain = QPixmap.fromImage(QImage(noise.data, 256, 256, 1024, QImage.Format_RGBA8888).copy())
        self.at = QPointF()
        # mover el grano repinta toda la ventana (~7 ms, ~7% de un núcleo); si pesa, grano quieto
        self.timer = QTimer(self, interval=100, timeout=self._move)
        self.timer.start()

    def _move(self):
        self.at = QPointF(*(float(v) for v in np.random.default_rng().integers(0, 256, 2)))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        r = self.rect()
        p.setOpacity(GRAIN)
        p.drawTiledPixmap(QRectF(r), self.grain, self.at)
        p.setOpacity(1)
        line = QColor(INK)
        line.setAlphaF(SCAN)
        for y in range(0, r.height(), 3):  # una línea de 1 px cada 3
            p.fillRect(0, y, r.width(), 1, line)
        g = QRadialGradient(0.5, 0.5, 0.5 ** 0.5)  # llega a su tono en las esquinas
        g.setCoordinateMode(QGradient.ObjectMode)  # elipse del tamaño de la ventana
        g.setColorAt(0.52, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(*VIGNETTE))
        p.fillRect(r, g)


class Elide(QLabel):
    """Texto de una línea: si no cabe termina en '…' y el texto completo queda en el globo de ayuda."""

    def paintEvent(self, e):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(QPalette.WindowText))
        r = self.contentsRect()
        text = p.fontMetrics().elidedText(self.text(), Qt.ElideRight, r.width())
        self.setToolTip(self.text() if text != self.text() else '')
        p.drawText(r, int(self.alignment()) | Qt.AlignVCenter, text)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())


def notice(parent, key, text, question=True):
    """Todo aviso de la app: SÍ/NO (o OK) con la casilla "No volver a mostrar".
    Si se marcó, la próxima vez no aparece y se repite la respuesta que se dio."""
    s = settings()
    kept = s.value(f'skip/{key}')
    if kept is not None:
        return kept == 'yes'
    box = QMessageBox(parent)
    box.setWindowTitle(TXT['brand'])
    box.setText(text)
    if question:
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText(TXT['yes'])
        box.button(QMessageBox.No).setText(TXT['no'])
    else:
        box.setStandardButtons(QMessageBox.Ok)
        box.button(QMessageBox.Ok).setText(TXT['ok'])
    check = QCheckBox(TXT['no_more'])
    box.setCheckBox(check)
    ok = box.exec() in (QMessageBox.Yes, QMessageBox.Ok)
    if check.isChecked():
        s.setValue(f'skip/{key}', 'yes' if ok else 'no')
    return ok


def warn(parent, key, text):
    notice(parent, key, text, question=False)


def section(text):
    label = QLabel(text)
    label.setObjectName('row')
    return label


def rule(vertical=False):
    line = QFrame()
    line.setObjectName('rule')
    line.setFixedWidth(1) if vertical else line.setFixedHeight(1)
    return line


def panel():
    frame = QFrame()
    frame.setObjectName('panel')
    return frame


class Key(QPushButton):
    """Tecla de panel. Las de alternancia llevan un LED cuadrado en la esquina."""

    def __init__(self, text='', fn=None, checkable=False, led=None, icon=None, width=None):
        super().__init__(text)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCheckable(checkable)
        self.led = checkable if led is None else led
        self.setProperty('led', self.led)
        self.glyph = icon
        if icon:
            self.set_glyph(icon)
        if width:
            self.setMinimumWidth(width)  # mínimo: el texto nunca se corta
        if fn:
            (self.toggled if checkable else self.clicked).connect(fn)

    def set_glyph(self, kind):
        """Cambia el ícono; el de ▶ (objectName 'phone') va en crema sobre el azul."""
        self.glyph = kind
        self.setIcon(glyph_icon(kind, color=TITLE if self.objectName() == 'phone' else None))

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.led:
            p = QPainter(self)
            r = QRectF(4, 4, 4, 4)
            if self.isChecked():
                p.fillRect(r, QColor(PAPER))
            else:
                p.setPen(QPen(QColor(MUTED), 1))
                p.drawRect(r)


class Choice(QWidget):
    """Fila de teclas exclusivas."""

    def __init__(self, items, width=None):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.group = QButtonGroup(self)
        self.keys = {}
        for data, text in items:
            k = Key(text, checkable=True, led=False, width=width)
            self.group.addButton(k)
            row.addWidget(k)
            self.keys[data] = k
        self.keys[items[0][0]].setChecked(True)

    def value(self):
        return next(d for d, k in self.keys.items() if k.isChecked())

    def set(self, data):
        if data in self.keys:
            self.keys[data].setChecked(True)


# =====================================================================================
# Espectrograma: la vista en gris del motor, teñida con el tema, con regla de tiempo y eje de Hz
# =====================================================================================

class SpecView(QWidget):
    """Espectrograma con zoom horizontal (la barra `scroll` navega y sigue a la reproducción),
    línea de reproducción que se arrastra, y un rango de Hz resaltado cuyos bordes se pueden mover."""
    RULER, AXIS = 18, 50
    ZOOMS = (1, 2, 4, 8, 16)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(240)
        self.setMouseTracking(True)
        self.gray, self.dur, self.peaks, self.silent, self.notes = None, 0.0, [], False, []
        self.drop_hover, self._cache = False, None
        self.playhead, self.on_seek = None, None  # segundos; callback(segundos) al hacer clic o arrastrar
        self.band, self.band_edit, self.on_band = None, False, None  # (hz_bajo, hz_alto); bordes movibles
        self.zoom, self.offset, self._drag = 1, 0.0, None
        self.scroll = QScrollBar(Qt.Horizontal)
        self.scroll.hide()
        self.scroll.valueChanged.connect(self._scrolled)

    # --- contenido ---
    def show_stem(self, d, notes=()):
        from PIL import Image
        self.gray = np.asarray(Image.open(d['vista']).convert('L'))
        self.dur, self.peaks, self.silent = d['duracion_s'], d['picos'], d['casi_silencio']
        self.notes, self._cache = list(notes), None
        self._sync()

    def show_notes(self, notes):
        """Notas sin espectrograma (audio convertido sin análisis): solo el piano roll sobre el fondo."""
        self.gray, self.peaks, self.silent, self.notes, self._cache = None, [], False, list(notes), None
        self.dur = max((e for _, e, _ in notes), default=0.0)
        self._sync()

    def clear(self, _text=''):
        """Sin texto en el centro: lo que pasa ya lo dice la línea junto a ▶."""
        self.gray, self.notes, self.dur, self._cache = None, [], 0.0, None
        self._sync()

    # --- zoom y desplazamiento ---
    @property
    def win(self):
        return self.dur / self.zoom if self.dur else 0.0

    def zoom_by(self, step):
        """step +1 acerca, -1 aleja; se queda centrado en la reproducción o en el centro de lo visible."""
        i = max(0, min(len(self.ZOOMS) - 1, self.ZOOMS.index(self.zoom) + step))
        center = self.playhead if self.playhead is not None else self.offset + self.win / 2
        self.zoom = self.ZOOMS[i]
        self.offset = center - self.win / 2
        self._sync()

    def _sync(self):
        """Ajusta la barra a lo visible. El zoom estira la imagen del análisis (1600 columnas);
        a x16 se ve suave pero no más detallada. Recalcular la STFT por ventana si hace falta más detalle."""
        self.offset = max(0.0, min(self.offset, self.dur - self.win))
        self.scroll.blockSignals(True)
        self.scroll.setVisible(self.zoom > 1 and self.dur > 0)
        self.scroll.setRange(0, int((self.dur - self.win) * 1000))
        self.scroll.setPageStep(max(1, int(self.win * 1000)))
        self.scroll.setValue(int(self.offset * 1000))
        self.scroll.blockSignals(False)
        self.update()

    def _scrolled(self, v):
        self.offset = v / 1000
        self.update()

    def set_playhead(self, t):
        """Mueve la línea; si sale de lo visible, la vista la sigue."""
        self.playhead = t
        if t is not None and self.zoom > 1 and not (self.offset <= t <= self.offset + self.win):
            self.offset = t - self.win * 0.1
            self._sync()
        else:
            self.update()

    # --- geometría ---
    def area(self):
        return QRectF(self.AXIS, self.RULER, self.width() - self.AXIS, self.height() - self.RULER)

    def y_of(self, f):
        a = self.area()
        lo, hi = engine.VISTA_HZ
        return a.top() + (1 - math.log(f / lo) / math.log(hi / lo)) * (a.height() - 1)

    def f_of(self, y):
        a = self.area()
        lo, hi = engine.VISTA_HZ
        return lo * (hi / lo) ** (1 - (y - a.top()) / (a.height() - 1))

    def x_of(self, t):
        a = self.area()
        return a.left() + (t - self.offset) / self.win * a.width()

    def t_of(self, x):
        a = self.area()
        return max(0.0, min(self.dur, self.offset + (x - a.left()) / a.width() * self.win))

    def _pixmap(self, a):
        h, w = self.gray.shape
        c0 = int(self.offset / self.dur * w)
        c1 = max(c0 + 1, min(w, round((self.offset + self.win) / self.dur * w)))
        key = (int(a.width()), int(a.height()), SPECTRUM, c0, c1)
        if self._cache is None or self._cache[0] != key:
            stops = np.array([QColor(c).getRgb()[:3] for c in SPECTRUM], float)
            t = np.linspace(0, 1, 256)
            lut = np.stack([np.interp(t, (0, .5, .8, 1), stops[:, k]) for k in range(3)], 1)
            rgb = np.ascontiguousarray(lut.astype(np.uint8)[self.gray[:, c0:c1]])
            img = QImage(rgb.data, c1 - c0, h, 3 * (c1 - c0), QImage.Format_RGB888).copy()
            self._cache = key, QPixmap.fromImage(img.scaled(key[0], key[1], Qt.IgnoreAspectRatio,
                                                            Qt.SmoothTransformation))
        return self._cache[1]

    # --- dibujo ---
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(PAPER))
        if (self.gray is not None or self.notes) and self.dur > 0:
            a = self.area()
            if self.gray is not None:
                p.drawPixmap(a.topLeft(), self._pixmap(a))
            p.setClipRect(a.adjusted(0, -self.RULER, 0, 0))
            if self.band:
                self._paint_band(p, a)
            self._paint_notes(p, a)
            p.setClipping(False)
            self._paint_axes(p, a)
            tabs = []
            for pk in [] if self.notes or self.band else self.peaks:  # con notas o rango, los picos estorban
                y = round(self.y_of(pk['hz'])) + 0.5
                p.setPen(QPen(QColor(INK), 1, Qt.DashLine))
                p.drawLine(QPointF(a.left(), y), QPointF(a.right(), y))
                label = pk['nota']
                w = p.fontMetrics().horizontalAdvance(label) + 6
                tab = QRectF(a.right() - w, y - 12, w, 12)
                while any(tab.intersects(t) for t in tabs):  # notas muy juntas: la pestaña se corre a la izquierda
                    tab.translate(-tab.width() - 2, 0)
                tabs.append(tab)
                p.fillRect(tab, QColor(INK))
                p.setPen(QColor(PAPER))
                p.drawText(tab, Qt.AlignCenter, label)
            if self.silent:
                hatch(p, a, PANEL, step=6, width=1)
                p.setFont(qfont('big'))
                box = QRectF(0, 0, p.fontMetrics().horizontalAdvance(TXT['silent']) + 28, 28)
                box.moveCenter(a.center())
                p.fillRect(box, QColor(PAPER))
                p.setPen(QPen(QColor(INK), 1))
                p.drawRect(box)
                p.drawText(box, Qt.AlignCenter, TXT['silent'])
            if self.playhead is not None and self.offset <= self.playhead <= self.offset + self.win:
                x = self.x_of(self.playhead)
                p.fillRect(QRectF(x - 1, a.top(), 2, a.height()), QColor(INK))
                p.fillRect(QRectF(x - 4, a.top() - 8, 8, 8), QColor(INK))
            corners(p, a.adjusted(.5, .5, -.5, -.5), TITLE)
        elif not self.drop_hover:
            self._paint_banner(p)
        if self.drop_hover:
            p.setFont(qfont('small'))
            p.setPen(QPen(QColor(INK), 2))
            p.drawRect(QRectF(self.rect()).adjusted(4, 4, -4, -4))
            p.drawText(self.rect(), Qt.AlignCenter, TXT['drop'])

    def _paint_banner(self, p):
        """Vacío: un banner azul con doble marco crema, el logo y el nombre, y las franjas celestes y crema."""
        r = QRectF(self.rect()).adjusted(32, 32, -32, -32)
        r.setHeight(min(r.height(), r.width() * .42))
        r.moveCenter(QRectF(self.rect()).center())
        p.fillRect(r, QColor(ACCENT))
        p.setPen(QPen(QColor(TITLE), 2))
        p.drawRect(r.adjusted(1, 1, -1, -1))
        p.setPen(QPen(QColor(TITLE), 1))
        p.drawRect(r.adjusted(5.5, 5.5, -5.5, -5.5))
        logo = logo_pixmap(TITLE, 44)
        top = r.top() + r.height() * .16
        p.drawPixmap(QPointF(r.left() + 32, top), logo)
        p.setFont(qfont('big'))
        p.setPen(QColor(TITLE))
        p.drawText(QRectF(r.left() + 48 + logo.deviceIndependentSize().width(), top, r.width(), 44),
                   Qt.AlignLeft | Qt.AlignVCenter, TXT['brand'])
        rng = np.random.default_rng(7)  # siempre las mismas franjas
        y0, rows = r.top() + r.height() * .5, 9
        rh = (r.bottom() - 14 - y0) / rows
        for i in range(rows):  # cada vez más llenas hacia abajo
            x = r.left() + 10 + rng.uniform(0, r.width() * .3) * (1 - i / rows)
            while x < r.right() - 10:
                w = rng.uniform(24, 160)
                p.fillRect(QRectF(x, y0 + i * rh, min(w, r.right() - 10 - x), rh * .55),
                           QColor(TITLE if i % 2 else DATA))
                x += w + rng.uniform(4, 90) * (1 - i / rows)

    def _band_ys(self, a):
        return [max(a.top(), min(a.bottom(), self.y_of(f))) for f in self.band]

    def _paint_band(self, p, a):
        """Fuera del rango: el espectrograma se apaga con el fondo; los bordes llevan su frecuencia."""
        y_lo, y_hi = self._band_ys(a)
        shade = QColor(PAPER)
        shade.setAlpha(190)
        p.fillRect(QRectF(a.left(), a.top(), a.width(), y_hi - a.top()), shade)
        p.fillRect(QRectF(a.left(), y_lo, a.width(), a.bottom() - y_lo), shade)
        p.setFont(qfont('small'))
        for i, (y, f) in enumerate(((y_hi, self.band[1]), (y_lo, self.band[0]))):
            p.setPen(QPen(QColor(INK), 2 if self._drag == 1 - i else 1))
            p.drawLine(QPointF(a.left(), y), QPointF(a.right(), y))
            label = f'{hz(f)} HZ' + ('  ↕' if self.band_edit else '')
            tab = QRectF(a.left() + 4, y - 13 if i == 0 else y + 1, p.fontMetrics().horizontalAdvance(label) + 8, 12)
            p.fillRect(tab, QColor(INK))
            p.setPen(QColor(PAPER))
            p.drawText(tab, Qt.AlignCenter, label)

    def _paint_notes(self, p, a):
        """Piano roll: cada nota es una barra en su frecuencia, con borde de fondo para leerse sobre el gris."""
        if not self.notes:
            return
        lo, hi = engine.VISTA_HZ
        p.setPen(QPen(QColor(PAPER), 1))
        p.setBrush(QColor(INK))
        for start, end, pitch in self.notes:
            f = 440 * 2 ** ((pitch - 69) / 12)
            if lo <= f <= hi and end >= self.offset and start <= self.offset + self.win:
                x0, x1 = self.x_of(start), self.x_of(end)
                p.drawRect(QRectF(x0, self.y_of(f) - 2.5, max(x1 - x0, 2), 5))
        p.setBrush(Qt.NoBrush)

    def _paint_axes(self, p, a):
        p.setFont(qfont('small'))
        p.setPen(QPen(QColor(CONTROL), 1))
        p.drawLine(QPointF(a.left(), a.top() - 0.5), QPointF(a.right(), a.top() - 0.5))
        p.drawLine(QPointF(a.left() - 0.5, a.top()), QPointF(a.left() - 0.5, a.bottom()))
        for f in HZ_TICKS:
            y = round(self.y_of(f)) + 0.5
            p.setPen(QPen(QColor(MUTED), 1))
            p.drawLine(QPointF(a.left() - 5, y), QPointF(a.left(), y))
            p.drawText(QRectF(0, y - 7, a.left() - 7, 14), Qt.AlignRight | Qt.AlignVCenter, hz(f))
        step = next((s for s in (0.5, 1, 2, 5, 10, 15, 30, 60) if s / self.win * a.width() >= 70), 120)
        t = math.ceil(self.offset / step) * step
        while (x := round(self.x_of(t)) + 0.5) < a.right():
            p.setPen(QPen(QColor(MUTED), 1))
            p.drawLine(QPointF(x, a.top() - 5), QPointF(x, a.top()))
            label = f'{int(t // 60)}:{int(t % 60):02d}' + (f'.{int(t * 10) % 10}' if step < 1 else '')
            p.drawText(QPointF(x + 3, 11), label)
            t += step

    # --- ratón: arrastrar la reproducción o los bordes del rango ---
    def _edge_at(self, pos):
        if not (self.band and self.band_edit):
            return None
        ys = self._band_ys(self.area())
        near = [(abs(pos.y() - y), i) for i, y in enumerate(ys) if abs(pos.y() - y) <= 8]
        return min(near)[1] if near else None

    def mousePressEvent(self, e):
        a, pos = self.area(), e.position()
        if self.dur <= 0 or not a.left() <= pos.x() <= a.right():
            return
        edge = self._edge_at(pos)
        self._drag = edge if edge is not None else 'play'
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is None:
            self.setCursor(Qt.SizeVerCursor if self._edge_at(pos) is not None else Qt.ArrowCursor)
            return
        if self._drag == 'play':
            if self.on_seek:
                self.on_seek(self.t_of(pos.x()))
            return
        a = self.area()
        f = self.f_of(max(a.top(), min(a.bottom(), pos.y())))
        lo, hi = self.band
        lo, hi = (min(f, hi / 1.06), hi) if self._drag == 0 else (lo, max(f, lo * 1.06))  # al menos un semitono
        self.band = (round(lo, 1), round(hi, 1))
        if self.on_band:
            self.on_band(self.band)
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.update()


def corners(p, r, color, n=10):
    """Esquinas en escuadra en vez de un marco completo."""
    p.setPen(QPen(QColor(color), 1))
    for x, y, dx, dy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                         (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * n, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * n))


def zoom_keys(spec):
    """− y + para alejar y acercar el espectrograma."""
    out = []
    for text, step, tip in (('−', -1, 'Alejar'), ('+', 1, 'Acercar')):
        k = Key(text, lambda _=False, s=step: spec.zoom_by(s), width=28)
        k.setToolTip(tip)
        out.append(k)
    return out


# =====================================================================================
# Ventana
# =====================================================================================

class Bridge(QObject):
    """Los avisos del hilo de trabajo llegan a la ventana por una señal de Qt (cola entre hilos)."""
    msg = Signal(str, object)


class Reticled(QListWidget):
    """Lista que, vacía, muestra pequeño un pequeño indicador de horizonte."""

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count():
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.viewport().rect().center())
        p.setPen(QPen(QColor(MUTED), 1))
        p.drawEllipse(c, 5, 5)
        for a, b in ((-26, -7), (7, 26), (-44, -32), (32, 44)):  # alas y horizonte
            p.drawLine(c + QPointF(a, 0), c + QPointF(b, 0))
        p.drawLine(c + QPointF(0, -7), c + QPointF(0, -14))


class StemList(Reticled):
    """Lista de stems: la casilla de cada uno lo suma a la mezcla que se escucha; se arrastran a Ableton."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragOnly)

    def mimeData(self, items):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(i.data(Qt.UserRole)[1]) for i in items if i.data(Qt.UserRole)])
        return data


class Player:
    """Mezcla en vivo de los stems marcados. Todo en RAM (~85 MB por stem de 4 min);
    streaming desde disco si alguien junta decenas de stems largos."""

    def __init__(self):
        self.tracks, self.active, self.pos, self.stream = {}, set(), 0, None
        self.mix, self.solo = {}, set()  # mix: {ruta: (dB, paneo -100..100)}; con solos suenan solo ellos

    @property
    def audible(self):
        return self.solo or self.active

    def load(self, paths):
        import librosa
        for p in paths:
            if p not in self.tracks:
                y = librosa.load(p, sr=engine.SR, mono=False)[0]
                self.tracks[p] = np.ascontiguousarray((np.stack([y, y]) if y.ndim == 1 else y).T, dtype=np.float32)

    @property
    def length(self):
        return max((len(self.tracks[p]) for p in self.audible if p in self.tracks), default=0)

    def block(self, n):
        out = np.zeros((n, 2), np.float32)
        for p in tuple(self.audible):  # la lista puede cambiar mientras suena
            seg = self.tracks.get(p, out[:0])[self.pos:self.pos + n]
            db, pan = self.mix.get(p, (0, 0))
            if db <= DB_OFF:
                continue
            # balance: el paneo baja el lado contrario; a 0 dB y centro el stem suena tal cual
            out[:len(seg)] += seg * (10 ** (db / 20) * np.array([min(1, 1 - pan / 100), min(1, 1 + pan / 100)], np.float32))
        self.pos += n
        return np.clip(out, -1, 1)

    def play(self):
        import sounddevice as sd

        def callback(outdata, frames, _t, _s):
            outdata[:] = self.block(frames)
            if self.pos >= self.length:
                raise sd.CallbackStop
        self.stream = sd.OutputStream(samplerate=engine.SR, channels=2, dtype='float32', callback=callback)
        self.stream.start()

    def stop(self):
        if self.stream:
            self.stream.close()
            self.stream = None

    @property
    def playing(self):
        return self.stream is not None and self.stream.active


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('RD Stems')
        self.setAcceptDrops(True)
        self.srcs, self.src, self.dst = [], '', ''
        self.conf = {}  # canción -> {'stems': set, 'extras': set}: casillas propias de cada una
        self.jobs, self.running = [], None  # canciones en la separación en curso y la que va
        self.report, self.busy, self.hw, self.song = None, False, None, ''
        self.run = None  # avance de la separación en curso: tiempos y pesos de los pasos
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self._progress)
        self.player = Player()
        self.bridge = Bridge()
        self.bridge.msg.connect(self.on_msg)

        # --- tira superior ---
        self.logo = QLabel()
        brand = Title(TXT['brand'])
        header = QHBoxLayout()
        header.setSpacing(4)
        header.addWidget(self.logo)
        header.addSpacing(8)
        header.addWidget(brand)
        header.addSpacing(24)
        self.tabs = Choice((('stems', TXT['tab_stems']), ('midi', TXT['tab_midi'])), width=96)
        self.tabs.group.buttonClicked.connect(lambda _: self.show_tab())
        for k in self.tabs.keys.values():
            k.setObjectName('tab')
        header.addWidget(self.tabs)
        header.addStretch()
        # cada pestaña con sus teclas: ABRIR de STEMS carga canciones para separar; ABRIR de MIDI carga sonidos al MIDI
        self.stem_keys_bar = QWidget()
        bar = QHBoxLayout(self.stem_keys_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)
        bar.addWidget(Key(TXT['open'], self.open_dialog))
        bar.addWidget(Key(TXT['batch'], self.folder_dialog))
        k = Key(TXT['yt'], self.youtube_dialog)
        k.setToolTip(f'Pega un link de YouTube o de una canción de Spotify, o busca en YouTube; '
                     f'el audio queda en {yt_dir()} y se suma a la lista.')
        bar.addWidget(k)
        header.addWidget(self.stem_keys_bar)
        self.midi_open = QWidget()  # ABRIR y CARPETA de MIDI: cargan sonidos al MIDI, no a STEMS
        bar = QHBoxLayout(self.midi_open)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)
        k = Key(TXT['open'], lambda: self.midi.open_dialog())
        k.setToolTip('Abre audios para convertir a MIDI (stems, loops, cualquier sonido).')
        bar.addWidget(k)
        k = Key(TXT['batch'], lambda: self.midi.folder_dialog())
        k.setToolTip('Carga todos los audios de una carpeta (sin subcarpetas).')
        bar.addWidget(k)
        self.midi_open.hide()
        header.addWidget(self.midi_open)
        header.addSpacing(16)
        self.device = Decode('…')
        self.device.setObjectName('info')
        header.addWidget(self.device)
        header.addSpacing(16)
        self.theme_btns = {}
        for name in ('day', 'night'):
            b = Key(checkable=True, led=False, width=28)
            b.clicked.connect(lambda _=False, name=name: self.set_theme(name))
            b.glyph = name
            header.addWidget(b)
            self.theme_btns[name] = b

        # --- display: espectrograma y su borde inferior con transporte, estado y progreso ---
        self.spec = SpecView()
        self.spec.on_seek = self.seek
        self.play_btn = Key(icon='play', fn=self.toggle_play, width=36)
        self.play_btn.setObjectName('phone')  # tecla principal: azul con marco crema
        self.play_btn.set_glyph('play')
        self.play_btn.setToolTip(TXT['play_tip'])
        self.info = Elide()
        self.info.setObjectName('info')
        self.info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.bar = Progress()
        self.bar.setFixedWidth(160)
        status = QHBoxLayout()
        status.setContentsMargins(6, 4, 8, 4)
        status.setSpacing(10)
        status.addWidget(self.play_btn)
        for k in zoom_keys(self.spec):
            status.addWidget(k)
        self.eta = Elide(' ')  # ' ' y no '' para que la fila no cambie de alto al empezar
        self.eta.setObjectName('info')
        self.eta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        lv.addWidget(self.info)
        lv.addWidget(self.eta)
        status.addWidget(left, 1)
        status.addWidget(self.bar)
        self.cancel_btn = Key(TXT['cancel'], self.cancel)
        self.cancel_btn.hide()
        status.addWidget(self.cancel_btn)
        status.addWidget(Key(TXT['show'], self.open_dir))
        display = QFrame()
        display.setObjectName('display')
        dl = QVBoxLayout(display)
        dl.setContentsMargins(1, 1, 1, 1)
        dl.setSpacing(0)
        dl.addWidget(self.spec, 1)
        dl.addWidget(self.spec.scroll)
        dl.addWidget(rule())
        dl.addLayout(status)

        self.bulk_sep = icon_key('split', lambda: self.start([it['path'] for it in self.songs.selected()]),
                                 TXT['sep_sel'])
        self.bulk_dl = icon_key('down', lambda: self.download(self.songs.selected()), TXT['dl_stems_sel'])
        self.bulk_rm = icon_key('x', lambda: self.remove(self.songs.selected()), TXT['rm_song_sel'])
        self.songs = Module('stems_view', (self.bulk_sep, self.bulk_dl, self.bulk_rm), self.pick_song,
                            self._song_counts)
        self.list = StemList()
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.currentItemChanged.connect(self.show_selected)
        self.list.itemChanged.connect(self.mix_changed)
        column = QWidget()
        column.setFixedWidth(318)
        cl = QVBoxLayout(column)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        cl.addWidget(self.songs, 3)
        cl.addWidget(self.list, 2)
        cl.addWidget(self._mixer())
        middle = QHBoxLayout()
        middle.setSpacing(8)
        middle.addWidget(column)
        middle.addWidget(display, 1)

        # --- placa: qué separar, extras de voz, calidad y datos del stem ---
        plate = panel()
        grid = QGridLayout(plate)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        s = settings()
        saved = set(s.value('stems', 'voz,bateria,bajo,guitarra,teclado').split(','))
        self.stem_keys = {}
        rows = (QGridLayout(), QHBoxLayout(), QHBoxLayout())
        rows[0].setSpacing(4)
        for i, (key, text, tip) in enumerate(STEM_KEYS):
            k = Key(text, checkable=True, width=112)
            k.setChecked(key in saved)
            k.setToolTip(MEGA_TIP if tip == 'MEGA' else tip)
            rows[0].addWidget(k, i // 5, i % 5)
            self.stem_keys[key] = k
        rows[0].setColumnStretch(5, 1)
        saved = set(s.value('extras', '').split(','))
        self.voice_keys = {}
        for key, text, tip in VOICE_KEYS:
            k = Key(text, checkable=True, width=112)
            k.setChecked(key in saved)
            k.setToolTip(tip)
            rows[1].addWidget(k)
            self.voice_keys[key] = k
        self.quality = Choice((('max', TXT['max']), ('fast', TXT['fast'])), width=112)
        self.quality.set(s.value('quality', 'max'))
        self.analyze = Key(TXT['analyze'], checkable=True, width=112)
        self.analyze.setChecked(s.value('analyze', 'true') == 'true')
        rows[2].addWidget(self.quality)
        rows[2].addSpacing(24)
        rows[2].addWidget(self.analyze)
        for i, (label, row) in enumerate(zip((TXT['separate'], TXT['voice'], TXT['quality']), rows)):
            if i:
                row.setSpacing(4)
                row.addStretch()
            grid.addWidget(section(label), i, 0, Qt.AlignTop if i == 0 else Qt.AlignVCenter)
            grid.addLayout(row, i, 1)
        for k in (*self.stem_keys.values(), *self.voice_keys.values()):
            k.toggled.connect(self._conf_changed)
        self.stem_keys['voz'].toggled.connect(self._voice_enabled)
        self._voice_enabled(self.stem_keys['voz'].isChecked())
        grid.addWidget(rule(vertical=True), 0, 2, 3, 1)
        data = QGridLayout()
        data.setHorizontalSpacing(12)
        data.setVerticalSpacing(2)
        self.values = {}
        for i, (label, key) in enumerate(DATA_ROWS):
            v = Decode('—')
            v.setObjectName('datum')
            v.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # muchos acordes no ensanchan la ventana
            data.addWidget(section(label), i % 4, 2 * (i // 4))
            data.addWidget(v, i % 4, 2 * (i // 4) + 1)
            self.values[key] = v
        data.setColumnStretch(1, 1)
        data.setColumnStretch(3, 1)
        grid.addLayout(data, 0, 3, 3, 1)
        grid.setColumnStretch(3, 1)

        stems_page = QWidget()
        sl = QVBoxLayout(stems_page)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        sl.addLayout(middle, 1)
        sl.addWidget(plate)
        self.midi = MidiPage(self)
        self.stack = QStackedWidget()
        for page in (stems_page, self.midi):
            self.stack.addWidget(page)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        lay.addLayout(header)
        lay.addWidget(TitleRule())
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        QShortcut(QKeySequence(Qt.Key_Space), self,
                  lambda: self.midi.toggle_play() if self.stack.currentWidget() is self.midi else self.toggle_play())
        self.timer = QTimer(self, interval=30, timeout=self._tick)
        self.set_theme(settings().value('theme', 'night'))
        self._refresh_info()
        bg(lambda: self.bridge.msg.emit('hw', engine.hardware()))

    def show_tab(self):
        """Cada pestaña lee del disco lo que hay al mostrarse: así ve lo recién separado, convertido o borrado."""
        self.stop_play(keep_pos=True)
        self.midi.stop_play()
        page = {'stems': 0, 'midi': 1}[self.tabs.value()]
        self.stack.setCurrentIndex(page)
        if not self.boot and self.isVisible():
            QTimer.singleShot(0, lambda: self.assemble(self.stack.currentWidget(), pace=.5))  # tras acomodarse
        self.stem_keys_bar.setVisible(page == 0)
        self.midi_open.setVisible(page == 1)
        if page:
            self.stack.currentWidget().refresh()

    def library(self):
        """Stems en disco de las canciones abiertas y de las separadas antes (los usa MIDI)."""
        items = []
        for src in self.srcs + [h for h in self.history() if h not in self.srcs]:
            for f in self.song_files(src):
                items.append(dict(f, src=src, dst=self._dst(src), ext='.wav',
                                  label=LABELS.get(f['base'], f['base'].replace('_', ' ').upper())))
        return items

    def forget(self, paths):
        """Stems borrados desde MIDI: fuera de la lista de STEMS y de lo que suena."""
        paths = set(paths)
        for i in reversed(range(self.list.count())):
            d = self.list.item(i).data(Qt.UserRole)
            if d and os.path.normpath(d[1]) in paths:
                self.list.takeItem(i)
        for p in list(self.player.tracks):
            if os.path.normpath(p) in paths:
                self.player.tracks.pop(p)
                self.player.active.discard(p)
                self.player.solo = self.player.solo - {p}

    def history(self, add=()):
        """Canciones ya separadas (de esta y otras sesiones) cuya carpeta de stems sigue existiendo:
        EXPORTAR y MIDI las muestran aunque no estén abiertas."""
        s = settings()
        songs = [p for p in s.value('library', [], type=list) + list(add) if os.path.isdir(self._dst(p))]
        songs = list(dict.fromkeys(songs))
        s.setValue('library', songs)
        return songs

    # --- mezclador: botones de un clic y VOL / PAN / SOLO del stem elegido (idea de StemKit) ---
    def _mixer(self):
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        tips = dict(all='Todos los stems: la canción completa.', karaoke='Todo menos la voz.',
                    acapella='Solo la voz.', rhythm='Batería y bajo.')
        presets = QHBoxLayout()
        presets.setSpacing(4)
        for kind in tips:
            k = Key(TXT[kind], lambda _=False, kind=kind: self.preset(kind))
            k.setToolTip(tips[kind] + ' Las teclas 1–9 activan o silencian cada stem, de arriba abajo.')
            presets.addWidget(k)
        grid.addLayout(presets, 0, 0, 1, 4)
        self.vol, vol_v = slider(DB_OFF, 6, 0, db_txt)
        self.pan, pan_v = slider(-100, 100, 0, pan_txt)
        self.solo = Key('SOLO', self.solo_changed, checkable=True, width=60)
        for i, (name, sl, val) in enumerate((('VOL', self.vol, vol_v), ('PAN', self.pan, pan_v)), 1):
            grid.addWidget(section(name), i, 0)
            grid.addWidget(sl, i, 1)
            grid.addWidget(val, i, 2)
            sl.valueChanged.connect(self.level_changed)
            sl.sliderReleased.connect(self.save_mix)
        grid.addWidget(self.solo, 1, 3)
        grid.setColumnStretch(1, 1)
        for n in range(1, 10):
            QShortcut(QKeySequence(Qt.Key_0 + n), self, lambda n=n: self.toggle_nth(n))
        self._show_levels(None)
        return box

    def _stem_items(self):
        return [self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(Qt.UserRole)]

    def _mark(self, it):
        """Nombre del stem con su SOLO, volumen y paneo si no son los de fábrica."""
        path = it.data(Qt.UserRole)[1]
        db, pan = self.player.mix.get(path, (0, 0))
        tags = ['SOLO'] * (path in self.player.solo) + [db_txt(db)] * (db != 0) + [pan_txt(pan)] * (pan != 0)
        it.setText('  · '.join([it.data(Qt.UserRole + 1)] + tags))

    def _show_levels(self, path):
        db, pan = self.player.mix.get(path, (0, 0)) if path else (0, 0)
        self.vol.setValue(db)  # level_changed vuelve a escribir el mismo nivel: no hace falta bloquear
        self.pan.setValue(pan)
        self.solo.blockSignals(True)  # sin bloqueo, marcarlo cargaría el audio otra vez
        self.solo.setChecked(path in self.player.solo)
        self.solo.blockSignals(False)
        for w in (self.vol, self.pan, self.solo):
            w.setEnabled(bool(path))

    def level_changed(self, _=None):
        it = self.list.currentItem()
        if not it or not it.data(Qt.UserRole):
            return
        self.player.mix[it.data(Qt.UserRole)[1]] = (self.vol.value(), self.pan.value())
        self._mark(it)

    def solo_changed(self, on):
        it = self.list.currentItem()
        if not it or not it.data(Qt.UserRole):
            return
        path = it.data(Qt.UserRole)[1]
        if on:
            with_wait(lambda: self.player.load([path]))
        # se reemplaza entero: el hilo de audio nunca ve el conjunto a medio cambiar
        self.player.solo = self.player.solo | {path} if on else self.player.solo - {path}
        self._mark(it)

    def save_mix(self):
        """VOL y PAN de cada stem quedan en <canción> - stems/mezcla.json y vuelven al abrirla."""
        if not os.path.isdir(self.dst):
            return
        mix = {it.data(Qt.UserRole)[0]: self.player.mix[it.data(Qt.UserRole)[1]] for it in self._stem_items()
               if self.player.mix.get(it.data(Qt.UserRole)[1], (0, 0)) != (0, 0)}
        try:
            with open(os.path.join(self.dst, 'mezcla.json'), 'w', encoding='utf-8') as f:
                json.dump(mix, f, ensure_ascii=False, indent=1)
        except OSError:
            log_error(traceback.format_exc())

    def toggle_nth(self, n):
        items = self._stem_items()
        if self.stack.currentIndex() == 0 and n <= len(items):
            it = items[n - 1]
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def _plays(self, g, s, kind):
        if kind == 'acapella':
            return s == 'voz'
        if kind == 'rhythm':
            return s in ('bateria', 'bajo') or (g == 'Batería 6' and self.kit_plays)
        # por defecto suena la canción armada con sus stems (stems + resto = mezcla)
        on = (g == 'Stems' and s not in VOICE_DUPES) or (g == 'Batería 6' and self.kit_plays)
        return on and not (kind == 'karaoke' and s == 'voz')

    def preset(self, kind):
        self.player.solo = set()
        for it in self._stem_items():
            g, s = it.data(Qt.UserRole)[0].split(' / ')
            it.setCheckState(Qt.Checked if self._plays(g, s, kind) else Qt.Unchecked)
            self._mark(it)
        self._show_levels(self._selected_path())

    def _voice_enabled(self, on):
        for k in self.voice_keys.values():
            k.setEnabled(on)

    # --- tema ---
    assembly = boot = None

    def assemble(self, root=None, pace=1.0):
        """Arma la interfaz (o solo una pestaña) por partes, con la coreografía de choreography()."""
        if self.assembly:
            self.assembly.finish()
        self.assembly = Assembly(self, choreography(self, root or self, pace))
        for w in (self.assembly, self.boot, self.surface):  # debajo del arranque y del grano
            if w:
                w.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.assembly:  # sus rectángulos ya no sirven
            self.assembly.finish()
        if not hasattr(self, 'surface'):
            self.surface = Surface(self)
        for w in (getattr(self, 'boot', None), self.surface):
            if w:
                w.setGeometry(self.rect())
        self.surface.raise_()

    def set_theme(self, name):
        """Día o noche: cambia la paleta en caliente, con el tema nuevo bajando por bandas, y la recuerda."""
        old = self.grab() if self.isVisible() and not self.boot and name != settings().value('theme') else None
        apply_theme(name)
        pix = logo_pixmap(INK, 22)
        self.logo.setPixmap(pix)
        self.logo.setFixedSize(pix.deviceIndependentSize().toSize())
        for key, b in self.theme_btns.items():
            b.setChecked(key == name)
        for k in self.findChildren(Key):  # los íconos están dibujados con los colores del tema
            if k.glyph:
                k.set_glyph(k.glyph)
        for w in self.findChildren(QWidget):
            w.update()
        settings().setValue('theme', name)
        if old:
            ThemeRoll(self, old)
            self.surface.raise_()

    # --- archivos ---
    def open_dialog(self):
        exts = ' '.join('*' + e for e in EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(self, TXT['open'], os.path.dirname(self.src), f'Audio ({exts})')
        if paths:
            self.set_sources(paths)

    def folder_dialog(self):
        """Todas las canciones de una carpeta (sin subcarpetas), después de confirmar cuántas son."""
        folder = QFileDialog.getExistingDirectory(self, TXT['batch'], os.path.dirname(self.src))
        if not folder:
            return
        n = sum(f.lower().endswith(EXTENSIONS) for f in os.listdir(folder))
        if n and notice(self, 'load_folder', TXT['load_folder'].format(n)):
            self.set_sources([folder])

    def _dst(self, src):
        """Los stems quedan junto a la canción, en la carpeta de donde se abrió."""
        return os.path.splitext(src)[0] + ' - stems'

    def youtube_dialog(self):
        """Link o búsqueda de YouTube: baja el audio en segundo plano y lo suma a la lista (idea de StemKit)."""
        text, ok = QInputDialog.getText(self, TXT['yt'], 'Pega un link de YouTube o de una canción de Spotify,\n'
                                                          'o escribe qué buscar:')
        text = text.strip()
        if not ok or not text:
            return
        url = text if text.startswith(('http://', 'https://')) else None
        if not url:
            try:
                found = with_wait(lambda: engine.youtube_search(text))
            except Exception:
                return self.on_msg('yt_error', traceback.format_exc())
            if not found:
                return warn(self, 'yt_none', 'Sin resultados en YouTube.')
            names = [f'{t}  ({fmt_time(d)})' for _, t, d in found]
            pick, ok = QInputDialog.getItem(self, TXT['yt'], 'Elige la canción:', names, 0, False)
            if not ok:
                return
            url = found[names.index(pick)][0]
        os.makedirs(yt_dir(), exist_ok=True)
        emit = self.bridge.msg.emit

        def work():
            try:
                link = url
                if 'spotify.' in link:  # Spotify no deja bajar su audio: se busca la misma canción en YouTube
                    emit('log', 'Buscando en YouTube la canción de Spotify…')
                    link, title, _ = engine.spotify_to_youtube(link)
                    emit('log', f'En YouTube: {title}')
                emit('yt', engine.youtube_audio(link, yt_dir(), lambda m: emit('log', m)))
            except Exception:
                emit('yt_error', traceback.format_exc())
        bg(work)

    def set_sources(self, paths):
        """Suma a la lista uno o varios archivos, o los audios de carpetas (sin subcarpetas)."""
        srcs = []
        for p in paths:
            if os.path.isdir(p):
                srcs += sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(EXTENSIONS))
            elif p.lower().endswith(EXTENSIONS):
                srcs.append(p)
        srcs = [os.path.normpath(p) for p in srcs]
        if not srcs:
            return
        s = settings()
        last = dict(stems=set(s.value('stems', 'voz,bateria,bajo,guitarra,teclado').split(',')) - {''},
                    extras=set(s.value('extras', '').split(',')) - {''})
        for p in srcs:
            if p not in self.srcs:
                self.srcs.append(p)
                self.conf[p] = {k: set(v) for k, v in last.items()}  # empieza con las últimas casillas usadas
        self.history(srcs)  # las ya separadas de antes también aparecen en MIDI
        self.refresh_songs(srcs[0])
        if self.stack.currentIndex():
            self.stack.currentWidget().refresh()

    def remove(self, items):
        """Quita canciones de la lista; sus archivos y stems quedan en disco."""
        paths = [it['path'] for it in items if it['path'] not in self.jobs]
        if self.busy and len(paths) < len(items):
            warn(self, 'busy_now', TXT['busy_now'])
        for p in paths:
            self.srcs.remove(p)
            self.conf.pop(p, None)
        if paths:
            self.refresh_songs()

    # --- módulo de canciones ---
    def song_files(self, src):
        """Stems de una canción que existen en disco (las piezas de BATERÍA 6 al final)."""
        dst, items = self._dst(src), []
        for sub in ('', 'bateria_6'):
            folder = os.path.join(dst, sub)
            if os.path.isdir(folder):
                for f in os.listdir(folder):
                    base, ext = os.path.splitext(f)
                    if ext.lower() == '.wav':
                        items.append(dict(path=os.path.normpath(os.path.join(folder, f)), base=base, piece=bool(sub),
                                          label=('BATERÍA 6 · ' if sub else '') + LABELS.get(base, base.replace('_', ' ').upper())))
        order = [k for k, _, _ in STEM_KEYS] + ['resto', 'voz_principal', 'coros', 'voz_seca', 'voz_limpia', *engine.GM_DRUMS]
        return sorted(items, key=lambda it: (it['piece'], order.index(it['base']) if it['base'] in order else 99))

    def refresh_songs(self, path=None):
        items = [dict(path=s, label=os.path.splitext(os.path.basename(s))[0].upper(),
                      folder=os.path.basename(os.path.dirname(s)), base='song') for s in self.srcs]
        self.songs.fill(items, self._song_card)
        it = self.songs.pick(path or self.src)
        if it and it['path'] == (path or self.src):
            self.pick_song(it)
        elif not it:
            self.src, self.dst = '', ''
            self.list.clear()
            self.spec.clear()
            self._refresh_info()

    def _song_card(self, it):
        p = it['path']
        n = len(self.song_files(p))
        rm = icon_key('x', lambda _=False, it=it: self.remove([it]), TXT['rm_song'])
        if p == self.running:
            return TXT['sep_now'], []
        if p in self.jobs:
            return TXT['sep_wait'], []
        keys = [icon_key('split', lambda _=False, p=p: self.start([p]), TXT['sep_one'])]
        if n:
            keys.append(icon_key('down', lambda _=False, it=it: self.download([it]), TXT['dl_stems']))
        return (TXT['sep_done'].format(n) if n else TXT['not_sep']), keys + [rm]

    def _song_counts(self):
        sel = self.songs.selected()
        self.bulk_sep.setVisible(bool(sel) and not self.busy)
        self.bulk_dl.setVisible(any(self.song_files(it['path']) for it in sel))
        self.bulk_rm.setVisible(bool(sel))

    def pick_song(self, it):
        """Ver una canción: sus casillas, sus stems (si ya está separada) y su análisis."""
        self.stop_play()
        self.src, self.dst = it['path'], self._dst(it['path'])
        conf = self.conf.setdefault(self.src, dict(stems=set(), extras=set()))
        for keys, chosen in ((self.stem_keys, conf['stems']), (self.voice_keys, conf['extras'])):
            for k, b in keys.items():
                b.blockSignals(True)
                b.setChecked(k in chosen)
                b.blockSignals(False)
        self._voice_enabled(self.stem_keys['voz'].isChecked())
        self.player.tracks, self.player.active = {}, set()
        files = self.song_files(self.src)
        results = {'Stems': {f['base']: f['path'] for f in files if not f['piece']}}
        if any(f['piece'] for f in files):
            results['Batería 6'] = {f['base']: f['path'] for f in files if f['piece']}
        try:
            with open(os.path.join(self.dst, 'analisis.json'), encoding='utf-8') as fh:
                report = json.load(fh)
        except (OSError, ValueError):
            report = None
        self.fill(results if files else {}, report)
        if not self.busy:
            self._refresh_info()

    def _conf_changed(self, *_):
        """Las casillas de SEPARAR y VOZ son de la canción elegida; CALIDAD y ANALIZAR, de todas."""
        if not self.src:
            return
        stems = {k for k, b in self.stem_keys.items() if b.isChecked()}
        extras = {k for k, b in self.voice_keys.items() if b.isChecked()}
        self.conf[self.src] = dict(stems=stems, extras=extras)
        s = settings()
        s.setValue('stems', ','.join(stems))  # la próxima canción que se cargue empieza así
        s.setValue('extras', ','.join(extras))

    # --- descargar stems ya separados ---
    def download(self, items):
        songs = []
        with_wait(lambda: songs.extend(self._pick_list(items)))
        if not songs:
            return
        dlg = PickStems(self, songs)
        if not dlg.exec() or not dlg.chosen():
            return
        s = settings()
        flac, auto, folder = dlg.fmt.value() == 'flac', dlg.auto.isChecked(), s.value('export_dir', '')
        s.setValue('export_fmt', dlg.fmt.value())
        s.setValue('export_auto', 'true' if auto else 'false')
        if not (auto and os.path.isdir(folder)):  # SIEMPRE EN: no pregunta (la 1a vez sí, para saber dónde)
            folder = QFileDialog.getExistingDirectory(self, TXT['save_to'], folder or os.path.expanduser('~'))
            if not folder:
                return
        s.setValue('export_dir', folder)
        pairs, taken = [], set()
        for f in dlg.chosen():  # cada canción en su carpeta; solo se crea lo que lleva archivos
            name = os.path.basename(f['path'])
            if flac and name.lower().endswith('.wav'):
                name = name[:-4] + '.flac'
            target = os.path.join(folder, f['song'], 'bateria_6' if f['piece'] else '', name)
            target = free_name(os.path.normpath(target), taken)
            taken.add(target)
            pairs.append((f['path'], target))
        self.songs.copy(pairs)

    def _pick_list(self, items):
        out = []
        for it in items:
            files = self.song_files(it['path'])
            if not files:
                continue
            dst = self._dst(it['path'])
            try:
                with open(os.path.join(dst, 'analisis.json'), encoding='utf-8') as fh:
                    report = json.load(fh)
            except (OSError, ValueError):
                report = None
            song = os.path.basename(dst)
            out.append((song, [(dict(f, song=song), is_empty(f['path'], report)) for f in files]))
        return out

    def _refresh_info(self, text=None):
        if text is None:
            text = os.path.basename(self.src) if self.src else TXT['empty']
        self.info.setText(text.upper() if text else '')

    def _progress(self):
        """Porcentaje, velocidad y tiempos. Cada paso pesa distinto (engine.WEIGHT); el ritmo se mide en los pasos
        ya terminados y, al empezar, se usa el de la última vez."""
        r = self.run
        if not r or not r['w']:
            return
        W, el = sum(r['w']), time.monotonic() - r['t0']
        base = sum(r['w'][:max(r['m'] - 1, 0)])  # pasos ya terminados de esta canción
        done = sum(map(sum, r['ws'][:r['i']])) + base  # cada canción pesa según sus casillas
        rate = r['tb'] / done if done else settings().value('rate', 0.0, type=float)  # segundos por unidad de peso
        cur = r['w'][r['m'] - 1] if r['m'] else 0
        run = min((el - r['tb']) / rate, 0.95 * cur) if rate else 0  # avance estimado del paso en curso
        total = sum(map(sum, r['ws']))
        frac = min((done + run) / total, 1)
        self.bar.setValue(round(frac * 1000))
        parts = [f'{frac:.0%}']
        audio = r['aud'] + r['dur'] * min((base + run) / W, 1)
        if el >= 5 and audio:
            parts.append(f'VEL x{audio / el:.1f}')
        if rate:
            parts += [f'TOTAL {fmt_time(rate * total)}', f'FALTAN {fmt_time(max(rate * total - el, 0))}']
        else:
            parts.append('CALCULANDO…')
        self.eta.setText('  ·  '.join(parts))

    def _finish_progress(self, ok):
        r, self.run = self.run, None
        self.clock.stop()
        if not r or not r['w']:
            return
        el = time.monotonic() - r['t0']
        parts = ['100%' if ok else '']
        audio = r['aud'] + r['dur']
        if ok and el >= 5 and audio:
            parts.append(f'VEL x{audio / el:.1f}')
        parts.append(f'TOTAL {fmt_time(el)}')
        self.eta.setText('  ·  '.join(p for p in parts if p))
        if ok:
            settings().setValue('rate', el / sum(map(sum, r['ws'])))  # ritmo de esta máquina para la próxima

    def _view(self):
        return self.midi.spec if self.stack.currentWidget() is self.midi else self.spec

    def dragEnterEvent(self, e):
        if any(os.path.isdir(u.toLocalFile()) or u.toLocalFile().lower().endswith(EXTENSIONS)
               for u in e.mimeData().urls()):
            e.acceptProposedAction()
            self._view().drop_hover = True
            self._view().update()

    def dragLeaveEvent(self, e):
        self._view().drop_hover = False
        self._view().update()

    def dropEvent(self, e):
        """Soltar audios (o carpetas) carga en la pestaña abierta, después de confirmar."""
        self.dragLeaveEvent(e)
        paths = [os.path.normpath(u.toLocalFile()) for u in e.mimeData().urls()]
        paths = [p for p in paths if os.path.isdir(p) or p.lower().endswith(EXTENSIONS)]
        if not paths:
            return
        names = [os.path.basename(p) for p in paths]
        ask = (TXT['load_q'].format(names[0]) if len(paths) == 1 else
               TXT['load_n'].format(len(paths)) + '\n\n' + '\n'.join(names[:10]) + ('\n…' if len(names) > 10 else ''))
        if not notice(self, 'load_drop', ask):
            return
        if self.stack.currentWidget() is self.midi:
            self.midi.add(paths)
        else:
            self.set_sources(paths)

    # --- separación ---
    def start(self, srcs):
        if self.busy:
            return warn(self, 'busy_now', TXT['busy_now'])
        analyze = self.analyze.isChecked()
        quality = self.quality.value()
        jobs = [(p, self.conf[p]['stems'], self.conf[p]['extras']) for p in srcs if p in self.conf
                and (self.conf[p]['stems'] or analyze)]
        if not jobs:
            return warn(self, 'nothing', TXT['nothing'])
        mega = sum(any(tip == 'MEGA' and key in st for key, _, tip in STEM_KEYS) for _, st, _ in jobs)
        if mega and not notice(self, 'mega', 'SINTETIZADOR, VIENTO y CUERDAS usan el modelo de 53 instrumentos: '
                               f'mucho más lento ({mega} canción(es)) y la 1a vez baja 1.3 GB.\n\n¿Continuar?'):
            return
        s = settings()
        s.setValue('quality', quality)
        s.setValue('analyze', 'true' if analyze else 'false')
        self.stop_play()
        self.busy, self.cancelled = True, False
        self.cancel_btn.show()
        self.jobs, self.running = [p for p, _, _ in jobs], None
        ws = [engine.step_weights(st, ex, quality, analyze, self._dst(p), p) or [1] for p, st, ex in jobs]
        self.run = dict(t0=time.monotonic(), i=0, n=len(jobs), ws=ws, w=ws[0], m=0, tb=0.0, aud=0.0, dur=0.0)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.eta.setText('0%  ·  CALCULANDO…')
        self.clock.start()
        self.refresh_songs()
        self._refresh_info('')
        bg(lambda: self._work(jobs, quality, analyze, self.hw))

    def _work(self, jobs, quality, analyze, hw):
        """Canción por canción con sus casillas, cada una en un proceso aparte (engine.py) que CANCELAR puede matar;
        si una falla se anota en error.log y se sigue con la siguiente."""
        import librosa
        emit = self.bridge.msg.emit
        last, failed = None, []
        for i, (src, stems, extras) in enumerate(jobs):
            if self.cancelled:
                break
            try:
                dur = librosa.get_duration(path=src)
            except Exception:
                dur = 0.0  # sin duración solo se pierde la velocidad
            emit('song', (i, len(jobs), src, engine.step_weights(stems, extras, quality, analyze, self._dst(src), src) or [1], dur))
            tmp = tempfile.mkdtemp(prefix='rds_')  # temporales del proceso: se borran aunque se cancele
            try:
                dst = self._dst(src)
                os.makedirs(dst, exist_ok=True)
                self.proc = subprocess.Popen(
                    [sys.executable, engine.__file__, json.dumps([src, dst, sorted(stems), sorted(extras), quality, analyze, hw])],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding='utf-8',
                    env=dict(os.environ, TMP=tmp, TEMP=tmp, TMPDIR=tmp),
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if self.cancelled:  # CANCELAR justo antes de que existiera el proceso
                    self.cancel()
                err = None
                for line in self.proc.stdout:
                    kind, val = json.loads(line)
                    if kind == 'error':
                        err = val
                    else:
                        emit(kind, val)
                code = self.proc.wait()
                if self.cancelled:
                    break
                if err or code:
                    failed.append((src, err or f'La separación se cerró sola (código {code}).'))
                else:
                    last = src
                    emit('saved', src)
            except Exception:
                failed.append((src, traceback.format_exc()))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        emit('done', (last, failed))

    def cancel(self):
        """Mata el proceso de separación con todo lo que haya abierto. Lo ya separado de esa canción no se anota en
        separacion.json, así que se vuelve a separar la próxima vez."""
        self.cancelled = True
        p = getattr(self, 'proc', None)
        if p and p.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                p.kill()

    def on_msg(self, kind, val):
        if kind == 'hw':
            self.hw = val
            gpu = val['kind'] != 'cpu'
            name = val['name'].replace('NVIDIA ', '').replace('GeForce ', '').upper()
            spec = (f"{name} · {val['vram']:.0f} GB" + (' · FP16' if val['fp16'] else '') if gpu
                    else f"{TXT['cpu']} · {val['cores']} NÚCLEOS · {val['ram']:.0f} GB RAM · {TXT['slow']}")
            self.device.setText(spec)
            self.device.setObjectName('info' if gpu else 'alert')
            self.device.style().unpolish(self.device)  # vuelve a leer el estilo con el nuevo nombre
            self.device.style().polish(self.device)
            self.device.updateGeometry()  # el recuadro rojo de la alerta es más ancho
            if not gpu and settings().value('quality') is None:
                self.quality.set('fast')  # sin GPU, MÁX tarda demasiado: arranca en RÁPIDA la primera vez
            self._refresh_info()
        elif kind == 'song':
            i, n, src, w, dur = val
            self.song = f'{i + 1}/{n} · ' if n > 1 else ''
            self.running = src
            self.refresh_songs()
            r = self.run
            r['aud'] += r['dur'] if i else 0  # audio de las canciones ya terminadas
            r.update(i=i, w=w, dur=dur, m=0, tb=time.monotonic() - r['t0'])
            self._progress()
        elif kind == 'log':
            self._refresh_info(self.song + val)
        elif kind == 'yt':
            self.set_sources([val])
            if not self.busy:
                self._refresh_info()
        elif kind == 'yt_error':
            log_error(val)
            warn(self, 'error', engine.explain(val))
        elif kind == 'step':
            self.run['m'] += 1
            self.run['tb'] = time.monotonic() - self.run['t0']
            self._refresh_info(self.song + val)
            self._progress()
        elif kind == 'saved':
            self.history([val])
            self.jobs = [p for p in self.jobs if p != val]
        elif kind == 'error':
            self.busy = False
            self.clock.stop()
            self.run = None
            self.bar.setRange(0, 1)
            self._refresh_info(TXT['error'])
            log_error(val)
            warn(self, 'error', engine.explain(val))
        elif kind == 'done':
            last, failed = val
            self.busy = False
            self.cancel_btn.hide()
            self.bar.setValue(0 if self.cancelled else self.bar.maximum())
            self._finish_progress(not failed and not self.cancelled)
            for src, tb in failed:
                log_error(f'{src}\n{tb}')
            self.jobs, self.running = [], None
            self.refresh_songs(last)  # se ve la última que terminó
            note = f"  ·  {TXT['failed'].format(len(failed))}" if failed else ''
            self._refresh_info(TXT['cancelled'] if self.cancelled else TXT['done'] + note if last else TXT['error'] + note)
            if failed and not last:
                warn(self, 'error', engine.explain(failed[-1][1]))
            if self.stack.currentIndex():
                self.stack.currentWidget().refresh()

    def fill(self, results, report):
        self.report = report
        self.list.blockSignals(True)  # las casillas disparan itemChanged al crearse
        self.list.clear()
        stems = (report or {}).get('stems', {})
        groups = {TXT['mix']: {'original': self.src}, **results}
        self.kit_plays = 'bateria' not in results.get('Stems', {})  # sin BATERÍA, sus piezas completan la canción
        try:
            with open(os.path.join(self.dst, 'mezcla.json'), encoding='utf-8') as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self.player.solo = set()
        for g, items in groups.items():
            head = QListWidgetItem(g.upper())
            head.setFlags(Qt.NoItemFlags)
            self.list.addItem(head)
            for s, path in items.items():
                name = 'Mezcla original / original' if g == TXT['mix'] else f'{g} / {s}'
                d = stems.get(name)
                it = QListWidgetItem()
                it.setData(Qt.UserRole, (name, path))
                it.setData(Qt.UserRole + 1, LABELS.get(s, s.upper()) + (f"  · {TXT['silent']}" if d and d['casi_silencio'] else ''))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
                it.setCheckState(Qt.Checked if self._plays(g, s, 'all') else Qt.Unchecked)
                self.player.mix[path] = tuple(saved.get(name, (0, 0)))
                self._mark(it)
                self.list.addItem(it)
        self.list.blockSignals(False)
        first = next((self.list.item(i) for i in range(self.list.count()) if self.list.item(i).flags()), None)
        self.list.setCurrentItem(first)
        self._show_levels(self._selected_path())
        if not report:
            self.spec.clear(TXT['no_analysis'])

    def show_selected(self, item=None, _=None):
        if not item or not item.data(Qt.UserRole):
            return
        name, path = item.data(Qt.UserRole)
        self._show_levels(path)
        d = (self.report or {}).get('stems', {}).get(name)
        for v in self.values.values():
            v.setText('—')
        if not d:
            return
        self.spec.show_stem(d)
        r = self.report
        pulse = r.get('pulso') or {}
        self.values['tempo'].setText(f"{r['tempo_bpm']} BPM" + (f" · {pulse['compas']}/4" if pulse.get('compas') else '')
                                     + (' · VARIABLE' if pulse and not pulse['estable'] else ''))
        self.values['key'].setText(r['tonalidad'].upper())
        self.values['chords'].setText('  '.join(c for _, c in r.get('acordes', [])[:12]) or '—')
        if d['casi_silencio']:
            self.values['rms'].setText(f"{d['rms_dBFS']} DBFS · {TXT['silent']}")
            return
        self.values['peak'].setText(f"{d['pico_dBFS']} DBFS")
        self.values['rms'].setText(f"{d['rms_dBFS']} DBFS")
        self.values['range'].setText(f"{hz(d['rango_hz'][0])} – {hz(d['rango_hz'][1])} HZ")
        self.values['centroid'].setText(f"{hz(d['centroide_hz'])} HZ")
        self.values['peaks'].setText('  '.join(f"{p['nota']} {hz(p['hz'])}" for p in d['picos']) or '—')

    def _selected_path(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole)[1] if item and item.data(Qt.UserRole) else None

    # --- reproducción ---
    def _checked(self):
        return [self.list.item(i).data(Qt.UserRole)[1] for i in range(self.list.count())
                if self.list.item(i).data(Qt.UserRole) and self.list.item(i).checkState() == Qt.Checked]

    def toggle_play(self):
        if self.player.playing:
            return self.stop_play(keep_pos=True)
        paths = self._checked() or [p for p in [self._selected_path() or self.src] if p]
        if not paths:
            return
        try:
            with_wait(lambda: self.player.load(paths))
            self.player.active = set(paths)
            if self.player.pos >= self.player.length:
                self.player.pos = 0
            self.player.play()
        except Exception:
            log_error(traceback.format_exc())
            return warn(self, 'no_audio', TXT['no_audio'])
        self.play_btn.set_glyph('stop')
        self.timer.start()

    def stop_play(self, keep_pos=False):
        self.player.stop()
        if not keep_pos:
            self.player.pos = 0
        self.timer.stop()
        self.play_btn.set_glyph('play')
        self.spec.set_playhead(self.player.pos / engine.SR if keep_pos else None)

    def _tick(self):
        if not self.player.playing:
            return self.stop_play()
        self.spec.set_playhead(self.player.pos / engine.SR)

    def seek(self, secs):
        self.player.pos = int(secs * engine.SR)
        self.spec.set_playhead(secs)

    def mix_changed(self, item):
        """Marcar o desmarcar un stem lo suma o lo quita de lo que suena, sin detener."""
        if not item.data(Qt.UserRole):
            return
        path = item.data(Qt.UserRole)[1]
        if item.checkState() == Qt.Checked:
            with_wait(lambda: self.player.load([path]))
            self.player.active.add(path)
        else:
            self.player.active.discard(path)

    def open_dir(self):
        path = self._selected_path()
        target = os.path.dirname(path) if path and path != self.src else self.dst
        if target and os.path.isdir(target):
            _open(target)

    def closeEvent(self, e):
        self.cancel()  # si no, la separación sigue sola sin ventana
        self.player.stop()
        self.midi.player.stop()
        super().closeEvent(e)


def slider(lo, hi, value, fmt):
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setFocusPolicy(Qt.NoFocus)
    label = QLabel()
    label.setObjectName('value')
    label.setFixedWidth(64)
    s.valueChanged.connect(lambda v: label.setText(fmt(v)))
    s.setValue(value)
    label.setText(fmt(value))
    return s, label


# =====================================================================================
# Pestaña MIDI: módulo de sonidos (mosaico o lista) con convertir, descargar y eliminar por MIDI,
# espectrograma con el rango del TIPO, y los controles para afinar la conversión
# =====================================================================================

def dim(text):
    label = QLabel(text)
    label.setObjectName('dim')
    return label


def icon_key(glyph, fn, tip):
    k = Key(icon=glyph, fn=fn, width=28)
    k.setToolTip(tip)
    return k


def auto_kind(base):
    return 'bajo' if base == 'bajo' else 'melodia' if base.startswith(('voz', 'coros')) else 'todo'


class Card(QFrame):
    """Un sonido: nombre, carpeta donde está (= la canción), si ya tiene MIDI, y sus teclas.
    Clic en la tarjeta = verlo."""

    def __init__(self, it, tiles, status, keys, on_click):
        super().__init__()
        self.setObjectName('card')
        self.on_click = on_click
        name, folder, st = Elide(it['label']), Elide(it['folder']), Elide(status)
        name.setObjectName('value')
        folder.setObjectName('dim')
        st.setObjectName('dim')
        for w in (name, folder, st):
            w.setToolTip(it['path'])
        icons = QHBoxLayout()
        icons.setSpacing(4)
        icons.addStretch()
        for k in keys:
            icons.addWidget(k)
        if tiles:
            v = QVBoxLayout(self)
            v.setContentsMargins(10, 8, 6, 6)
            v.setSpacing(1)
            for w in (name, folder, st):
                v.addWidget(w)
            v.addStretch()
            v.addLayout(icons)
        else:
            top = QHBoxLayout()  # nombre y estado; debajo la carpeta a todo lo ancho, para que se lea la canción
            top.setSpacing(8)
            top.addWidget(name, 3)
            top.addWidget(st, 2)
            v = QVBoxLayout()
            v.setSpacing(1)
            v.addLayout(top)
            v.addWidget(folder)
            h = QHBoxLayout(self)
            h.setContentsMargins(10, 3, 6, 3)
            h.addLayout(v, 1)
            h.addLayout(icons)

    def mousePressEvent(self, e):
        self.on_click(e.modifiers())


class Module(QWidget):
    """Mosaico o lista de tarjetas con SELECCIONAR (varias) y descargas con porcentaje que se desvanece.
    Lo usan STEMS (canciones) y MIDI (sonidos); cada pestaña decide qué dice y qué teclas lleva cada tarjeta."""
    TILE = QSize(142, 108)

    def __init__(self, key, bulk_keys, on_pick, on_selection):
        super().__init__()
        self.key, self.on_pick, self.on_selection, self.cur, self.fade = key, on_pick, on_selection, None, None
        self.bridge = Bridge()
        self.bridge.msg.connect(self._copy_msg)
        self.view = Choice((('tiles', TXT['tiles']), ('rows', TXT['rows'])))
        self.view.set(settings().value(key, 'tiles'))
        self.view.group.buttonClicked.connect(lambda _: self.fill(self.items, self.card_for))
        self.multi = Key(TXT['multi'], self._multi, checkable=True)
        self.all_btn = Key(TXT['all'], self.select_all)
        self.sel_count = dim('')
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        row1.addWidget(self.view)
        row1.addStretch()
        row1.addWidget(self.multi)
        self.bulk = QWidget()
        row2 = QHBoxLayout(self.bulk)
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(4)
        row2.addWidget(self.all_btn)
        row2.addWidget(self.sel_count)
        row2.addStretch()
        for k in bulk_keys:
            row2.addWidget(k)
        self.grid = Reticled()
        self.grid.setObjectName('tiles')
        self.grid.setSelectionMode(QListWidget.MultiSelection)
        self.grid.setFocusPolicy(Qt.NoFocus)
        self.grid.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setSpacing(3)
        self.grid.itemSelectionChanged.connect(self._counts)
        self.progress = QWidget()
        pl = QHBoxLayout(self.progress)
        pl.setContentsMargins(0, 0, 0, 0)
        self.pbar = Progress()
        self.pbar.setTextVisible(False)
        self.pbar.setRange(0, 100)
        self.pct = QLabel('0%')
        self.pct.setObjectName('value')
        self.pct.setFixedWidth(40)
        pl.addWidget(self.pbar, 1)
        pl.addWidget(self.pct)
        self.opacity = QGraphicsOpacityEffect(self.progress)
        self.progress.setGraphicsEffect(self.opacity)
        self.progress.hide()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(row1)
        lay.addWidget(self.bulk)
        lay.addWidget(self.grid, 1)
        lay.addWidget(self.progress)
        self.items, self.card_for = [], None
        self.bulk.hide()

    def fill(self, items, card_for):
        """card_for(it) -> (estado, teclas). La tarjeta actual se conserva por su ruta."""
        keep = {i.data(Qt.UserRole)['path'] for i in self.grid.selectedItems()} if self.multi.isChecked() else set()
        self.items, self.card_for = items, card_for
        tiles = self.view.value() == 'tiles'
        settings().setValue(self.key, self.view.value())
        self.grid.blockSignals(True)
        self.grid.clear()
        self.grid.setViewMode(QListView.IconMode if tiles else QListView.ListMode)
        self.grid.setMovement(QListView.Static)  # IconMode deja arrastrar tarjetas: aquí no
        self.grid.setWrapping(tiles)
        self.grid.setDragEnabled(False)
        for it in items:
            status, keys = card_for(it)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, it)
            item.setSizeHint(self.TILE if tiles else QSize(200, 44))
            self.grid.addItem(item)
            self.grid.setItemWidget(item, Card(it, tiles, status, [k for k in keys if k],
                                               lambda mods, item=item: self.click(item, mods)))
            item.setSelected(it['path'] in keep or (not self.multi.isChecked() and it['path'] == self.cur))
        self.grid.blockSignals(False)
        self._counts()

    def click(self, item, mods):
        if self.multi.isChecked() or mods & (Qt.ControlModifier | Qt.ShiftModifier):
            item.setSelected(not item.isSelected())
        else:
            self.grid.clearSelection()
            item.setSelected(True)
        it = item.data(Qt.UserRole)
        if it['path'] != self.cur:
            self.cur = it['path']
            self.on_pick(it)

    def pick(self, path):
        """Elige por ruta (o la primera si ya no está). Devuelve la tarjeta elegida o None."""
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            if item.data(Qt.UserRole)['path'] == path:
                self.cur = path
                if not self.multi.isChecked():
                    self.grid.clearSelection()
                    item.setSelected(True)
                return item.data(Qt.UserRole)
        if self.grid.count():
            self.cur = None
            self.click(self.grid.item(0), Qt.NoModifier)
            return self.grid.item(0).data(Qt.UserRole)
        self.cur = None
        return None

    def _multi(self, on):
        self.bulk.setVisible(on)
        if not on:
            self.grid.clearSelection()
            for i in range(self.grid.count()):
                self.grid.item(i).setSelected(self.grid.item(i).data(Qt.UserRole)['path'] == self.cur)
        self._counts()

    def select_all(self):
        on = len(self.grid.selectedItems()) < self.grid.count()
        for i in range(self.grid.count()):
            self.grid.item(i).setSelected(on)

    def selected(self):
        return [i.data(Qt.UserRole) for i in self.grid.selectedItems()]

    def _counts(self):
        self.sel_count.setText(TXT['sel'].format(len(self.grid.selectedItems())))
        self.on_selection()

    def copy(self, pairs):
        """Copia [(origen, destino)] en segundo plano; crea carpetas solo si llevan archivos. Un destino .flac de un
        .wav se convierte (sin pérdida)."""
        if self.fade:
            self.fade.stop()
        self.opacity.setOpacity(1)
        self.pbar.setValue(0)
        self.pct.setText('0%')
        self.progress.show()
        emit = self.bridge.msg.emit

        def work():
            try:
                total, done = sum(os.path.getsize(a) for a, _ in pairs) or 1, 0
                for a, b in pairs:
                    os.makedirs(os.path.dirname(b), exist_ok=True)
                    if b.endswith('.flac') and not a.lower().endswith('.flac'):
                        y, sr = sf.read(a, dtype='int32')  # enteros: los 24 bits pasan tal cual
                        sf.write(b, y, sr, subtype='PCM_24')
                        done += os.path.getsize(a)
                        emit('pct', done * 100 // total)
                        continue
                    with open(a, 'rb') as f, open(b, 'wb') as g:
                        while chunk := f.read(1 << 20):
                            g.write(chunk)
                            done += len(chunk)
                            emit('pct', done * 100 // total)
                emit('copied', None)
            except Exception:
                emit('copy_error', traceback.format_exc())
        threading.Thread(target=work, daemon=True).start()

    def _copy_msg(self, kind, val):
        if kind == 'pct':
            self.pbar.setValue(val)
            self.pct.setText(f'{val}%')
            return
        if kind == 'copy_error':
            self.progress.hide()
            log_error(val)
            return warn(self, 'error', engine.explain(val))
        self.fade = QPropertyAnimation(self.opacity, b'opacity', self)
        self.fade.setStartValue(1.0)
        self.fade.setEndValue(0.0)
        self.fade.setDuration(900)
        self.fade.setEasingCurve(QEasingCurve.InOutQuad)
        self.fade.finished.connect(self.progress.hide)
        QTimer.singleShot(400, self.fade.start)  # que se alcance a ver el 100%


class PickStems(QDialog):
    """Antes de descargar: qué stems de cada canción. Los casi vacíos vienen sin marcar."""

    def __init__(self, parent, songs):
        super().__init__(parent)
        self.setWindowTitle(TXT['pick_title'])
        self.resize(420, 520)
        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.NoFocus)
        for song, files in songs:
            head = QListWidgetItem(song.upper())
            head.setFlags(Qt.NoItemFlags)
            self.list.addItem(head)
            for it, empty in files:
                row = QListWidgetItem(it['label'] + (f"  · {TXT['silent']}" if empty else ''))
                row.setData(Qt.UserRole, it)
                row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                row.setCheckState(Qt.Unchecked if empty else Qt.Checked)
                self.list.addItem(row)
        self.list.itemClicked.connect(
            lambda i: i.setCheckState(Qt.Unchecked if i.checkState() == Qt.Checked else Qt.Checked) if i.flags() else None)
        keys = QHBoxLayout()
        keys.addWidget(Key(TXT['all'], lambda: self._all(Qt.Checked)))
        keys.addWidget(Key(TXT['none'], lambda: self._all(Qt.Unchecked)))
        keys.addStretch()
        keys.addWidget(Key(TXT['cancel'], self.reject))
        keys.addWidget(Key(TXT['download'], self.accept))
        s = settings()
        self.fmt = Choice((('wav', 'WAV'), ('flac', 'FLAC')), width=64)  # FLAC: mismo audio de 24 bits, ~mitad de tamaño
        self.fmt.set(s.value('export_fmt', 'wav'))
        folder = s.value('export_dir', '')
        self.auto = QCheckBox(TXT['always_in'].format(os.path.basename(folder).upper()) if folder else TXT['always_pick'])
        self.auto.setToolTip(folder)
        self.auto.setChecked(s.value('export_auto', 'false') == 'true')
        opts = QHBoxLayout()
        opts.addWidget(self.fmt)
        opts.addWidget(self.auto, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(dim(TXT['pick_hint']))
        lay.addWidget(self.list, 1)
        lay.addLayout(opts)
        lay.addLayout(keys)

    def _all(self, state):
        for i in range(self.list.count()):
            if self.list.item(i).flags():
                self.list.item(i).setCheckState(state)

    def chosen(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).flags() and self.list.item(i).checkState() == Qt.Checked]


def is_empty(path, report):
    """Casi en silencio (-60 dBFS RMS): del análisis si existe; si no, se mide."""
    for d in (report or {}).get('stems', {}).values():
        if os.path.normpath(d.get('ruta', '')) == os.path.normpath(path):
            return d['casi_silencio']
    try:
        y = sf.read(path, dtype='float32')[0]
        return 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12) < -60
    except Exception:
        return False


class MidiPage(QWidget):

    def __init__(self, main):
        super().__init__()
        self.main, self.busy, self.cur = main, False, None
        self.opened, self.views, self.notes = [], {}, {}  # abiertos aquí; espectrogramas; .mid -> notas
        self.player = Player()
        self.bridge = Bridge()
        self.bridge.msg.connect(self.on_msg)
        s = settings()
        self.custom = (s.value('midi_lo', 80.0, type=float), s.value('midi_hi', 1400.0, type=float))
        self.pulse, self.scale, self.first = None, 1, None  # pulso de la canción elegida y lo que se le corrigió

        # --- módulo de sonidos ---
        self.bulk_convert = icon_key('note', lambda: self.convert(self.selected(False)), TXT['convert_sel'])
        self.bulk_dl = icon_key('down', lambda: self.download(self.selected(True)), TXT['dl_sel'])
        self.bulk_rm = icon_key('x', lambda: self.delete(self.mod.selected()), TXT['rm_sel'])
        self.mod = Module('midi_view', (self.bulk_convert, self.bulk_dl, self.bulk_rm), self.pick, self._counts)
        module = self.mod
        module.setFixedWidth(318)

        # --- espectrograma y transporte ---
        self.spec = SpecView()
        self.spec.on_seek = self.seek
        self.spec.on_band = self._band_moved
        self.play_btn = Key(icon='play', fn=self.toggle_play, width=36)
        self.play_btn.setObjectName('phone')  # tecla principal: azul con marco crema
        self.play_btn.set_glyph('play')
        self.info = Elide(TXT['midi_none'])
        self.info.setObjectName('info')
        self.info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.bar = Progress()
        self.bar.setFixedWidth(160)
        self.bar.setRange(0, 1)
        status = QHBoxLayout()
        status.setContentsMargins(6, 4, 8, 4)
        status.setSpacing(10)
        status.addWidget(self.play_btn)
        for k in zoom_keys(self.spec):
            status.addWidget(k)
        status.addWidget(self.info, 1)
        status.addWidget(self.bar)
        sheet = Key(TXT['sheet'], self.sheets)
        sheet.setToolTip('PDF con la partitura (y tablatura si es guitarra o bajo) y MusicXML, junto al MIDI.\n'
                         'Usa MuseScore 4. Sale mejor con CUANTIZAR. Con SELECCIÓN MÚLTIPLE, una por cada marcado.')
        status.addWidget(sheet)
        status.addWidget(Key(TXT['show'], self.open_dir))
        display = QFrame()
        display.setObjectName('display')
        dl = QVBoxLayout(display)
        dl.setContentsMargins(1, 1, 1, 1)
        dl.setSpacing(0)
        dl.addWidget(self.spec, 1)
        dl.addWidget(self.spec.scroll)
        dl.addWidget(rule())
        dl.addLayout(status)
        middle = QHBoxLayout()
        middle.setSpacing(8)
        middle.addWidget(module)
        middle.addWidget(display, 1)

        # --- controles ---
        self.kind = Choice((('todo', 'TODO'), ('melodia', 'MELODÍA'), ('bajo', 'BAJO'), ('custom', 'CUSTOM')),
                           width=88)
        self.kind.group.buttonClicked.connect(lambda _: self._band())
        for k, tip in (('todo', 'Acordes y varias notas a la vez: piano, guitarra, teclados.'),
                       ('melodia', 'Una línea: voz, solos, vientos (80 Hz – 1.4 kHz).'),
                       ('bajo', 'Solo graves (30–400 Hz).'),
                       ('custom', 'Tu propio rango: arrastra las pestañas de Hz sobre el espectrograma.')):
            self.kind.keys[k].setToolTip(tip)
        self.sens, sens_v = slider(0, 100, s.value('midi_sens', 50, type=int), lambda v: f'{v}%')
        self.sens.setToolTip('Más alto: detecta notas suaves (y más ruido). Más bajo: solo las notas claras.')
        self.min_len, min_v = slider(30, 500, s.value('midi_min', 128, type=int), lambda v: f'{v} MS')
        self.min_len.setToolTip('Las notas más cortas que esto se descartan.')
        # pasos por tiempo: 2 = corcheas, 3 = tresillos de corchea...; -1 = la rejilla en que caen las notas
        self.qgrid = Choice(((0, 'LIBRE'), (-1, 'AUTO'), (2, '1/8'), (3, '1/8T'), (4, '1/16'), (6, '1/16T'), (8, '1/32')),
                            width=56)
        self.qgrid.set(s.value('midi_q', 0, type=int))
        self.qgrid.setToolTip('Ajusta el inicio y el final de cada nota a la rejilla del pulso, aunque el tempo cambie.\n'
                              'AUTO elige la rejilla en que caen las notas (también tresillos, T).')
        self.qgrid.group.buttonClicked.connect(lambda _: self.strength.setEnabled(self.qgrid.value() != 0))
        self.strength, strength_v = slider(10, 100, s.value('midi_strength', 100, type=int), lambda v: f'{v}%')
        self.strength.setToolTip('Cuánto se acercan las notas a la rejilla: 100% del todo; menos conserva algo del toque.')
        self.strength.setEnabled(self.qgrid.value() != 0)
        self.tempo = QDoubleSpinBox()
        self.tempo.setRange(20, 400)
        self.tempo.setDecimals(1)
        self.tempo.setSuffix(' BPM')
        self.tempo.setValue(120)
        self.tempo.setFixedWidth(96)
        self.tempo.setButtonSymbols(QDoubleSpinBox.NoButtons)  # se escribe o se cambia con la rueda
        self.tempo.setToolTip('Tempo detectado. Si cambia en la canción, el .mid lo sigue y las barras caen en los\n'
                              'tiempos fuertes. Escribir otro deja un tempo fijo.')
        halve = Key('÷2', lambda: self._rescale(0.5), width=40)
        halve.setToolTip('El detector contó cada corchea como un tiempo: tempo a la mitad.')
        double = Key('×2', lambda: self._rescale(2), width=40)
        double.setToolTip('El detector contó cada blanca como un tiempo: tempo al doble.')
        self.meter = QSpinBox()
        self.meter.setRange(0, 12)
        self.meter.setSpecialValueText('—')
        self.meter.setSuffix('/4')
        self.meter.setFixedWidth(56)
        self.meter.setButtonSymbols(QSpinBox.NoButtons)
        self.meter.setToolTip('Tiempos por compás. — = sin compás (el DAW pone 4/4).')
        self.here = Key(TXT['here'], self._first_here, width=96)
        self.here.setToolTip('Pon la reproducción en un tiempo fuerte (el 1 de un compás) y haz clic: ahí va una barra.')
        self.rests = Choice(((0.0, 'NO'), (0.25, '1/16'), (0.5, '1/8'), (1.0, 'TIEMPO')), width=60)
        self.rests.set(s.value('midi_fill', 0.0, type=float))
        self.rests.setToolTip('Alarga cada nota hasta la siguiente si el silencio entre ellas dura a lo más esto.\n'
                              'Evita los silencios cortos que el editor de partituras escribiría.')
        self.trim = Key(TXT['trim'], checkable=True, width=128)
        self.trim.setChecked(s.value('midi_trim', 'false') == 'true')
        self.trim.setToolTip('Quita los compases vacíos antes de la primera nota. El .mid ya no empieza donde la canción.')
        self.bends = Key(TXT['keep'], checkable=True, width=96)
        self.bends.setChecked(s.value('midi_bends', 'true') == 'true')
        self.bends.setToolTip('Guarda las desafinaciones y glissandos como pitch bend. Apágalo para notas fijas.')
        plate = panel()
        grid = QGridLayout(plate)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        sens_row = QHBoxLayout()
        for w in (dim('−'), self.sens, dim('+'), sens_v):
            sens_row.addWidget(w)
        min_row = QHBoxLayout()
        min_row.addWidget(self.min_len)
        min_row.addWidget(min_v)
        left = ((TXT['kind'], self.kind), (TXT['sens'], sens_row), (TXT['min_len'], min_row), (TXT['bends'], self.bends))
        strength_row, tempo_row, rest_row = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        for row, ws in ((strength_row, (self.strength, strength_v)),
                        (tempo_row, (self.tempo, halve, double, section(TXT['meter']), self.meter, self.here)),
                        (rest_row, (self.rests, self.trim))):
            for w in ws:
                row.addWidget(w)
        tempo_row.addStretch()
        rest_row.addStretch()
        right = ((TXT['grid'], self.qgrid), (TXT['strength'], strength_row), (TXT['tempo'], tempo_row),
                 (TXT['rests'], rest_row))
        for col, rows in ((0, left), (3, right)):
            for i, (label, w) in enumerate(rows):
                grid.addWidget(section(label), i, col)
                if isinstance(w, QHBoxLayout):
                    w.setSpacing(10)
                    grid.addLayout(w, i, col + 1)
                else:
                    grid.addWidget(w, i, col + 1, Qt.AlignLeft)
        grid.addWidget(rule(vertical=True), 0, 2, 4, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addLayout(middle, 1)
        lay.addWidget(plate)
        self.timer = QTimer(self, interval=30, timeout=self._tick)

    # --- qué hay: abiertos aquí y stems de las canciones separadas ---
    def sources(self):
        def folder(it):  # la carpeta donde está; una pieza de BATERÍA 6 muestra la de la canción
            return os.path.basename(it['dst'] if it.get('piece') else os.path.dirname(it['path']))
        items = [dict(it, opened=True) for it in self.opened]
        stems = [it for it in self.main.library() if it['ext'] == '.wav']
        for src in dict.fromkeys(it['src'] for it in stems):
            # la mezcla original también se puede convertir
            items.append(dict(path=os.path.normpath(src), label=TXT['mix'], src=src, dst=self.main._dst(src),
                              base='', piece=False))
            items += [dict(it, label=('BATERÍA 6 · ' if it['piece'] else '') + it['label'])
                      for it in stems if it['src'] == src]
        return [dict(it, folder=folder(it)) for it in items]

    def mid_of(self, it):
        """Dónde queda (o quedaría) su .mid. Las piezas de BATERÍA 6 comparten el MIDI del kit."""
        kit = self._kit(it)
        if kit:
            return os.path.join(kit, 'bateria.mid')
        if not it['base']:  # la mezcla: su .mid va en la carpeta de stems
            return os.path.join(it['dst'], os.path.splitext(os.path.basename(it['path']))[0] + '.mid')
        return os.path.splitext(it['path'])[0] + '.mid'

    def notes_of(self, it):
        """Notas del .mid en disco (se leen una vez; convertir o borrar las renueva)."""
        mid = self.mid_of(it)
        if not os.path.exists(mid):
            self.notes.pop(mid, None)
            return None
        if mid not in self.notes:
            try:
                self.notes[mid] = engine.read_midi(mid)
            except Exception:
                return None
        return self.notes[mid]

    def _kit(self, it):
        """Carpeta de BATERÍA 6 si el sonido es batería (una pieza o la batería completa con piezas al lado)."""
        kit = os.path.join(it['dst'], 'bateria_6')
        is_drum = it.get('piece') or it['base'] == 'bateria'
        return kit if is_drum and os.path.isdir(kit) else None

    def _no_notes(self, it):
        return it['base'] == 'bateria' and not self._kit(it)

    def refresh(self):
        self.mod.fill(self.sources(), self._card)
        prev = self.cur['path'] if self.cur else None
        it = self.mod.pick(prev)  # si ya no está, elige la primera (y esa se muestra sola)
        if it and it['path'] == prev:
            self.cur = it
            self._show()
        elif not it:
            self.cur = None
            self.spec.clear()
            self.info.setText(TXT['midi_none'])

    def _card(self, it):
        notes = self.notes_of(it)
        drums = bool(self._kit(it))
        rm = (icon_key('x', lambda _=False, it=it: self.delete([it]),
                       TXT['rm_opened'] if it.get('opened') else TXT['rm_audio']) if it['base'] else None)
        if self._no_notes(it):
            return TXT['no_drums_short'], [rm]
        if notes is None:
            return TXT['no_midi'], [icon_key('note', lambda _=False, it=it: self.convert([it]), TXT['convert_one']), rm]
        return TXT['hits' if drums else 'notes'].format(len(notes)), [
            icon_key('note', lambda _=False, it=it: self.convert([it]), TXT['reconvert']),
            icon_key('down', lambda _=False, it=it: self.download([it]), TXT['dl']),
            icon_key('x', lambda _=False, it=it: self.delete([it]), TXT['rm'])]

    def open_dialog(self):
        exts = ' '.join('*' + e for e in EXTENSIONS)
        last = self.opened[-1]['path'] if self.opened else self.main.src
        paths, _ = QFileDialog.getOpenFileNames(self, TXT['open'], os.path.dirname(last), f'Audio ({exts})')
        self.add(paths)

    def folder_dialog(self):
        """Todos los audios de una carpeta (sin subcarpetas), después de confirmar cuántos son."""
        last = self.opened[-1]['path'] if self.opened else self.main.src
        folder = QFileDialog.getExistingDirectory(self, TXT['batch'], os.path.dirname(last))
        if not folder:
            return
        n = sum(f.lower().endswith(EXTENSIONS) for f in os.listdir(folder))
        if n and notice(self, 'load_folder_midi', TXT['load_folder'].format(n)):
            self.add([folder])

    def add(self, paths):
        """Audios sueltos (o los de una carpeta) para convertir, aparte de las canciones de STEMS."""
        files = []
        for p in map(os.path.normpath, paths):
            if os.path.isdir(p):
                files += sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(EXTENSIONS))
            elif p.lower().endswith(EXTENSIONS):
                files.append(p)
        known = {it['path'] for it in self.opened}
        for p in files:
            if p in known:
                continue
            folder = os.path.dirname(p)
            piece = os.path.basename(folder).lower() == 'bateria_6'  # una pieza de BATERÍA 6: su kit está al lado
            base = os.path.splitext(os.path.basename(p))[0]
            self.opened.append(dict(path=p, label=base.upper(), src=p, base=base.lower(), piece=piece,
                                    dst=os.path.dirname(folder) if piece else folder))
        if files:
            self.cur = dict(path=files[0])
            self.refresh()

    # --- selección ---
    def pick(self, it):
        self.cur = it
        self.stop_play()
        self.player.tracks.clear()
        _, tempo, self.pulse = self._report(it['dst'])
        self.scale, self.first = 1, None
        self.tempo.setValue(tempo or 120.0)
        self.meter.setValue((self.pulse or {}).get('compas') or 0)
        self.here.setText(TXT['here'])
        if self.kind.value() != 'custom':
            self.kind.set(auto_kind(it['base']))
        self._show()

    def selected(self, converted):
        """Los marcados que ya tienen MIDI (converted=True) o que todavía no (False)."""
        return [it for it in self.mod.selected()
                if not self._no_notes(it) and (self.notes_of(it) is not None) == converted]

    def _counts(self):
        self.bulk_convert.setVisible(bool(self.selected(False)))
        self.bulk_dl.setVisible(bool(self.selected(True)))
        self.bulk_rm.setVisible(any(it['base'] for it in self.mod.selected()))

    # --- lo que se ve ---
    def _report(self, dst):
        """analisis.json de la canción: ruta -> datos del stem, el tempo y el pulso (beat-this; None en análisis
        viejos). Se lee cada vez: pudo volver a separarse."""
        try:
            with open(os.path.join(dst, 'analisis.json'), encoding='utf-8') as f:
                r = json.load(f)
            return {os.path.normpath(d['ruta']): d for d in r['stems'].values()}, r['tempo_bpm'], r.get('pulso')
        except (OSError, ValueError, KeyError):
            return {}, None, None

    def _rescale(self, k):
        """÷2 / ×2: el tempo y el compás se cuentan en otros tiempos; las barras no se mueven."""
        if not 0.25 <= self.scale * k <= 4:
            return
        self.scale *= k
        self.tempo.setValue(self.tempo.value() * k)
        meter = self.meter.value() * k
        if meter >= 1 and float(meter).is_integer():
            self.meter.setValue(int(meter))

    def _first_here(self):
        self.first = self.player.pos / engine.SR
        self.here.setText(f"{TXT['here']} · {fmt_time(self.first)}")

    def _grid(self, it):
        """El pulso con que se escribe el MIDI: el del sonido que se ve con lo corregido aquí; los demás, el suyo."""
        if self.cur and it['path'] == self.cur['path']:
            return engine.grid_for(self.pulse, self.tempo.value(), self.scale, self.meter.value(), self.first)
        _, tempo, pulse = self._report(it['dst'])
        return engine.grid_for(pulse, tempo or self.tempo.value())

    def _show(self):
        it = self.cur
        notes = self.notes_of(it) or []
        d = self._report(it['dst'])[0].get(it['path']) or self.views.get(it['path'])
        if d:
            self.spec.show_stem(d, notes)
        else:  # sin análisis (audio abierto aquí): el espectrograma se calcula aparte
            self.spec.show_notes(notes) if notes else self.spec.clear()
            self._make_view(it['path'])
        self._band()
        self._enable()
        self._say()

    def _make_view(self, path):
        png = os.path.join(tempfile.gettempdir(), 'rd_stems_vistas', f'{abs(hash(path))}.png')
        emit = self.bridge.msg.emit

        def work():
            try:
                emit('view', (path, engine.analyze_stem(path, png)))
            except Exception:
                log_error(traceback.format_exc())
        bg(work)

    def _band(self):
        """Marca en el espectrograma el rango de Hz del TIPO; en CUSTOM sus bordes se arrastran."""
        kind = self.kind.value()
        drums = bool(self.cur and self._kit(self.cur))
        band = self.custom if kind == 'custom' else engine.MIDI_RANGES[kind]
        self.spec.band = band if band[0] and not drums else None
        self.spec.band_edit = kind == 'custom'
        self.spec.update()

    def _band_moved(self, band):
        self.custom = band
        settings().setValue('midi_lo', band[0])
        settings().setValue('midi_hi', band[1])

    def _say(self):
        it = self.cur
        if not it:
            return
        if self._no_notes(it):
            return self.info.setText(TXT['midi_no_drums'])
        notes = self.notes_of(it)
        drums = bool(self._kit(it))
        state = TXT['hits' if drums else 'notes'].format(len(notes)) if notes is not None else TXT['no_midi']
        self.info.setText(f"{it['label']}  ·  {state}")

    def _enable(self):
        drums = bool(self.cur and self._kit(self.cur))
        for w in (self.kind, self.min_len, self.bends):  # la batería no tiene alturas: esos no aplican
            w.setEnabled(not drums)

    # --- convertir (uno o varios, en fila) ---
    def convert(self, items):
        if self.busy or not items:
            return
        s = settings()
        s.setValue('midi_sens', self.sens.value())
        s.setValue('midi_min', self.min_len.value())
        s.setValue('midi_q', self.qgrid.value())
        s.setValue('midi_strength', self.strength.value())
        s.setValue('midi_fill', self.rests.value())
        s.setValue('midi_trim', 'true' if self.trim.isChecked() else 'false')
        s.setValue('midi_bends', 'true' if self.bends.isChecked() else 'false')
        sens = self.sens.value() / 100
        quant = dict(quant=self.qgrid.value(), strength=self.strength.value() / 100, fill=self.rests.value(),
                     trim=self.trim.isChecked())
        jobs, seen = [], set()
        for it in items:
            out = self.mid_of(it)
            if self._no_notes(it) or out in seen:  # varias piezas del mismo kit: un solo MIDI
                continue
            seen.add(out)
            # el sonido que se ve usa el TIPO elegido; los demás, el que corresponde a su nombre
            kind = self.kind.value() if self.cur and it['path'] == self.cur['path'] else auto_kind(it['base'])
            band = self.custom if kind == 'custom' else None
            g = self._grid(it)
            kit = self._kit(it)
            if kit:
                pieces = {os.path.splitext(f)[0]: os.path.join(kit, f) for f in os.listdir(kit)
                          if f.endswith('.wav') and os.path.splitext(f)[0] in engine.GM_DRUMS}
                jobs.append((out, lambda p=pieces, o=out, g=g: engine.drums_to_midi(p, o, g, sens, **quant)))
            else:
                opts = dict(quant, sensitivity=sens, min_ms=self.min_len.value(), kind='todo' if band else kind,
                            band=band, bends=self.bends.isChecked(), program=engine.program(it['base']),
                            name=it['label'])
                jobs.append((out, lambda p=it['path'], o=out, g=g, opts=opts: engine.to_midi(p, o, g, **opts)))
        if not jobs:
            return
        self.stop_play()
        self.busy = True
        self.bar.setRange(0, 0)  # sin pasos: la barra se mueve sola mientras trabaja
        emit = self.bridge.msg.emit

        def work():
            for n, (out, job) in enumerate(jobs):
                emit('busy', TXT['midi_busy_n'].format(n + 1, len(jobs)) if len(jobs) > 1 else TXT['midi_busy'])
                try:
                    emit('midi', (out, job()))
                except Exception:
                    emit('error', traceback.format_exc())
            emit('all', None)
        bg(work)

    def on_msg(self, kind, val):
        if kind == 'view':
            path, d = val
            self.views[path] = d
            if self.cur and self.cur['path'] == path:
                self.spec.show_stem(d, self.notes_of(self.cur) or [])
                self._band()
        elif kind == 'busy':
            self.info.setText(val)
        elif kind == 'midi':
            out, notes = val
            self.notes[out] = notes
            self.player.tracks.pop('notas', None)
        elif kind == 'error':
            log_error(val)
            warn(self, 'error', engine.explain(val))
        elif kind == 'sheets':
            self.info.setText(TXT['sheets_done'].format(len(val)))
            if len(val) == 1:
                _open(val[0])  # el PDF
        elif kind == 'all':
            self.busy = False
            self.bar.setRange(0, 1)
            self.bar.setValue(0)
            self.refresh()

    def sheets(self):
        """Partitura del sonido que se ve o, con SELECCIÓN MÚLTIPLE, de cada marcado que ya tenga MIDI."""
        if self.busy:
            return
        mids = list(dict.fromkeys(self.mid_of(it) for it in (self.selected(True) or ([self.cur] if self.cur else []))
                                  if self.notes_of(it) is not None))
        if not mids:
            return warn(self, 'no_midi_sheet', 'Primero convierte a MIDI (♪).')
        if not engine.find_musescore():
            return warn(self, 'no_musescore', 'Las partituras las escribe MuseScore 4, que es gratis: bájalo de '
                        'musescore.org, instálalo y vuelve a intentar.')
        self.busy = True
        self.bar.setRange(0, 0)
        emit = self.bridge.msg.emit

        def work():
            done = []
            for n, mid in enumerate(mids):
                emit('busy', f"{TXT['sheet']} {n + 1}/{len(mids)}…")
                try:
                    done.append(engine.sheets(mid)[0])
                except Exception:
                    emit('error', traceback.format_exc())
            emit('all', None)
            emit('sheets', done)
        bg(work)

    # --- descargar y eliminar MIDI ---
    def download(self, items):
        mids = list({self.mid_of(it): it for it in items if self.notes_of(it) is not None}.items())
        if not mids:
            return
        s = settings()
        last = s.value('export_dir', os.path.expanduser('~'))
        name = lambda it: os.path.splitext(os.path.basename(self.mid_of(it)))[0] + '-midi.mid'
        if len(mids) == 1:  # uno: se elige carpeta y nombre
            target, _ = QFileDialog.getSaveFileName(self, TXT['save_to'], os.path.join(last, name(mids[0][1])),
                                                    'MIDI (*.mid)')
            if not target:
                return
            pairs, folder = [(mids[0][0], target)], os.path.dirname(target)
        else:  # varios: se elige carpeta; si un nombre ya existe se numera
            folder = QFileDialog.getExistingDirectory(self, TXT['save_to'], last)
            if not folder:
                return
            pairs, taken = [], set()
            for mid, it in mids:
                target = free_name(os.path.join(folder, name(it)), taken)
                taken.add(target)
                pairs.append((mid, target))
        s.setValue('export_dir', folder)
        self.mod.copy(pairs)

    def delete(self, items):
        mids, wavs, drop = {}, [], []
        for it in items:
            if self.notes_of(it) is not None:
                mids[self.mid_of(it)] = it
            elif it.get('opened'):
                drop.append(it['path'])
            elif it['base']:  # la mezcla original nunca se borra desde aquí
                wavs.append(it['path'])
        if not (mids or wavs or drop):
            return
        lines = [TXT[k].format(len(v)) for k, v in (('rm_mid', mids), ('rm_wav', wavs), ('rm_list', drop)) if v]
        if not notice(self, 'rm_midi', f"{TXT['rm_q']}\n\n" + '\n'.join(lines)):
            return
        self.stop_play()  # Windows no deja mover un archivo abierto
        self.main.stop_play(keep_pos=True)
        failed, gone = [], []
        for path in list(mids) + wavs:
            r = QFile.moveToTrash(path)
            (gone if (r[0] if isinstance(r, tuple) else r) else failed).append(path)
            self.notes.pop(path, None)
            folder = os.path.dirname(path)
            if os.path.basename(folder).lower() == 'bateria_6' and not os.listdir(folder):
                os.rmdir(folder)
        self.opened = [it for it in self.opened if it['path'] not in drop]
        self.main.forget(gone)
        self.player.tracks.clear()
        self.refresh()
        if failed:
            warn(self, 'trash_fail', TXT['trash_fail'].format('\n'.join(failed)))

    # --- escuchar: siempre las notas junto con el audio ---
    def toggle_play(self):
        if self.player.playing:
            return self.stop_play(keep_pos=True)
        it = self.cur
        if not it:
            return
        notes = self.notes_of(it)
        try:
            active = set()
            if notes and not self._kit(it):  # la batería en tonos no dice nada: se escucha el audio
                if 'notas' not in self.player.tracks:
                    y = engine.midi_audio(notes)
                    self.player.tracks['notas'] = np.ascontiguousarray(np.stack([y, y], 1))
                active.add('notas')
            with_wait(lambda: self.player.load([it['path']]))
            active.add(it['path'])
            self.player.active = active
            if self.player.pos >= self.player.length:
                self.player.pos = 0
            self.player.play()
        except Exception:
            log_error(traceback.format_exc())
            return warn(self, 'no_audio', TXT['no_audio'])
        self.play_btn.set_glyph('stop')
        self.timer.start()

    def stop_play(self, keep_pos=False):
        self.player.stop()
        if not keep_pos:
            self.player.pos = 0
        self.timer.stop()
        self.play_btn.set_glyph('play')
        self.spec.set_playhead(self.player.pos / engine.SR if keep_pos else None)

    def _tick(self):
        if not self.player.playing:
            return self.stop_play()
        self.spec.set_playhead(self.player.pos / engine.SR)

    def seek(self, secs):
        self.player.pos = int(secs * engine.SR)
        self.spec.set_playhead(secs)

    def open_dir(self):
        if self.cur:
            _open(os.path.dirname(self.mid_of(self.cur)))


def free_name(path, taken=()):
    """'voz.mid' ya existe -> 'voz (2).mid'."""
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(path) or path in taken:
        path, n = f'{base} ({n}){ext}', n + 1
    return path


def bg(fn):
    """Hilo de fondo que espera a que engine termine de importar librosa/scipy/torch (ver engine.ready)."""
    threading.Thread(target=lambda: (engine.ready(), fn()), daemon=True).start()


def with_wait(fn):
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        engine.ready()  # el hilo principal tampoco importa librosa mientras el de fondo lo hace
        return fn()
    finally:
        QApplication.restoreOverrideCursor()


def _open(path):
    path = os.path.normpath(path)  # Explorer a veces rechaza rutas con "/"
    if os.name == 'nt':
        try:
            os.startfile(path)
        except OSError:  # WinError 1726 visto en Windows 11: Explorer directo sí funciona
            subprocess.Popen(['explorer', path])
    else:
        subprocess.Popen(['xdg-open' if sys.platform != 'darwin' else 'open', path])


def log_error(text):
    """Sin consola los errores no se ven: quedan en error.log junto a la app."""
    try:
        with open(os.path.join(engine.APP_DIR, 'error.log'), 'a', encoding='utf-8') as f:
            f.write(text + '\n')
    except OSError:
        pass


# --- arranque: la pluma de luz dibuja el logo y lo lleva a la barra ---

BOOT_STAGE = '#070E0A'  # el mismo negro en los dos temas
BOOT_HEAD, BOOT_BODY = '#F4F8E2', '#35F28E'  # pluma: cabeza crema, cuerpo verde
# Líneas centrales del logo en el espacio de assets/logo.svg:
# párpado, base, párpado de abajo y cola de un solo trazo; después los tres rayos.
_LID = [(12, 381), (20, 372), (50, 338), (85, 303), (125, 272), (170, 245), (220, 222), (285, 203), (350, 191),
        (418, 186), (482, 186), (557, 196), (621, 211), (677, 232), (721, 251), (763, 275), (797, 300), (846, 339),
        (880, 374), (892, 378)]
_LOWER = [(12, 382), (42, 415), (62, 440), (90, 470), (125, 492), (165, 511), (212, 523), (260, 526), (310, 527),
          (350, 521), (393, 509), (435, 491), (472, 469), (505, 445), (528, 424)]
BOOT_PEN = ((120, 1300, _LID + [(10, 378)] + _LOWER + [(1012, 652), (1012, 378)]),  # (empieza, dura, línea) en ms
            (1130, 200, [(152, 186), (84, 100)]), (1200, 200, [(448, 110), (448, 0)]), (1270, 200, [(742, 186), (810, 100)]))
DRAWN, FLY, GLIDE, HEAD = 1500, 1900, 1100, 170  # ms: dibujado, empieza a volar, viaje; largo de la cabeza


def _clamp(t):
    return max(0.0, min(1.0, t))


def _ease(t):  # ease-in-out cúbica
    return 4 * t ** 3 if t < .5 else 1 - (-2 * t + 2) ** 3 / 2


def _stretch(line, a, b):
    """El tramo de una polilínea entre las distancias a y b, como QPainterPath."""
    out, run = [], 0.0
    for (x0, y0), (x1, y1) in zip(line, line[1:]):
        seg = math.dist((x0, y0), (x1, y1))
        lo, hi = max(a - run, 0), min(b - run, seg)
        if seg and lo < hi:
            if not out:
                out.append(QPointF(x0 + (x1 - x0) * lo / seg, y0 + (y1 - y0) * lo / seg))
            out.append(QPointF(x0 + (x1 - x0) * hi / seg, y0 + (y1 - y0) * hi / seg))
        run += seg
    path = QPainterPath()
    if out:
        path.addPolygon(QPolygonF(out))
    return path


# Contenido que se calienta como fósforo: (avance, opacidad, brillo)
PHOSPHOR = ((0, .2, .38, .55, 1), (0, .8, .3, 1, 1), (2.4, 2.2, 1.6, 1.5, 1))


class Clocked(QWidget):
    """Capa animada sobre la ventana con su propio reloj: si el programa se traba, espera en vez de saltar."""

    def __init__(self, win):
        super().__init__(win)
        self.win, self.t, self.last = win, 0, 0
        self.clock = QElapsedTimer()
        self.clock.start()
        self.timer = QTimer(self, interval=16, timeout=self._tick)
        self.timer.start()
        self.setGeometry(win.rect())

    def _tick(self):
        now = self.clock.elapsed()
        self.t += min(now - self.last, 50)
        self.last = now
        self.frame()


class ThemeRoll(Clocked):
    """Cambio de tema: el nuevo baja sobre el anterior por bandas, como un refresco de pantalla (14 pasos en 420 ms),
    y llega con más brillo (×1.4) que se asienta."""
    STEPS, TIME = 14, 420

    def __init__(self, win, old):
        super().__init__(win)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.old = old  # la ventana con el tema anterior
        self.show()

    def frame(self):
        if self.t >= self.TIME:
            self.timer.stop()
            self.deleteLater()
        self.update()

    def paintEvent(self, e):
        q = math.floor(_clamp(self.t / self.TIME) * self.STEPS) / self.STEPS
        cut = self.height() * q
        p = QPainter(self)
        p.setClipRect(QRectF(0, cut, self.width(), self.height() - cut))
        p.drawPixmap(0, 0, self.old)
        p.setClipRect(QRectF(0, 0, self.width(), cut))
        p.setCompositionMode(QPainter.CompositionMode_Screen)  # aclara como un brillo de 1.4 que baja a 1
        p.fillRect(self.rect(), QColor(255, 255, 255, round(70 * (1 - q))))


NOISE = 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%&*+='


class Decode(QLabel):
    """Un valor que cambia se decodifica: caracteres al azar que se resuelven de izquierda a derecha en 300 ms."""

    def __init__(self, text=''):
        super().__init__(text)
        self.final = text
        self.clock = QElapsedTimer()
        self.timer = QTimer(self, interval=16, timeout=self._step)

    def setText(self, text):
        if text == self.final:
            return
        self.final = text
        if not self.isVisible() or text in ('', '—'):
            self.timer.stop()
            return super().setText(text)
        self.clock.start()
        self.timer.start()
        self._step()

    def text(self):
        return self.final

    def _step(self):
        q = min(1.0, self.clock.elapsed() / 300)
        k = int(q * len(self.final))
        super().setText(self.final[:k] + ''.join(c if c == ' ' else random.choice(NOISE) for c in self.final[k:]))
        if q >= 1:
            self.timer.stop()


class Assembly(Clocked):
    """La interfaz se arma por partes, sin tocar los widgets: esta capa tapa cada uno con el fondo y lo destapa a su
    tiempo. items: (cómo, rectángulo, empieza, dura, letras). Cómo entra cada uno:
    marco = el borde se traza con un eco y el contenido se llena por bandas con parpadeo de fósforo; línea = cortinilla
    de izquierda a derecha; caída = de arriba abajo; texto = se teclea (400 ms como mucho)."""

    def __init__(self, win, items):
        super().__init__(win)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.items = items
        self.end = max((at + d * 1.3 + 320 for _, _, at, d, _ in items), default=0)  # hasta que se apaga el trazo
        self.show()

    def frame(self):
        if self.t >= self.end:
            return self.finish()
        self.update()

    def finish(self):
        if self.timer.isActive():
            self.timer.stop()
            self.hide()
            self.deleteLater()
            if self.win.assembly is self:
                self.win.assembly = None

    def paintEvent(self, e):
        p = QPainter(self)
        for kind, r, at, d, n in self.items:
            if self.t >= at + d * 1.3 + 320:
                continue
            if kind == 'frame':
                self._fill(p, r, (self.t - at - d * .55) / (d + 120))
                self._trace(p, r, self.t - at, d * 1.3)
            elif kind == 'drop':
                q = _ease(_clamp((self.t - at) / (d * 1.4)))
                p.fillRect(QRectF(r.left(), r.top() + r.height() * q, r.width(), r.height() * (1 - q)), QColor(PAPER))
            elif n or kind == 'line':  # cortinilla o tecleo: se tapa lo que falta a la derecha
                q = (_ease(_clamp((self.t - at) / d)) if kind == 'line'
                     else math.floor(_clamp((self.t - at) / min(400, n * 16)) * n) / n)  # carácter a carácter
                p.fillRect(QRectF(r.left() + r.width() * q, r.top(), r.width() * (1 - q), r.height()), QColor(PAPER))

    @staticmethod
    def _fill(p, r, q):
        """Por bandas de 6 px de arriba abajo, con el parpadeo y el brillo de un fósforo que se calienta."""
        if q >= 1:
            return
        cut = r.top() + math.ceil(r.height() * _clamp(q / .55) / 6) * 6
        p.fillRect(QRectF(r.left(), cut, r.width(), max(0.0, r.bottom() - cut)), QColor(PAPER))
        shown = QRectF(r.left(), r.top(), r.width(), min(cut, r.bottom()) - r.top())
        if shown.height() <= 0:
            return
        q = _clamp(q)
        veil, glow = QColor(PAPER), QColor(INK)
        veil.setAlphaF(1 - float(np.interp(q, PHOSPHOR[0], PHOSPHOR[1])))
        glow.setAlphaF(min(.45, (float(np.interp(q, PHOSPHOR[0], PHOSPHOR[2])) - 1) * .3))
        p.fillRect(shown, veil)
        p.fillRect(shown, glow)

    @staticmethod
    def _trace(p, r, el, d):
        """El borde se dibuja solo, seguido de un eco más tenue que se cierra sobre él; después se apaga."""
        fade = el / (d + 320)
        if el <= 0 or fade >= 1:
            return
        for inset, lag, color, alpha in ((5, 60, CONTROL, .5), (0, 0, INK, 1)):
            q = _ease(_clamp((el - lag) / d))
            b = r.adjusted(-inset + .5, -inset + .5, inset - .5, inset - .5)
            line = [(b.left(), b.top()), (b.right(), b.top()), (b.right(), b.bottom()), (b.left(), b.bottom()),
                    (b.left(), b.top())]
            c = QColor(color)
            c.setAlphaF(alpha * (1 if fade < .75 else (1 - fade) / .25))
            p.setPen(QPen(c, 1, Qt.SolidLine, Qt.FlatCap))
            p.drawPath(_stretch(line, 0, 2 * (b.width() + b.height()) * q))


def choreography(win, root, pace=1.0, start=0.0):
    """Qué entra y cómo, en este orden: barras y botones, columnas, paneles, títulos, teclas, contenido,
    valores y textos, progreso. Solo lo que se ve; cada uno ~42 ms después del anterior (menos si son muchos)."""
    every = [w for w in root.findChildren(QWidget) if w.isVisible() and not w.visibleRegion().isEmpty()]
    stage = lambda test: [w for w in every if test(w)]  # noqa: E731
    in_page = win.stack.isAncestorOf
    steps = (('frame', stage(lambda w: isinstance(w, Key) and not in_page(w))),
             ('line', stage(lambda w: isinstance(w, TitleRule))),
             ('drop', stage(lambda w: isinstance(w, Module))),
             ('frame', stage(lambda w: w.objectName() == 'panel')),
             ('line', stage(lambda w: w.objectName() == 'row')),
             ('type', stage(lambda w: isinstance(w, Title))),
             ('frame', stage(lambda w: isinstance(w, Key) and in_page(w))),
             ('frame', stage(lambda w: w.objectName() == 'display' or isinstance(w, Reticled))),
             ('line', stage(lambda w: w.objectName() == 'datum' or isinstance(w, QSlider))),
             ('type', stage(lambda w: isinstance(w, Elide) or w.objectName() in ('info', 'value'))),
             ('line', stage(lambda w: isinstance(w, Progress))))
    n = sum(len(ws) for _, ws in steps)
    gap, at, items = min(42.0, 1600 / max(n, 1)) * pace, start, []
    for kind, ws in steps:
        for w in ws:
            text = w.text() if isinstance(w, QLabel) else ''
            items.append((kind, QRectF(QPointF(w.mapTo(win, QPoint(0, 0))), QSizeF(w.size())), at, 300 * pace,
                          min(len(text), 40)))
            at += gap
    return items


class Boot(Clocked):
    """El arranque, sobre la ventana: una pluma de luz con la cabeza clara dibuja el logo de un trazo y luego los
    rayos; el brillo se asienta; el logo viaja despacio a su lugar en la barra con dos ecos detrás, mientras el negro
    se funde con el tema. Clic o tecla lo saltan. Un bloqueo del programa lo pausa en vez de saltárselo."""

    def __init__(self, win, slot, on_done, on_fly=None):
        super().__init__(win)
        self.slot, self.on_done, self.on_fly = slot, on_done, on_fly
        self.shape = logo_path()
        self.box = self.shape.boundingRect()
        self.strokes = [(at, ms, line, sum(math.dist(a, b) for a, b in zip(line, line[1:]))) for at, ms, line in BOOT_PEN]
        self.logo = slot.pixmap()
        empty = QPixmap(self.logo.size())  # el de la barra se esconde sin cambiar de tamaño
        empty.setDevicePixelRatio(self.logo.devicePixelRatio())
        empty.fill(Qt.transparent)
        slot.setPixmap(empty)
        self.setFocusPolicy(Qt.StrongFocus)
        self.show()
        self.raise_()
        self.setFocus()

    def frame(self):
        if self.t >= FLY and self.on_fly:
            self.on_fly()
            self.on_fly = None
        if self.t >= FLY + GLIDE:
            return self.finish()
        self.update()

    def finish(self, skip=False):
        if not self.timer.isActive():
            return
        if skip and self.win.assembly:  # saltar el arranque salta también el ensamblado
            self.win.assembly.finish()
        self.timer.stop()
        self.slot.setPixmap(logo_pixmap(INK, 22))  # con el tema de ahora, por si cambió
        self.hide()
        self.deleteLater()
        self.win.boot = None
        self.on_done()

    def mousePressEvent(self, e):
        self.finish(skip=True)

    def keyPressEvent(self, e):
        self.finish(skip=True)

    def _place(self, p, k):
        """Lleva el pintor a la caja del logo: centrada (34% del ancho, 440 px como mucho) en k=0, la de la barra en k=1."""
        lw = min(self.width() * .34, 440)
        lh = lw * self.box.height() / self.box.width()
        a = QRectF(self.width() / 2 - lw / 2, self.height() / 2 - lh / 2, lw, lh)
        b = QRectF(QPointF(self.slot.mapTo(self.win, QPoint(0, 0))), QSizeF(self.slot.size()))
        x, y, w = (a.x() + (b.x() - a.x()) * k, a.y() + (b.y() - a.y()) * k, a.width() + (b.width() - a.width()) * k)
        p.resetTransform()
        p.translate(x, y)
        p.scale(w / self.box.width(), w / self.box.width())
        p.translate(-self.box.topLeft())

    @staticmethod
    def _pen(p, color, width, alpha):
        c = QColor(color)
        c.setAlphaF(_clamp(alpha))
        p.setPen(QPen(c, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def _fill(self, p, color, alpha):
        c = QColor(color)
        c.setAlphaF(_clamp(alpha))
        p.fillPath(self.shape, c)

    def _draw_pen(self, p):
        heads = []
        for at, ms, line, length in self.strokes:
            q = _clamp((self.t - at) / ms)
            heads.append(length * (q - math.sin(q * math.pi * 2) / 25))  # la mano frena y acelera un poco
        for (_, _, line, length), h in zip(self.strokes, heads):
            if h <= 0:
                continue
            for width, alpha in ((30, .1), (20, .22), (12, .9)):  # resplandor: anchas y tenues, luego la línea
                self._pen(p, BOOT_BODY, width, alpha)
                p.drawPath(_stretch(line, 0, h))
            if h < length:
                for width, alpha in ((36, .25), (16, 1)):
                    self._pen(p, BOOT_HEAD, width, alpha)
                    p.drawPath(_stretch(line, h - HEAD, h))
        p.save()  # el logo hace de máscara: la línea toma su ancho y sus puntas reales
        p.setClipPath(self.shape)
        for (_, _, line, length), h in zip(self.strokes, heads):
            if h <= 0:
                continue
            self._pen(p, BOOT_BODY, 44, 1)
            p.drawPath(_stretch(line, 0, h))
            if h < length:
                self._pen(p, BOOT_HEAD, 44, 1)
                p.drawPath(_stretch(line, h - HEAD, h))
                self._pen(p, BOOT_BODY, 44, .3)
                p.drawPath(_stretch(line, h, h + 70))
        p.restore()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.t
        stage = QColor(BOOT_STAGE)
        stage.setAlphaF(1 - _ease(_clamp((t - FLY) / (GLIDE * .9))))  # el negro se funde con el tema, sin golpe
        p.fillRect(self.rect(), stage)
        if t < DRAWN:
            self._place(p, 0)
            return self._draw_pen(p)
        fly = _ease(_clamp((t - FLY) / GLIDE))
        for lag, alpha in ((180, .15), (90, .3)):  # ecos, solo mientras viaja
            self._place(p, _ease(_clamp((t - FLY - lag) / GLIDE)))
            self._fill(p, BOOT_BODY, alpha * math.sin(fly * math.pi))
        self._place(p, fly)
        glow = (1 - .5 * _clamp((t - DRAWN) / 400)) * (1 - fly)  # el brillo se asienta
        for width, alpha in ((28, .12), (14, .22)):
            self._pen(p, BOOT_BODY, width, alpha * glow)
            p.drawPath(self.shape)
        self._fill(p, BOOT_BODY, 1 - fly)
        if fly:
            self._fill(p, INK, fly)  # se funde al color de texto del tema


def main():
    engine.utf8_console()
    # 125% y 150% se dibujan 1:1, 175% o más al doble: con escalas fraccionarias la letra de píxel se ve borrosa
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    load_fonts()
    apply_theme(settings().value('theme', 'night'))
    app.setWindowIcon(QIcon(resource_path('assets/logo.ico')))

    def excepthook(*exc):
        text = ''.join(traceback.format_exception(*exc))
        log_error(text)
        warn(None, 'error', engine.explain(text))
    sys.excepthook = excepthook

    win = Main()
    room = app.primaryScreen().availableGeometry()
    win.resize(min(1240, room.width() - 40), min(860, room.height() - 40))
    args = sys.argv[1:]
    win.show()
    win.activateWindow()
    win.boot = Boot(win, win.logo, lambda: win.set_sources(args) if args else None, on_fly=win.assemble)
    win.surface.raise_()  # el grano también va sobre el arranque
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
