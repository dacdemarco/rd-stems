"""Chequeo rápido del análisis (no necesita modelos): python test_engine.py"""
import os
import tempfile

import numpy as np
import soundfile as sf

import engine

SR = 22050


def tone(freqs, dur):
    t = np.arange(int(dur * SR)) / SR
    return sum(np.sin(2 * np.pi * f * t) for f in freqs) * np.exp(-t * 2)


def test_tempo():
    for bpm in (90, 128, 174):
        y = np.zeros(SR * 20)
        n = int(0.05 * SR)
        for k in range(int(20 * bpm / 60)):
            s = int(k * 60 / bpm * SR)
            y[s:s + n] += np.random.randn(len(y[s:s + n])) * np.exp(-np.arange(len(y[s:s + n])) / 200)
        got = engine.detect_tempo(y, SR)
        assert abs(got - bpm) < 1.5 or abs(got - bpm * 2) < 3 or abs(got - bpm / 2) < 1.5, (bpm, got)


def test_key():
    c, a = 261.63, 220.0
    semis = lambda root, steps: [root * 2 ** (s / 12) for s in steps]
    # progresión I-IV-V-I en Do mayor y i-iv-v-i en La menor
    cmaj = np.concatenate([tone(semis(c, ch), 1) for ch in ([0, 4, 7], [5, 9, 12], [7, 11, 14], [0, 4, 7])] * 3)
    amin = np.concatenate([tone(semis(a, ch), 1) for ch in ([0, 3, 7], [5, 8, 12], [7, 10, 14], [0, 3, 7])] * 3)
    assert engine.detect_key(cmaj, SR)[0].startswith("C major"), engine.detect_key(cmaj, SR)
    assert engine.detect_key(amin, SR)[0].startswith("A minor"), engine.detect_key(amin, SR)


def test_stem_analysis():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "a440.wav")
    sf.write(p, tone([440], 3) * 0.5, SR)
    r = engine.analyze_stem(p, os.path.join(d, "a.png"))
    assert r["picos"] and abs(r["picos"][0]["hz"] - 440) < 6, r["picos"]
    from PIL import Image
    vista = np.asarray(Image.open(r["vista"]))
    assert vista.shape[0] == engine.VISTA_H and vista.shape[1] <= engine.VISTA_W, vista.shape
    row = engine.VISTA_H - 1 - round(np.log(440 / 20) / np.log(1000) * (engine.VISTA_H - 1))  # 440 Hz en la vista
    assert vista[row - 3:row + 4].mean() > vista.mean() + 40, "el tono de 440 Hz no aparece donde la app lo dibuja"
    sf.write(p, np.zeros(SR), SR)  # silencio no debe tronar
    assert engine.analyze_stem(p, os.path.join(d, "s.png"))["casi_silencio"]


def test_truncated_model():
    import zipfile
    d = tempfile.mkdtemp()
    good, bad = os.path.join(d, "good.ckpt"), os.path.join(d, "bad.ckpt")
    with zipfile.ZipFile(good, "w") as z:
        z.writestr("data.pkl", b"x" * 5000)
    with open(good, "rb") as f, open(bad, "wb") as g:
        g.write(f.read()[:3000])  # descarga cortada
    for p in (good, bad):
        engine._drop_if_truncated(p, lambda m: None)
    assert os.path.exists(good) and not os.path.exists(bad)


def test_midi():
    try:
        import basic_pitch  # noqa: F401
    except ImportError:
        return print("(basic-pitch no instalado: se salta la prueba de MIDI)")
    d = tempfile.mkdtemp()
    wav, mid = os.path.join(d, "melodia.wav"), os.path.join(d, "melodia.mid")
    melody = (60, 64, 67, 72)
    sf.write(wav, np.concatenate([tone([440 * 2 ** ((n - 69) / 12)], 0.5) * 0.4 for n in melody]), SR)
    notes = engine.to_midi(wav, mid, engine.grid_for(None, 100))
    assert [p for _, _, p in notes] == list(melody), notes
    assert os.path.getsize(mid) > 0


