"""Mezclador sin pantalla (no necesita modelos): .venv/Scripts/python test_app.py"""
import json
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import app

qa = QApplication([])


def contrast(a, b):  # WCAG 2
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        return sum(k * (x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4) for k, x in zip((.2126, .7152, .0722), c))
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + .05) / (lo + .05)


# paleta: texto AA (4.5:1) y bordes 3:1 en los dos temas, sobre fondo y panel
for name, t in app.THEMES.items():
    for bg in (t["PAPER"], t["PANEL"]):
        for k in ("INK", "MUTED", "TITLE", "DATA", "DANGER"):
            assert contrast(t[k], bg) >= 4.5, (name, k, bg, contrast(t[k], bg))
        assert contrast(t["CONTROL"], bg) >= 3, (name, "CONTROL", bg)
    assert contrast(t["ON_ACTION"], t["ACTION"]) >= 4.5 and contrast(t["TITLE"], t["ACCENT"]) >= 4.5, name
    assert contrast(t["PAPER"], t["DANGER"]) >= 4.5, (name, "alerta", contrast(t["PAPER"], t["DANGER"]))
w = app.Main()
d = tempfile.mkdtemp()
w.src = os.path.join(d, "song.wav")
w.dst = os.path.join(d, "song - stems")
os.makedirs(w.dst)
sr = app.engine.SR
paths = {}
for s in ("voz", "bateria", "bajo", "resto"):
    paths[s] = os.path.join(w.dst, s + ".wav")
    sf.write(paths[s], np.full((sr, 2), 0.1, np.float32), sr)
sf.write(w.src, np.full((sr, 2), 0.4, np.float32), sr)
w.fill({"Stems": dict(paths)}, None)

on = lambda: {it.data(Qt.UserRole)[0].split(" / ")[1] for it in w._stem_items() if it.checkState() == Qt.Checked}
assert on() == {"voz", "bateria", "bajo", "resto"}, on()
w.preset("karaoke"); assert on() == {"bateria", "bajo", "resto"}, on()
w.preset("acapella"); assert on() == {"voz"}, on()
w.preset("rhythm"); assert on() == {"bateria", "bajo"}, on()
w.preset("all"); assert on() == {"voz", "bateria", "bajo", "resto"}

# tecla 1 = primer stem (mezcla original): se marca y se desmarca
w.toggle_nth(1); assert "original" in on()
w.toggle_nth(1); assert "original" not in on()

# VOL / PAN del stem elegido
items = {it.data(Qt.UserRole)[0].split(" / ")[1]: it for it in w._stem_items()}
w.list.setCurrentItem(items["voz"])
w.vol.setValue(-6); w.pan.setValue(-40)
assert w.player.mix[paths["voz"]] == (-6, -40)
assert items["voz"].text() == "VOZ  · -6 DB  · I 40", items["voz"].text()
w.save_mix()
assert json.load(open(os.path.join(w.dst, "mezcla.json"), encoding="utf-8")) == {"Stems / voz": [-6, -40]}

# al cambiar de stem, los deslizadores muestran el suyo y no tocan el anterior
w.list.setCurrentItem(items["bajo"])
assert (w.vol.value(), w.pan.value()) == (0, 0) and w.player.mix[paths["voz"]] == (-6, -40)

# SOLO: suena solo ese, aunque haya otros marcados
w.solo.setChecked(True)
assert w.player.audible == {paths["bajo"]} and items["bajo"].text().endswith("SOLO")

# mezcla real: bajo en solo a 0 dB -> 0.1; voz -6 dB paneada a la izquierda
w.player.load(list(paths.values()))
w.player.pos = 0
b = w.player.block(4); assert np.allclose(b, 0.1, atol=1e-3), b
w.solo.setChecked(False)
w.player.active = {paths["voz"]}
w.player.pos = 0
L, R = w.player.block(4)[0]
assert abs(L - 0.1 * 10 ** (-6 / 20)) < 1e-4 and abs(R - 0.1 * 10 ** (-6 / 20) * 0.6) < 1e-4, (L, R)
w.list.setCurrentItem(items["voz"])
w.vol.setValue(app.DB_OFF)
w.player.pos = 0
assert not w.player.block(4).any()

# al volver a abrir la canción, el nivel guardado vuelve
w.fill({"Stems": dict(paths)}, None)
assert w.player.mix[paths["voz"]] == (-6, -40) and w.player.solo == set()

# YouTube: el audio bajado se suma a la lista como cualquier canción
yt = os.path.join(d, "de youtube.flac")
sf.write(yt, np.zeros((sr, 2), np.float32), sr)
w.on_msg("yt", yt)
assert os.path.normpath(yt) in w.srcs and app.yt_dir().endswith("RD Stems")

# exportar en FLAC: mismo audio de 24 bits, sin pérdida
src24 = os.path.join(d, "voz24.wav")
y24 = (np.random.default_rng(0).uniform(-1, 1, (sr, 2)) * 0.5).astype(np.float32)
sf.write(src24, y24, sr, subtype="PCM_24")
out = os.path.join(d, "export", "song", "voz24.flac")
w.songs.copy([(src24, out)])
while w.songs.pbar.value() < 100:  # el 100% llega cuando el archivo ya está escrito
    qa.processEvents()
assert sf.info(out).subtype == "PCM_24" and np.array_equal(sf.read(out, dtype="int32")[0], sf.read(src24, dtype="int32")[0])

# arranque: se dibuja por etapas y un clic lo salta; el logo vuelve a la barra
booted = []
w.boot = app.Boot(w, w.logo, lambda: booted.append(1))
assert w.logo.pixmap().toImage().pixelColor(w.logo.width() // 2, w.logo.height() // 2).alpha() == 0  # escondido
for w.boot.t in (300, 1400, 2500):
    w.boot.grab()
w.boot.mousePressEvent(None)
assert booted == [1] and w.boot is None and not w.logo.pixmap().isNull()

# ensamblado: cada pieza visible entra en orden; termina solo y deja de tapar
w.resize(1240, 860)
w.show()
qa.processEvents()
w.assemble()
kinds = [k for k, *_ in w.assembly.items]
assert kinds[0] == "frame" and kinds[-1] == "line" and len(kinds) > 20, kinds
for w.assembly.t in (0, 400, 1200):
    w.grab()
w.assembly.t = w.assembly.end
w.assembly._tick()
assert w.assembly is None

# cambio de tema por bandas (sin tocar el tema guardado) y valores que se decodifican
roll = app.ThemeRoll(w, w.grab())
roll.t = 200
roll.grab()
roll.t = roll.TIME
roll.frame()
assert not roll.timer.isActive()
dec = w.values["tempo"]
dec.setText("83.8 BPM · 4/4")
assert dec.text() == "83.8 BPM · 4/4" and dec.timer.isActive() and app.QLabel.text(dec) != dec.text()  # ruido mientras tanto
dec.clock = type("Reloj", (), {"elapsed": lambda self: 300})()
dec._step()
assert app.QLabel.text(dec) == "83.8 BPM · 4/4" and not dec.timer.isActive()

# MIDI: el pulso del análisis (3/4 a 100 BPM, primer tiempo fuerte en 0.6 s), ×2 y AQUÍ
import mido, time  # noqa: E401,E402
t = np.arange(sr * 6) / sr
sf.write(paths["bajo"], np.stack([np.sin(2 * np.pi * 110 * 2 ** ((t * 100 / 60).astype(int) % 5 / 12) * t)] * 2, 1) * 0.5, sr)
beats = list(np.round(0.6 + 0.6 * np.arange(-1, 10), 3))
json.dump({"tempo_bpm": 100.0, "pulso": dict(bpm=100.0, compas=3, primero=0.6, estable=True, pulsos=beats),
           "stems": {}}, open(os.path.join(os.path.dirname(paths["bajo"]), "analisis.json"), "w", encoding="utf-8"))
it = dict(path=os.path.normpath(paths["bajo"]), label="BAJO", src=os.path.join(d, "song.wav"),
          dst=os.path.dirname(paths["bajo"]), base="bajo", piece=False)
m = w.midi
m.pick(it)
assert (m.tempo.value(), m.meter.value()) == (100.0, 3)
m._rescale(2)
assert (m.tempo.value(), m.meter.value(), m.scale) == (200.0, 6, 2)
g = m._grid(it)
assert g["compas"] == 6 and len(g["pulsos"]) == 2 * len(beats) - 1  # sigue los pulsos, contados al doble
m.player.pos = int(1.2 * sr)
m._first_here()
assert m._grid(it)["primero"] == 1.2 and "0:01" in m.here.text(), m.here.text()
m.qgrid.set(-1)
m.convert([it])
t0 = time.monotonic()
while m.busy and time.monotonic() - t0 < 120:
    qa.processEvents()
mid = mido.MidiFile(m.mid_of(it))
assert any(x.type == "time_signature" and x.numerator == 6 for x in mid.tracks[0]), mid.tracks[0]
assert m.notes_of(it), "sin notas"
assert [x.program for x in mid.tracks[1] if x.type == "program_change"] == [33]  # bajo eléctrico, no piano

# CANCELAR mata el proceso de separación: no se guarda nada y la cola no sigue
import threading, time, types  # noqa: E401,E402
msgs = []
w.bridge = types.SimpleNamespace(msg=types.SimpleNamespace(emit=lambda k, v: msgs.append((k, v))))
w.cancelled, w.proc = False, None
job = (w.src, set(), set())  # solo ANALIZAR: no necesita modelos
t = threading.Thread(target=w._work, args=([job, job], "fast", True, w.hw or app.engine.hardware()))
t.start()
while not msgs:  # en cuanto empieza la 1a canción
    time.sleep(0.01)
w.cancel()
t.join(30)
assert not t.is_alive() and msgs[-1] == ("done", (None, [])) and not any(k == "saved" for k, _ in msgs), msgs
assert w.proc.returncode != 0 and sum(k == "song" for k, _ in msgs) == 1  # la 2a canción no empezó
print("mixer OK")
if len(sys.argv) > 1:  # captura de la ventana: test_app.py captura.png
    w.resize(1240, 860)
    w.show()
    qa.processEvents()
    w.grab().save(sys.argv[1])