def test_plan():
    # rápida: si el SW corre, la voz sale de ahí (un pase menos); máx: modelo de voz dedicado
    assert engine.plan({"voz", "bajo"}, set(), "fast") == (["sw"], [])
    assert engine.plan({"voz", "bajo"}, set(), "max") == (["vocal", "sw"], [])
    assert engine.plan({"bateria6"}, set(), "fast") == (["sw", "drumsep"], [])
    assert engine.plan({"cuerdas"}, {"coros"}, "max") == (["mega"], [])  # sin voz no hay extras de voz
    assert engine.plan({"voz"}, {"sin_ruido", "coros"}, "max") == (["vocal"], ["coros", "sin_ruido"])
    # voz + resto + principal + coros + voz limpia; bateria6 = 6 piezas (+ resto)
    assert engine.outputs({"voz"}, {"coros", "sin_ruido"}) == 5
    assert engine.outputs({"bateria6"}, set()) == 7
    assert engine.stem_name("Canción (Remix)_(Vocals)_bs_roformer.wav") == "vocals"
    assert engine.stem_name("cancion_(synth).wav") == "synth"


def test_step_weights():
    w = engine.step_weights({"voz", "bajo"}, {"coros"}, "max", True)
    assert w[:3] == [20, 10, 4] and len(w) == 3 + 2 + engine.outputs({"voz", "bajo"}, {"coros"})
    assert engine.step_weights({"voz"}, set(), "fast", False) == [10]


def test_residual():
    mix = np.random.default_rng(0).standard_normal((1000, 2)).astype(np.float32)
    a, b = mix * 0.25, mix[:900] * 0.5  # un stem más corto no debe tronar
    rest = engine.residual(mix, [a, b])
    assert np.allclose(rest[:900], mix[:900] * 0.25) and np.allclose(rest[900:], mix[900:] * 0.75)


def test_chords():
    c, a = 261.63, 220.0
    semis = lambda root, steps: [root * 2 ** (s / 12) for s in steps]
    prog = [semis(c, [0, 4, 7]), semis(a, [0, 3, 7])] * 4  # C, Am, C, Am...
    y = np.concatenate([tone(ch, 2) for ch in prog])
    names = [n for _, n in engine.detect_chords(y, SR)]
    assert {"C", "Am"} <= set(names), names


def test_drums_midi():
    try:
        import pretty_midi
    except ImportError:
        return print("(pretty_midi no instalado: se salta la prueba de MIDI de batería)")
    d = tempfile.mkdtemp()
    kick = np.zeros(SR * 4)
    for t in (0.5, 1.5, 2.5, 3.5):
        n = int(0.2 * SR)
        kick[int(t * SR):int(t * SR) + n] = np.sin(2 * np.pi * 60 * np.arange(n) / SR) * np.exp(-np.arange(n) / 2000)
    sf.write(os.path.join(d, "bombo.wav"), kick, SR)
    sf.write(os.path.join(d, "crash.wav"), np.zeros(SR * 4), SR)  # pieza vacía: sin golpes
    hits = engine.drums_to_midi({"bombo": os.path.join(d, "bombo.wav"), "crash": os.path.join(d, "crash.wav")},
                                os.path.join(d, "bateria.mid"), engine.grid_for(None, 120))
    assert [round(s, 1) for s, _, p in hits if p == 36] == [0.5, 1.5, 2.5, 3.5], hits
    assert not [h for h in hits if h[2] == 49]
    assert len(pretty_midi.PrettyMIDI(os.path.join(d, "bateria.mid")).instruments[0].notes) == 4


def test_quantize():
    import pretty_midi
    d = tempfile.mkdtemp()
    midi = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(0)
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.13, end=0.15))  # 1/16 a 120 = 0.125 s
    inst.pitch_bends.append(pretty_midi.PitchBend(100, 0.1))
    midi.instruments.append(inst)
    notes = engine._finish_midi(midi, os.path.join(d, "q.mid"), engine.grid_for(None, 120), quant=4, bends=False)
    assert np.allclose(notes, [(0.125, 0.25, 60)]), notes  # el final nunca queda antes de un paso de rejilla
    assert not pretty_midi.PrettyMIDI(os.path.join(d, "q.mid")).instruments[0].pitch_bends
    y = engine.midi_audio([(0.0, 0.5, 69)])
    assert abs(len(y) / engine.SR - 0.6) < 0.01 and 0 < np.abs(y).max() <= 1


def test_beat_grid():
    """Barras en los tiempos fuertes, mapa de tempo, rejilla automática con tresillos, rellenar y recortar."""
    import mido
    import pretty_midi
    d = tempfile.mkdtemp()
    # 100 BPM en 3/4 que se acelera a 120, con el primer tiempo fuerte en 1.0 s (antes, una anacrusa)
    beats = np.cumsum(np.r_[0.4, 60 / np.linspace(100, 120, 80)])
    pulse = dict(bpm=110.0, compas=3, primero=float(beats[2]), estable=False, pulsos=list(beats))
    g = engine.grid_for(pulse, 110.0)
    midi = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(33)
    for b0, b1 in zip(beats[2:60], beats[3:61]):  # tresillos de corchea, 15 ms tarde, cortos
        for j in range(3):
            t = b0 + (b1 - b0) * j / 3 + 0.015
            inst.notes.append(pretty_midi.Note(velocity=80, pitch=40 + j, start=t, end=t + 0.05))
    midi.instruments.append(inst)
    out = os.path.join(d, "g.mid")
    notes = engine._finish_midi(midi, out, g, quant=-1, fill=1.0)
    f = mido.MidiFile(out)
    meta = [m for m in f.tracks[0] if m.is_meta]
    assert any(m.type == "time_signature" and m.numerator == 3 for m in meta)
    tempos = [60e6 / m.tempo for m in meta if m.type == "set_tempo"]
    assert len(tempos) > 2 and tempos[0] < tempos[-1], tempos  # sigue la aceleración, sin un cambio por pulso
    assert len(tempos) < 30, len(tempos)
    ticks, now = [], 0
    for m in f.tracks[1]:
        now += m.time
        if m.type == "note_on":
            ticks.append(now)
    assert all(t % 160 == 0 for t in ticks), ticks[:10]  # tresillos exactos (480 / 3), rejilla elegida sola
    assert ticks[0] == 3 * 480, ticks[0]  # el tiempo fuerte cae en una barra; la anacrusa cabe en el compás 1
    assert abs(notes[0][0] - (beats[2] + 0.015)) < 0.026, notes[0]  # donde suena; el mapa de tempo simplificado mueve hasta 25 ms
    assert abs(notes[0][1] - notes[1][0]) < 1e-6  # rellenar: cada nota llega hasta la siguiente
    back = engine.read_midi(out)
    assert np.allclose([n[0] for n in back], [n[0] for n in notes], atol=0.003), (back[:3], notes[:3])
    # recortar compases vacíos: ninguno aquí (la nota cae en el primer compás); a mano, con el primero en 5 s
    late = engine.grid_for(pulse, 110.0, primero=float(beats[11]))
    engine._finish_midi(midi, out, late, quant=-1, trim=True)
    first = next(m.time for m in mido.MidiFile(out).tracks[1] if m.type == "note_on")
    assert first < 3 * 480, first
    assert abs(engine.read_midi(out)[0][0] - notes[0][0]) < 0.005  # aunque se recorte, sigue en su lugar
    # tempo a mano, x2 y compás
    assert engine.grid_for(pulse, 90.0)["estable"] and engine.grid_for(pulse, 220.0, scale=2)["compas"] == 6
    assert len(engine.grid_for(pulse, 55.0, scale=0.5)["pulsos"]) == 41
    assert engine.grid_for(pulse, 110.0, compas=0)["compas"] is None


def test_hardware():
    hw = engine.hardware()
    assert hw["kind"] in ("cuda", "mps", "cpu") and hw["ram"] > 0 and hw["cores"] >= 1


def test_gpu_fallback():
    assert "memoria" in engine.explain("Traceback...\ntorch.OutOfMemoryError: CUDA out of memory. Tried to allocate")
    assert "PyTorch" in engine.explain("RuntimeError: CUDA error: no kernel image is available")
    assert engine.explain("x\nValueError: otra cosa") == "ValueError: otra cosa"
    assert "install.bat" in engine.explain('File "yt_dlp/YoutubeDL.py"\nyt_dlp.utils.DownloadError: ERROR: HTTP Error 403')
    calls, real = [], engine._run

    def fake(audio, model, quality, hw, log, duration, tmp):
        calls.append(hw["kind"])
        if model == "bad":
            raise ValueError("archivo dañado")
        if hw["kind"] == "cuda":
            raise RuntimeError("CUDA out of memory")
        return {"vocals": "v.wav"}
    engine._run = fake
    try:
        hw = dict(kind="cuda", fp16=True, roomy=True, ram=16)
        assert engine._separate("a.wav", "m", "max", hw, lambda m: None)[0] == {"vocals": "v.wav"}
        assert calls == ["cuda", "cpu"]
        try:  # un error que no es de GPU no se reintenta
            engine._separate("a.wav", "bad", "max", hw, lambda m: None)
            assert False
        except ValueError:
            pass
        assert calls == ["cuda", "cpu", "cuda"]
    finally:
        engine._run = real


def test_reuse():
    """Lo ya separado en la carpeta no se vuelve a separar; DrumSep sale de bateria.wav si ya existe."""
    d = tempfile.mkdtemp()
    song = os.path.join(d, "cancion.wav")
    sf.write(song, np.zeros((engine.SR, 2), np.float32), engine.SR)
    names = {engine.DRUM_MODEL: engine.PIECES, engine.SW_MODEL: ["vocals", "drums", "bass", "guitar", "piano"]}
    calls, real = [], engine._separate

    def fake(audio, model, quality, hw, log, duration=0.0):
        calls.append((model if isinstance(model, str) else "ensamble", os.path.basename(audio)))
        tmp = tempfile.mkdtemp()
        out = {}
        for n in names.get(model if isinstance(model, str) else "", ["vocals", "instrumental"]):
            out[n] = os.path.join(tmp, n + ".wav")
            sf.write(out[n], np.full((engine.SR, 2), 0.01, np.float32), engine.SR)
        return out, tmp
    engine._separate = fake
    try:
        out = os.path.join(d, "stems")
        run = lambda st, q="max": engine.separate_all(song, out, st, set(), q, {}, lambda m: None, lambda m: None)  # noqa: E731
        run({"voz", "bateria"})
        assert [c[0] for c in calls] == ["ensamble", engine.SW_MODEL]
        calls.clear()
        r = run({"voz", "bateria", "bateria6"})
        assert calls == [(engine.DRUM_MODEL, "bateria.wav")], calls  # ni voz ni SW otra vez
        assert set(r["Batería 6"]) == set(engine.PIECES.values()) and "resto" in r["Stems"]
        calls.clear()
        run({"voz", "bateria6"}, "fast")  # MÁX sirve para RÁPIDA; kit reutilizado sin pedir batería
        assert calls == []
        assert engine.step_weights({"voz", "bateria6"}, set(), "fast", False, out, song) == []
        run({"voz", "bajo"}, "fast")
        assert [c[0] for c in calls] == [engine.SW_MODEL]  # bajo nuevo; la voz MÁX no se toca
        calls.clear()
        sf.write(song, np.zeros((engine.SR * 2, 2), np.float32), engine.SR)  # otra mezcla, mismo nombre
        run({"voz"})
        assert [c[0] for c in calls] == ["ensamble"]
        run({"bajo"}, "fast")
        names[engine.SW_MODEL] = None  # la siguiente separación muere a medias, como al cancelar
        try:
            run({"bajo"})
        except TypeError:
            pass
        assert "bajo" not in engine._done(out, song) and "voz" in engine._done(out, song)  # se rehará, no se reutiliza
    finally:
        engine._separate = real


def test_fetch():
    """Una descarga cortada sigue donde quedó: pide Range desde lo que ya hay en .part."""
    import io
    import urllib.request
    data, asked = bytes(range(256)) * 40, []

    def fake(req, timeout=0):
        start = int(req.headers["Range"][6:-1])
        asked.append(start)
        r = io.BytesIO(data[start:])
        r.status, r.headers = 206, {"Content-Length": str(len(data) - start)}
        return r
    real, urllib.request.urlopen = urllib.request.urlopen, fake
    try:
        path = os.path.join(tempfile.mkdtemp(), "modelo.ckpt")
        open(path + ".part", "wb").write(data[:3000])
        engine._fetch("http://x", path, lambda m: None)
        assert asked == [3000] and open(path, "rb").read() == data and not os.path.exists(path + ".part")
    finally:
        urllib.request.urlopen = real


def test_sheets():
    """Partituras con un MuseScore falso: lo que se le pide, la tablatura de la guitarra y los tresillos."""
    import sys
    import pretty_midi
    d = tempfile.mkdtemp()
    fake = os.path.join(d, "fake_mscore.py")
    with open(fake, "w", encoding="utf-8") as f:  # como MuseScore: -M opciones, -o salida, entrada
        f.write("""import shutil, sys
a = sys.argv[1:]
out, src = a[a.index("-o") + 1], a[-1]
if out.endswith(".mscx") and "-M" in a:
    opts = open(a[a.index("-M") + 1]).read()
    open(out, "w").write('<museScore><Score><Part><Staff id="1"><StaffType group="pitched"><name>stdNormal</name>'
                         '<lines>5</lines></StaffType></Staff><Instrument>' + '<StringData><frets>24</frets>' +
                         '<string>40</string>' * 6 + '</StringData></Instrument></Part>' +
                         '<Part><Staff id="2"/><Instrument/></Part></Score><!--' + opts + '--></museScore>')
else:
    shutil.copyfile(src, out)
""")
    bat = os.path.join(d, "MuseScore4.bat")
    with open(bat, "w") as f:
        f.write(f'@"{sys.executable}" "{fake}" %*\n')
    midi = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(engine.program("guitarra"), name="GUITARRA")
    inst.notes += [pretty_midi.Note(velocity=90, pitch=52 + i, start=i * 0.25, end=i * 0.25 + 0.2) for i in range(8)]
    midi.instruments.append(inst)
    mid = os.path.join(d, "guitarra.mid")
    engine._finish_midi(midi, mid, engine.grid_for(None, 120), quant=4)
    real = engine.find_musescore
    engine.find_musescore = lambda: bat
    try:
        out = engine.sheets(mid)
    finally:
        engine.find_musescore = real
    assert [os.path.basename(p) for p in out] == ["guitarra.pdf", "guitarra.musicxml", "guitarra-tab.pdf"], out
    tab, plain = open(out[2]).read(), open(out[0]).read()
    assert 'group="tablature"' in tab and "<lines>6</lines>" in tab and "tab6StrCommon" in tab, tab
    assert 'group="tablature"' not in plain and "<Triplets>true</Triplets>" in plain  # cuantizado: busca tresillos
    assert tab.count("tablature") == 1  # la parte sin cuerdas no cambia
    if real():  # con MuseScore instalado, de verdad: las marcas rdstems: no quedan impresas
        out = engine.sheets(mid)
        assert len(out) == 3 and "rdstems" not in open(out[1], encoding="utf-8").read(), out


def test_utf8_console():
    """Una ruta con «⧸» (títulos de YouTube) no tumba los print de las librerías en una consola cp1252."""
    import io
    import sys
    real, sys.stdout = sys.stdout, io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    try:
        engine.utf8_console()
        print("Predicting MIDI for Boards of Canada ⧸ Roygbiv.wav...")
    finally:
        sys.stdout = real


def test_child():
    """El proceso aparte que la app puede cancelar: líneas JSON por stdout y el error como última línea."""
    import json
    import subprocess
    import sys
    d = tempfile.mkdtemp()
    song = os.path.join(d, "tono.wav")
    sf.write(song, tone([220], 4), SR)
    hw = dict(kind="cpu", name="CPU", vram=0.0, fp16=False, ram=8, cores=4, roomy=False)

    def child(audio):
        p = subprocess.run([sys.executable, engine.__file__, json.dumps([audio, d, [], [], "fast", True, hw])],
                           capture_output=True, encoding="utf-8")
        return p.returncode, [json.loads(line) for line in p.stdout.splitlines()]
    code, lines = child(song)
    assert code == 0 and ["step", "Analizando"] in lines, lines
    code, lines = child(song + "x")
    assert code == 1 and lines[-1][0] == "error" and "Traceback" in lines[-1][1]


def test_spotify():
    """Sin internet: página de Spotify y búsqueda de YouTube falsas."""
    import urllib.request
    page = ('<meta property="og:title" content="Bohemian Rhapsody - Remastered 2011"/>'
            '<meta name="music:musician_description" content="Queen &amp; Co"/><meta name="music:duration" content="354"/>')

    class Resp:
        def __init__(self, url):
            self.url = url

        def read(self):
            return page.encode()
    asked, real = [], (urllib.request.urlopen, engine.youtube_search)
    urllib.request.urlopen = lambda req, timeout=0: Resp(req.full_url)
    engine.youtube_search = lambda q, n=10: asked.append(q) or [("a", "live", 420), ("b", "oficial", 355), ("c", "corta", 200)]
    try:
        assert engine.spotify_to_youtube("https://open.spotify.com/track/x?si=1")[0] == "b"  # la duración más parecida
        assert asked == ["Queen & Co - Bohemian Rhapsody - Remastered 2011"]
        try:
            engine.spotify_to_youtube("https://open.spotify.com/album/x")
            assert False
        except ValueError as e:
            assert "álbumes" in str(e)
    finally:
        urllib.request.urlopen, engine.youtube_search = real


if __name__ == "__main__":
    test_sheets()
    test_beat_grid()
    test_fetch()
    test_utf8_console()
    test_child()
    test_spotify()
    test_reuse()
    test_gpu_fallback()
    test_plan()
    test_step_weights()
    test_residual()
    test_chords()
    test_drums_midi()
    test_hardware()
    test_quantize()
    test_truncated_model()
    test_tempo()
    test_key()
    test_stem_analysis()
    test_midi()
    print("OK")
