"""Motor de separación y análisis. Sin interfaz: se puede usar solo desde código."""
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import threading

import numpy as np
import soundfile as sf

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(APP_DIR, "models")
SR = 44100  # todos los modelos trabajan a 44.1 kHz estéreo

# Mejores modelos públicos a la fecha (comunidad UVR / MVSEP).
VOCAL_MODELS = ["bs_roformer_vocals_resurrection_unwa.ckpt", "melband_roformer_big_beta6x.ckpt"]
SW_MODEL = "BS-Roformer-SW.ckpt"  # voz, bajo, batería, guitarra, piano, otros
DRUM_MODEL = "MDX23C-DrumSep-aufr33-jarredou.ckpt"  # bombo, tarola, toms, hihat, ride, crash
KARAOKE_MODEL = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"  # voz principal / coros
DEREVERB_MODEL = "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt"
DENOISE_MODEL = "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt"
# 53 instrumentos (ZFTurbo / MVSep). Es el único modelo público que separa sintetizador, viento y cuerdas.
MEGA_MODEL = "mvsep_mega_model_bs_roformer_53_stems_v1.ckpt"
MEGA_YAML = "mvsep_mega_model_bs_roformer_53_stems.yaml"
MEGA_URL = "https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v1.0.21/"
MEGA_BYTES_PER_S = 53 * 2 * SR * 4 * 2  # búferes de suma por segundo de audio (53 stems, estéreo, float32, x2)

# Qué se puede pedir: clave -> (modelo que lo da, nombre del stem en ese modelo)
STEMS = {
    "voz": ("vocal", "vocals"), "bateria": ("sw", "drums"), "bateria6": ("drumsep", None),
    "bajo": ("sw", "bass"), "guitarra": ("sw", "guitar"), "teclado": ("sw", "piano"),
    "sintetizador": ("mega", "synth"), "viento": ("mega", "wind"), "cuerdas": ("mega", "strings"),
}
# Extras sobre la voz separada: extra -> (modelo, {stem del modelo: archivo}, paso)
VOICE_FX = {
    "coros": (KARAOKE_MODEL, {"vocals": "voz_principal", "instrumental": "coros"}, "Voz principal y coros"),
    "sin_reverb": (DEREVERB_MODEL, {"noreverb": "voz_seca"}, "Voz sin reverberación"),
    "sin_ruido": (DENOISE_MODEL, {"dry": "voz_limpia"}, "Voz sin ruido"),
}
PIECES = {"kick": "bombo", "snare": "tarola", "toms": "toms", "hh": "hihat", "ride": "ride", "crash": "crash"}
GM_DRUMS = {"bombo": 36, "tarola": 38, "toms": 45, "hihat": 42, "ride": 51, "crash": 49}  # notas General MIDI

KEY_NAMES = ["Do", "Do#", "Re", "Re#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"]
KEY_EN = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Perfiles Krumhansl-Kessler
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Dos hilos que importan scipy/librosa por primera vez a la vez se bloquean (_DeadlockError en error.log).
# Un solo hilo los importa al arrancar; todo hilo que los use espera con ready().
HEAVY = ("torch", "scipy.signal", "librosa", "pretty_midi", "audio_separator.separator", "basic_pitch.inference")


def _warm():
    import importlib
    for m in HEAVY:
        try:
            importlib.import_module(m)
        except Exception:
            pass  # el import real al usarlo muestra el error verdadero


_WARM = threading.Thread(target=_warm, daemon=True)
if __name__ != "__main__":  # el proceso de separación (abajo) tiene un solo hilo: no le hace falta
    _WARM.start()
ready = _WARM.join


def utf8_console():
    """La consola de Windows es cp1252: un nombre con «⧸» (así cambia YouTube la «/» de los títulos) hacía fallar
    los print de las librerías (Basic Pitch imprime la ruta) y con ellos la conversión. Lo que no se pueda mostrar se
    reemplaza; el archivo no se toca."""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- hardware

def ram_gb():
    if os.name == "nt":
        import ctypes

        class MEM(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong) for n in ("total", "avail", "pt", "apt", "vt", "avt", "ext")]
        m = MEM()
        m.len = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total / 2 ** 30
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30


def hardware():
    """Qué hay en el equipo y cómo conviene usarlo. La app lo muestra y la separación se ajusta sola."""
    import torch
    hw = dict(kind="cpu", name="CPU", vram=0.0, fp16=False, ram=ram_gb(), cores=os.cpu_count() or 1)
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        # media precisión nativa: desde Volta/Turing (7.x) hay núcleos tensor; en tarjetas más viejas no acelera
        hw.update(kind="cuda", name=p.name, vram=p.total_memory / 2 ** 30, fp16=p.major >= 7)
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        hw.update(kind="mps", name="Apple Silicon", vram=hw["ram"], fp16=True)  # memoria unificada
    hw["roomy"] = hw["kind"] != "cpu" and hw["vram"] >= 8  # cabe el trozo largo del modelo de 53 stems
    return hw


OOM = re.compile(r"out of memory|can(?:no|')t allocate memory|bad_alloc|not enough memory|DefaultCPUAllocator", re.I)
NO_KERNEL = re.compile(r"no kernel image|invalid device function", re.I)


def explain(tb):
    """Última línea de un traceback, o qué hacer cuando es memoria o una GPU no compatible (idea de StemKit)."""
    if OOM.search(tb):
        return ("Se acabó la memoria al separar. Cierra programas pesados, usa calidad RÁPIDA "
                "o separa menos instrumentos a la vez (SINTETIZADOR, VIENTO y CUERDAS son los que más piden).")
    if NO_KERNEL.search(tb):
        return "Esta versión de PyTorch no es compatible con tu tarjeta. Vuelve a correr install.bat."
    lines = tb.strip().splitlines()
    last = lines[-1][:400] if lines else "Error desconocido"
    if "yt_dlp" in tb:  # YouTube cambia seguido y rompe yt-dlp hasta que sale una versión nueva
        return f"YouTube no dejó bajar el audio ({last}). Si sigue pasando, corre install.bat: actualiza yt-dlp."
    return last


# ---------------------------------------------------------------- separación

def ensure_ffmpeg():
    """audio-separator necesita 'ffmpeg' en el PATH; usamos el binario de imageio-ffmpeg."""
    if shutil.which("ffmpeg"):
        return
    import imageio_ffmpeg
    bin_dir = os.path.join(APP_DIR, "bin")
    exe = os.path.join(bin_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not os.path.exists(exe):
        os.makedirs(bin_dir, exist_ok=True)
        shutil.copy(imageio_ffmpeg.get_ffmpeg_exe(), exe)
        os.chmod(exe, 0o755)
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]


# ---------------------------------------------------------------- YouTube (idea de StemKit)
# yt-dlp necesita un intérprete de JavaScript para los retos de YouTube: el deno que instala install.bat en .venv.
# Solo para uso personal: bajar audio de YouTube va contra sus términos para productos públicos.

def _yt(**opts):
    from yt_dlp import YoutubeDL
    deno = os.path.join(os.path.dirname(sys.executable), "deno.exe" if os.name == "nt" else "deno")
    return YoutubeDL(dict(quiet=True, no_warnings=True, noprogress=True, noplaylist=True,
                          js_runtimes={"deno": {"path": deno}} if os.path.exists(deno) else {"deno": {}}, **opts))


def youtube_search(query, n=10):
    """[(url, título, segundos)] de los primeros n resultados."""
    with _yt(extract_flat=True) as y:
        info = y.extract_info(f"ytsearch{n}:{query}", download=False)
    return [(e["url"], e.get("title") or e["url"], e.get("duration") or 0) for e in info.get("entries") or []]


def spotify_to_youtube(url):
    """Link de una canción de Spotify -> (url, título, segundos) del video de YouTube que la tiene.
    Como spotDL pero sin cuenta ni API: título, artista y duración salen de la página pública de la canción,
    y entre los primeros resultados gana el de duración más parecida. El audio es el de YouTube, no el de Spotify."""
    import html
    import urllib.request
    resp = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20)
    if "/track/" not in resp.url:  # sigue redirecciones: los links cortos spotify.link también sirven
        raise ValueError("Solo links de canciones de Spotify (open.spotify.com/track/...), no playlists ni álbumes.")
    page = resp.read().decode("utf-8", "replace")

    def meta(key):
        m = re.search(rf'<meta (?:name|property)="{key}" content="([^"]*)"', page)
        return html.unescape(m[1]) if m else ""
    query, secs = f'{meta("music:musician_description")} - {meta("og:title")}'.strip(" -"), int(meta("music:duration") or 0)
    found = youtube_search(query, 5) if query else []
    if not found:
        raise ValueError(f"No encontré «{query or url}» en YouTube.")
    return min(found, key=lambda r: abs(r[2] - secs)) if secs else found[0]


def youtube_audio(url, folder, log=print):
    """Baja el audio de un video a folder/<título>.flac (sin pérdida desde lo que da YouTube) y devuelve la ruta."""
    ensure_ffmpeg()
    last = [-10]

    def hook(d):
        pct = int(100 * d.get("downloaded_bytes", 0) / (d.get("total_bytes") or d.get("total_bytes_estimate") or 1))
        if d["status"] == "downloading" and pct >= last[0] + 10:
            last[0] = pct
            log(f"Bajando de YouTube {pct}%")
    with _yt(format="bestaudio/best", outtmpl=os.path.join(folder, "%(title)s.%(ext)s"), progress_hooks=[hook],
             postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "flac"}]) as y:
        info = y.extract_info(url)
        return os.path.splitext(y.prepare_filename(info))[0] + ".flac"


def _drop_if_truncated(path, log):
    """Una descarga cortada deja un .ckpt zip sin directorio central; se borra para que se vuelva a bajar.
    Los .ckpt de formato viejo (no zip) no empiezan con PK y no se tocan."""
    import zipfile
    if not os.path.isfile(path):
        return
    with open(path, "rb") as f:
        is_zip = f.read(2) == b"PK"
    if is_zip and not zipfile.is_zipfile(path):
        log("Modelo incompleto: se baja de nuevo")
        os.remove(path)


def _fetch(url, path, log):
    """Baja a path.part y, si se cortó antes, sigue donde quedó (Range). Solo al terminar queda como path."""
    import urllib.error
    import urllib.request
    part = path + ".part"
    os.makedirs(os.path.dirname(path), exist_ok=True)  # instalación nueva: models/ todavía no existe
    have = os.path.getsize(part) if os.path.exists(part) else 0
    log("Bajando modelo (solo la 1a vez)" + (" · sigue donde quedó" if have else ""))
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"Range": f"bytes={have}-"}), timeout=60)
    except urllib.error.HTTPError as e:
        if e.code != 416:  # 416: el .part ya estaba completo
            raise
    else:
        with r, open(part, "ab" if r.status == 206 else "wb") as f:
            have = have if r.status == 206 else 0  # el servidor no reanuda: desde cero
            total, last = have + int(r.headers.get("Content-Length") or 0), -1
            while chunk := r.read(1 << 20):
                f.write(chunk)
                have += len(chunk)
                pct = have * 100 // total if total else 0
                if pct != last and pct % 5 == 0:  # sin esto la barra parece congelada durante 1.3 GB
                    last = pct
                    log(f"Bajando modelo {pct}%")
    os.replace(part, path)


def _register_mega(log):
    """El modelo de 53 stems no viene en la lista de audio-separator: se baja aparte y se registra."""
    from audio_separator.separator import Separator
    from audio_separator.separator.roformer.parameter_validator import ParameterValidator
    os.makedirs(MODEL_DIR, exist_ok=True)
    for name in (MEGA_YAML, MEGA_MODEL):
        path = os.path.join(MODEL_DIR, name)
        _drop_if_truncated(path, log)
        if not os.path.exists(path):
            _fetch(MEGA_URL + name, path, log)
    ParameterValidator.PARAMETER_RANGES["num_stems"] = (1, 64)  # el validador asume 16 como máximo
    if getattr(Separator, "_rd_mega", False):
        return
    original = Separator.list_supported_model_files

    def with_mega(self):
        models = original(self)
        models.setdefault("MDXC", {})["Roformer Model: MVSep Mega 53"] = {
            "filename": MEGA_MODEL, "download_files": [MEGA_MODEL, MEGA_YAML], "scores": {}, "stems": [],
            "target_stem": None}
        return models
    Separator.list_supported_model_files = with_mega
    Separator._rd_mega = True


def _separate(audio, model, quality, hw, log, duration=0.0):
    """Corre un modelo (o lista = ensamble) y devuelve ({stem_en: ruta_temporal}, carpeta_temporal).
    Si la GPU se queda sin memoria o no es compatible, repite el paso en el procesador."""
    tmp = tempfile.mkdtemp(prefix="rds_")
    try:
        return _run(audio, model, quality, hw, log, duration, tmp), tmp
    except Exception as e:
        if hw["kind"] == "cpu" or not (OOM.search(str(e)) or NO_KERNEL.search(str(e))):
            raise
    # fuera del except: el traceback guarda el modelo en la GPU y empty_cache no la liberaría
    import gc
    import torch
    log("La GPU no pudo con este paso: se repite en el procesador (más lento)")
    gc.collect()
    torch.cuda.empty_cache()  # no hace nada si CUDA nunca arrancó
    return _run(audio, model, quality, dict(hw, kind="cpu", fp16=False, roomy=False), log, duration, tmp), tmp


def _run(audio, model, quality, hw, log, duration, tmp):
    import logging
    from audio_separator.separator import Separator

    mega = model == MEGA_MODEL
    if mega:
        _register_mega(log)
    roformer = model != DRUM_MODEL  # DrumSep es MDX23C: la media precisión nativa solo está verificada en RoFormer
    piece = max(30.0, hw["ram"] * 0.4 * 2 ** 30 / MEGA_BYTES_PER_S)  # segundos que caben en el 40% de la RAM
    sep = Separator(
        log_level=logging.WARNING,
        model_file_dir=MODEL_DIR,
        output_dir=tmp,
        normalization_threshold=1.0,  # solo evita clipping, conserva niveles reales entre stems
        use_native_fp16=hw["fp16"] and roformer,
        use_autocast=hw["fp16"] and not roformer and hw["kind"] == "cuda",
        ensemble_algorithm="avg_fft" if isinstance(model, list) else None,
        # 53 stems ocupan mucha RAM al sumar: canciones largas se procesan por partes del tamaño que quepa
        chunk_duration=piece if mega and duration > piece else None,
        mdxc_params={"segment_size": 256, "batch_size": None, "pitch_shift": 0,
                     # trozos de 3 s para el modelo de 53 stems si la GPU es chica o no hay GPU
                     "override_model_segment_size": mega and not hw["roomy"],
                     # overlap = veces que se calcula cada trozo; de 4 a 8 la mejora es marginal y cuesta el doble
                     # el de 53 stems ya es el más lento: siempre overlap 2 (subir si la calidad importa más que el tiempo)
                     "overlap": 4 if quality == "max" and not mega else 2},
    )
    if hw["kind"] == "cpu":  # audio-separator elige la GPU por su cuenta; en el reintento se fuerza el procesador
        sep.torch_device = sep.torch_device_cpu
        sep.onnx_execution_provider = ["CPUExecutionProvider"]
    for name in [model] if isinstance(model, str) else model:
        _drop_if_truncated(os.path.join(MODEL_DIR, name), log)
    # audio-separator baja sus modelos de una sola vez y sin avance; así siguen donde quedaron si se cortan
    sep.download_file_if_not_exists = lambda url, out: os.path.isfile(out) or _fetch(url, out, log)
    log("Cargando modelo")
    sep.load_model(model)
    log("Separando...")
    sep.separate(audio)
    return {stem_name(f): f for f in glob.glob(os.path.join(tmp, "*.wav")) if stem_name(f)}


def stem_name(path):
    """"cancion_(Vocals)_modelo.wav" -> "vocals"; por partes audio-separator escribe "cancion_(vocals).wav"."""
    found = re.findall(r"\(([^)]+)\)", os.path.basename(path))
    return found[-1].lower() if found else None


def plan(stems, extras, quality, drums_ready=False):
    """Pases de separación según lo pedido: modelos y luego extras de voz.
    La voz rápida sale del mismo pase del SW si ese pase ocurre.
    drums_ready: bateria.wav ya está en la carpeta y DrumSep sale de ahí, sin pasar otra vez por el SW."""
    models = {STEMS[s][0] for s in stems}
    if "bateria6" in stems and not drums_ready:
        models.add("sw")
    if "vocal" in models and quality == "fast" and "sw" in models:
        models.discard("vocal")  # evita un pase completo; en MÁX la voz dedicada es más limpia
    fx = [e for e in VOICE_FX if e in extras] if "voz" in stems else []
    return [m for m in ("vocal", "sw", "drumsep", "mega") if m in models], fx


DONE = "separacion.json"  # {stem o extra: calidad} de lo que ya está en la carpeta de stems


def _files(k, out_dir):
    if k == "bateria6":
        return [os.path.join(out_dir, "bateria_6")]
    return [os.path.join(out_dir, n + ".wav") for n in (VOICE_FX[k][1].values() if k in VOICE_FX else [k])]


def _source(audio):
    st = os.stat(audio)
    return [st.st_size, int(st.st_mtime)]


def _done(out_dir, audio):
    """Lo hecho en out_dir; vacío si la canción cambió desde entonces (se volvió a exportar con el mismo nombre)."""
    try:
        with open(os.path.join(out_dir, DONE), encoding="utf-8") as f:
            done = json.load(f)
        return done if done.pop("_fuente", None) == _source(audio) else {}
    except (OSError, ValueError):
        return {}


def pending(out_dir, stems, extras, quality, audio):
    """(modelos, extras, ya hechos): lo separado antes en out_dir con calidad igual o mejor
    (MÁX sirve para RÁPIDA) y cuyos archivos siguen ahí no se vuelve a separar (idea de StemKit)."""
    ok = ("max",) if quality == "max" else ("max", "fast")
    have = {k for k, q in _done(out_dir, audio).items() if q in ok and all(map(os.path.exists, _files(k, out_dir)))}
    models, _ = plan(set(stems) - have, (), quality, drums_ready="bateria" in have)
    return models, [e for e in plan(stems, extras, quality)[1] if e not in have], have


def outputs(stems, extras):
    """Cuántos archivos salen (para la barra de progreso del análisis)."""
    n = len(stems - {"bateria6"}) + 1 + 6 * ("bateria6" in stems)  # + resto
    return n + sum(len(VOICE_FX[e][1]) for e in plan(stems, extras, "max")[1])


def _write(path, y):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, y, SR, subtype="PCM_24")
    return path


def residual(mix, parts):
    """Lo que queda de la mezcla al quitar los stems elegidos: así todo lo exportado suma la canción."""
    rest = mix.copy()
    for p in parts:
        n = min(len(rest), len(p))
        rest[:n] -= p[:n]
    return rest


def separate_all(audio, out_dir, stems, extras, quality, hw, log, step):
    """Devuelve {grupo: {stem: ruta}}. Los stems quedan en out_dir; la batería por piezas en out_dir/bateria_6.
    Lo que ya estaba separado en out_dir se reutiliza (ver pending)."""
    import librosa
    ensure_ffmpeg()
    mix = librosa.load(audio, sr=SR, mono=False)[0].T
    mix = np.stack([mix, mix], 1) if mix.ndim == 1 else mix
    duration = len(mix) / SR
    got, temps = {}, []  # stem_en de cada modelo -> ruta temporal
    models, fx, have = pending(out_dir, stems, extras, quality, audio)
    redo, old = (set(stems) | set(fx)) - have, _done(out_dir, audio)
    done = {k: v for k, v in old.items() if k not in redo}
    if len(done) < len(old):  # si se cancela a medias, lo que se estaba rehaciendo no queda como hecho
        _save(out_dir, dict(done, _fuente=_source(audio)))
    reused = sorted(have & (set(stems) | set(extras)))
    if reused:
        log("Ya separado antes, se reutiliza: " + ", ".join(reused))
    drums = lambda: got["sw"]["drums"] if "sw" in got else os.path.join(out_dir, "bateria.wav")  # noqa: E731
    for s in models:
        if s == "vocal":
            step("Voz")
            res, tmp = _separate(audio, VOCAL_MODELS if quality == "max" else VOCAL_MODELS[0], quality, hw, log)
            got["vocal"] = res
        elif s == "sw":
            step("Bajo, batería, guitarra, teclado")
            got["sw"], tmp = _separate(audio, SW_MODEL, quality, hw, log)
        elif s == "drumsep":
            step("Batería por piezas")
            got["drumsep"], tmp = _separate(drums(), DRUM_MODEL, quality, hw, log)
        elif s == "mega":
            step("Synth, viento, cuerdas")
            got["mega"], tmp = _separate(audio, MEGA_MODEL, quality, hw, log, duration)
        temps.append(tmp)
    if "vocal" not in got and "voz" in stems and "voz" not in have:
        got["vocal"] = {"vocals": got["sw"]["vocals"]}

    main, parts = {}, []
    for s in [k for k in STEMS if k in stems and k != "bateria6"]:  # orden fijo, como en la placa
        path = os.path.join(out_dir, s + ".wav")
        if s in have:
            main[s] = path
            parts.append(sf.read(path, dtype="float32")[0])
            continue
        model, name = STEMS[s]
        y = sf.read(got[model][name], dtype="float32")[0]
        main[s] = _write(path, y)
        parts.append(y)
    kit = os.path.join(out_dir, "bateria_6")
    if "bateria6" in stems and "bateria" not in stems:
        if "sw" in got or "bateria" in have:
            parts.append(sf.read(drums(), dtype="float32")[0])
        else:  # kit reutilizado sin bateria.wav: la suma de las piezas casi iguala la batería del SW
            parts.append(sum(sf.read(f, dtype="float32")[0] for f in glob.glob(os.path.join(kit, "*.wav"))))
    if stems:
        main["resto"] = _write(os.path.join(out_dir, "resto.wav"), residual(mix, parts))
    results = {"Stems": main}

    for e in plan(stems, extras, quality)[1]:
        model, names, label = VOICE_FX[e]
        if e not in fx:  # ya hecho
            main.update({n: os.path.join(out_dir, n + ".wav") for n in names.values()})
            continue
        step(label)
        res, tmp = _separate(main["voz"], model, quality, hw, log)
        temps.append(tmp)
        for stem, name in names.items():
            path = res.get(stem) or next(p for k, p in res.items() if k not in names)  # nombres varían por modelo
            main[name] = _write(os.path.join(out_dir, name + ".wav"), sf.read(path, dtype="float32")[0])

    if "bateria6" in stems:
        if "bateria6" in have:
            results["Batería 6"] = {es: os.path.join(kit, es + ".wav") for es in PIECES.values()
                                    if os.path.exists(os.path.join(kit, es + ".wav"))}
        else:
            results["Batería 6"] = {es: _write(os.path.join(kit, es + ".wav"), sf.read(got["drumsep"][en], dtype="float32")[0])
                                    for en, es in PIECES.items() if en in got["drumsep"]}
    for t in temps:  # el modelo de 53 stems deja ~50 WAV que no se usan
        shutil.rmtree(t, ignore_errors=True)
    done.update({k: quality for k in redo}, _fuente=_source(audio))
    _save(out_dir, done)
    return results


def _save(out_dir, done):
    with open(os.path.join(out_dir, DONE), "w", encoding="utf-8") as f:
        json.dump(done, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- análisis

def detect_key(y, sr):
    import librosa
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    best = (-2, "", 0)
    for i in range(12):
        for prof, mode in ((MAJOR, "mayor"), (MINOR, "menor")):
            r = np.corrcoef(chroma, np.roll(prof, i))[0, 1]
            if r > best[0]:
                best = (r, f"{KEY_EN[i]} {'major' if mode == 'mayor' else 'minor'} ({KEY_NAMES[i]} {mode})", r)
    return best[1], float(best[2])


def detect_tempo(y, sr):
    """beat_track cuantiza el BPM a la rejilla del hop; la mediana entre beats da décimas reales."""
    import librosa
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=256, units="time")
    if len(beats) > 4:
        d = np.diff(beats)
        d = d[np.abs(d - np.median(d)) < 0.1 * np.median(d)]  # fuera beats perdidos/dobles
        return round(60 / float(d.mean()), 1)
    return round(float(np.atleast_1d(tempo)[0]), 1)


def detect_chords(y, sr, pulse=None):
    """Acordes mayores y menores cada dos tiempos: croma alineado al pulso contra 24 plantillas. Con el pulso de
    beat-this, los pares empiezan en el tiempo fuerte. Triadas nada más; séptimas y suspendidos caen en
    la triada más cercana."""
    import librosa
    if pulse:
        beats = librosa.time_to_frames(pulse["pulsos"], sr=sr)
        beats = beats[_nearest(pulse["pulsos"], pulse["primero"]) % 2:]
    else:
        beats = librosa.beat.beat_track(y=y, sr=sr)[1]
    full = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma = librosa.util.sync(full, beats[::2], aggregate=np.median)
    # los mismos bordes que usa sync: agrega el 0 solo si el primer pulso no cae ahí
    times = librosa.frames_to_time(librosa.util.fix_frames(beats[::2], x_min=0, x_max=full.shape[1])[:-1], sr=sr)
    templates, names = [], []
    for i in range(12):
        for third, suffix in ((4, ""), (3, "m")):
            t = np.zeros(12)
            t[[i, (i + third) % 12, (i + 7) % 12]] = 1
            templates.append(t / np.linalg.norm(t))
            names.append(KEY_EN[i] + suffix)
    norm = chroma / (np.linalg.norm(chroma, axis=0, keepdims=True) + 1e-9)
    best = (np.array(templates) @ norm).argmax(axis=0)
    chords = []
    for t, b, energy in zip(times, best, chroma.sum(axis=0)):
        if energy > 1e-3 and (not chords or chords[-1][1] != names[b]):
            chords.append((round(float(t), 2), names[b]))
    return chords


VISTA_HZ = (20, 20000)  # rango vertical de la vista, en escala logarítmica
VISTA_H, VISTA_W = 320, 1600


def spectro_vista(D, sr, out):
    """Espectrograma en gris de 8 bits sin ejes: la app lo tiñe con los colores del tema y dibuja su propia regla."""
    from PIL import Image
    if not np.ptp(D):  # silencio total: amplitude_to_db da 0 dB parejo, se pinta como fondo
        D = np.full_like(D, -90)
    freqs = np.linspace(0, sr / 2, D.shape[0])
    rows = np.interp(np.geomspace(*VISTA_HZ, VISTA_H), freqs, np.arange(len(freqs))).round().astype(int)
    img = D[rows[::-1]]  # agudos arriba
    k = -(-img.shape[1] // VISTA_W)  # máximo por bloques, conserva los golpes al reducir
    img = np.pad(img, ((0, 0), (0, -img.shape[1] % k)), constant_values=-90).reshape(VISTA_H, -1, k).max(axis=2)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    Image.fromarray(((img + 90) / 90 * 255).clip(0, 255).astype(np.uint8)).save(out)


def analyze_stem(path, png):
    import librosa
    from scipy.signal import find_peaks

    y, sr = librosa.load(path, sr=SR, mono=True)
    peak = float(np.abs(y).max()) or 1e-9
    rms = float(np.sqrt(np.mean(y ** 2))) or 1e-9
    S = np.abs(librosa.stft(y, n_fft=8192, hop_length=2048))
    spec = S.mean(axis=1)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=8192)
    energy = np.cumsum(spec ** 2)
    energy /= energy[-1] if energy[-1] > 0 else 1
    last = len(freqs) - 1  # stem en silencio: energía 0, searchsorted se sale del rango
    lo, hi = freqs[min(np.searchsorted(energy, 0.05), last)], freqs[min(np.searchsorted(energy, 0.95), last)]
    centroid = float(librosa.feature.spectral_centroid(S=S, sr=sr).mean())

    silent = 20 * np.log10(rms) < -60
    db = 20 * np.log10(spec + 1e-12)
    band = (freqs > 20) & (freqs < 16000)
    idx, _ = find_peaks(np.where(band, db, db.min()), prominence=6, distance=3)
    idx = [] if silent else sorted(idx, key=lambda i: db[i], reverse=True)[:5]
    peaks = [{"hz": round(float(freqs[i]), 1), "nota": librosa.hz_to_note(freqs[i], unicode=False),
              "db": round(float(db[i] - db.max()), 1)} for i in sorted(idx)]

    D = librosa.amplitude_to_db(np.abs(librosa.stft(y, n_fft=4096, hop_length=1024)), ref=np.max, top_db=90)
    spectro_vista(D, sr, png)
    return {
        "pico_dBFS": round(20 * np.log10(peak), 1),
        "rms_dBFS": round(20 * np.log10(rms), 1),
        "centroide_hz": round(centroid),
        "rango_hz": [round(float(lo)), round(float(hi))],
        "picos": peaks,
        "casi_silencio": bool(silent),
        "vista": png,
        "duracion_s": round(len(y) / sr, 2),
    }


def analyze_all(audio, results, out_dir, log, step):
    import librosa
    step("Analizando")
    spec_dir = os.path.join(out_dir, "espectrogramas")
    y, sr = librosa.load(audio, sr=22050, mono=True)
    key, conf = detect_key(y, sr)
    pulse = detect_beats(y, sr, log)  # sobre la mezcla: en la batería sola la tarola parte el tempo a la mitad
    report = {
        "archivo": audio,
        "duracion_s": round(len(y) / sr, 1),
        "tempo_bpm": pulse["bpm"] if pulse else detect_tempo(y, sr),
        "pulso": pulse,
        "tonalidad": key,
        "confianza_tonalidad": round(conf, 2),
        "acordes": detect_chords(y, sr, pulse),
        "stems": {},
    }
    log(f"{report['tempo_bpm']} BPM" + (f" · {pulse['compas']}/4" if pulse and pulse["compas"] else "") + f" · {key}")
    items = [("Mezcla original", "original", audio)] + [
        (g, s, p) for g, stems in results.items() for s, p in stems.items()]
    for group, stem, path in items:
        step(f"Analizando {stem}")
        slug = re.sub(r"\W+", "_", f"{group}_{stem}").lower()
        report["stems"][f"{group} / {stem}"] = dict(analyze_stem(path, os.path.join(spec_dir, slug + ".png")), ruta=path)
    with open(os.path.join(out_dir, "analisis.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def process(audio, out_dir, stems, extras, quality, analyze, hw, log=print, step=print):
    results = separate_all(audio, out_dir, stems, extras, quality, hw, log, step)
    report = analyze_all(audio, results, out_dir, log, step) if analyze else None
    return results, report


# peso de cada paso en el tiempo total; a ojo, la app lo corrige con lo que mide
WEIGHT = {"vocal": 10, "sw": 10, "drumsep": 3, "mega": 25}


def step_weights(stems, extras, quality, analyze, out_dir="", audio=""):
    """Un peso por cada llamada a step(), en el orden en que ocurren (sin lo que se reutiliza de out_dir)."""
    models, fx, _ = pending(out_dir, stems, extras, quality, audio)
    w = [WEIGHT[m] * (2 if m == "vocal" and quality == "max" else 1) for m in models] + [4] * len(fx)
    return w + [1] * (2 + outputs(stems, extras)) if analyze else w


# ---------------------------------------------------------------- pulso (ideas de MuScriptor, MIT)

BEAT_URL = "https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt"  # beat-this (CP JKU, MIT)


def _nearest(beats, t):
    return int(np.abs(np.asarray(beats) - t).argmin())


def _regular(beats):
    """Pone los pulsos que el detector se saltó (un corte, un acorde largo) y quita los que sobran."""
    if len(beats) < 3:
        return np.asarray(beats, float)
    period, kept = np.median(np.diff(beats)), [beats[0]]
    for b in beats[1:]:
        apart = (b - kept[-1]) / period
        if apart < 0.7:
            continue
        n = max(1, round(apart))
        kept.extend(kept[-1] + (b - kept[-1]) * np.arange(1, n) / n)
        kept.append(b)
    return np.asarray(kept, float)


def detect_beats(y, sr, log=print):
    """beat-this: cada pulso, el compás (pulsos entre tiempos fuertes, si el 90% coincide), el primer tiempo fuerte
    y si el tempo es estable (metrónomo) o se mueve. None si no hay pulso claro."""
    import torch
    from beat_this.inference import Audio2Beats
    ckpt = os.path.join(MODEL_DIR, "beat_this-final0.ckpt")
    if not os.path.exists(ckpt):
        _fetch(BEAT_URL, ckpt, log)
    if len(y) < sr:
        return None
    beats, downs = Audio2Beats(ckpt, device="cuda" if torch.cuda.is_available() else "cpu", dbn=False)(y, sr)
    beats = _regular(np.asarray(beats, float))
    if len(beats) < 8:
        return None
    k = np.arange(len(beats))
    slope, icpt = np.polyfit(k, beats, 1)
    compas = None
    if len(downs) >= 3:
        c = np.diff([_nearest(beats, d) for d in downs])
        vals, n = np.unique(c[c >= 2], return_counts=True)
        if len(n) and n.max() / n.sum() >= 0.9:
            compas = int(vals[n.argmax()])
    return dict(bpm=round(60 / float(slope), 1), compas=compas, primero=round(float(downs[0] if len(downs) else beats[0]), 3),
                estable=bool((beats - icpt - slope * k).std() <= 0.05 * slope),
                pulsos=[round(float(b), 3) for b in beats])


def grid_for(pulse, bpm=120.0, scale=1, compas=None, primero=None):
    """El pulso con las correcciones de la app: bpm distinto al detectado = tempo constante; scale 2 / 0.5 cuando el
    detector contó la mitad o el doble; compas (0 = sin compás) y primero corrigen las barras. Sin pulso (audio sin
    análisis): tempo constante bpm desde 0 s."""
    first, meter = (pulse["primero"], pulse["compas"]) if pulse else (0.0, None)
    if pulse and abs(bpm - pulse["bpm"] * scale) < 0.05:
        beats, s = np.asarray(pulse["pulsos"], float), scale
        while s > 1:
            beats, s = np.insert(beats, np.arange(1, len(beats)), (beats[:-1] + beats[1:]) / 2), s / 2
        while s < 1:
            beats, s = beats[_nearest(beats, first) % 2::2], s * 2
        if meter and float(meter * scale).is_integer() and meter * scale >= 1:  # 4/4 contado al doble = 8 tiempos
            meter = int(meter * scale)
        g = dict(pulsos=beats, estable=pulse["estable"], primero=first, compas=meter)
    else:  # tempo escrito a mano: constante, desde el primer tiempo fuerte
        p = 60 / bpm
        g = dict(pulsos=first + p * np.arange(-int(first / p) - 1, 600 / p), estable=True, primero=first, compas=meter)
    if compas is not None:
        g["compas"] = compas or None
    if primero is not None:
        g["primero"] = primero
    return g


def _ext(x, xp, fp):
    """np.interp que sigue la pendiente de los extremos en vez de quedarse plano."""
    from scipy.interpolate import interp1d
    out = interp1d(xp, fp, fill_value="extrapolate", assume_sorted=True)(x)
    return float(out) if out.ndim == 0 else out


def _timeline(grid, tol=0.025):
    """(segundos, tiempos): dónde cae cada tiempo de la partitura, con el primer tiempo fuerte en 0. Estable: una
    línea (un solo tempo). Si no, sigue los pulsos suavizados y cambia de tempo solo en las barras donde hace falta
    para que ningún pulso quede a más de tol segundos (sin esto habría un cambio de tempo en cada pulso)."""
    from scipy.signal import savgol_filter
    beats = grid["pulsos"]
    k = np.arange(len(beats)) - _nearest(beats, grid["primero"])
    if grid["estable"]:
        slope = np.polyfit(k, beats, 1)[0]
        return np.array([grid["primero"], grid["primero"] + slope]), np.array([0.0, 1.0])
    if len(beats) >= 9:
        beats = savgol_filter(beats, 9, 2)  # el detector marca en cuadros de 20 ms: eso no es un cambio de tempo
    bar, last = grid["compas"] or 1, len(beats) - 1
    fits = lambda a, b: np.abs(beats[a:b + 1] - np.interp(k[a:b + 1], k[[a, b]], beats[[a, b]])).max() <= tol  # noqa: E731
    cands = [i for i in range(1, last) if k[i] % bar == 0] + [last]
    kept = [0]
    for i, b in enumerate(cands):
        if b == last or not fits(kept[-1], cands[i + 1]):
            kept.append(b)
    return beats[kept], k[kept].astype(float)


def _tempos(times, pos):
    """[(tick, microsegundos por tiempo)] desde el tick 0, solo donde el tempo cambia."""
    us = np.round(np.diff(times) / np.diff(pos) * 1e6).astype(int)
    out = [(0, int(us[0]))]
    for p, u in zip(pos[:-1], us):
        t = max(0, round(p * 480))
        if u != out[-1][1]:
            out[-1:] = [(t, int(u))] if t == out[-1][0] else [out[-1], (t, int(u))]
    return out


def _onset_grid(onsets, beats):
    """(retraso_s, pasos por tiempo): qué tan tarde caen los ataques frente a la subdivisión del pulso donde mejor
    calzan (cada ataque es un vector en un círculo; el promedio da el corrimiento y qué tan juntos están).
    (0, None) si no calzan con ninguna o hay pocos."""
    t = np.unique(np.round(onsets, 3))
    t = t[(t >= beats[0]) & (t <= beats[-1])]
    if len(t) < 40:  # con menos, una rejilla al azar puede parecer buena
        return 0.0, None
    ph, period, best = np.interp(t, beats, np.arange(len(beats))), np.median(np.diff(beats)), None
    for sub in (1, 2, 3, 4, 6, 8, 12, 16, 24):
        if period / (2 * sub) < 0.04:  # rejilla tan fina que no distingue 40 ms tarde de temprano
            break
        m = np.exp(2j * np.pi * np.mod(ph * sub, 1)).mean()
        if not best or abs(m) > best[0]:
            best = (abs(m), float(np.angle(m)) / (2 * np.pi * sub) * period, sub)
    if not best or best[0] < 0.5 or abs(best[1]) > 0.04:
        return 0.0, None
    return best[1], best[2]


# ---------------------------------------------------------------- audio a MIDI

# tipo de sonido -> rango en Hz que Basic Pitch considera (None = todo)
MIDI_RANGES = {"todo": (None, None), "melodia": (80.0, 1400.0), "bajo": (30.0, 400.0)}


def _finish_midi(midi, out, grid, quant=0, strength=1.0, fill=0.0, trim=False, bends=True):
    """Escribe out sobre el pulso (ver grid_for) y devuelve las notas [(inicio_s, fin_s, nota)] en segundos de la
    canción. Las barras de compás caen en los tiempos fuertes: el MIDI empieza en una barra y una marca de texto
    guarda en qué segundo de la canción cae (read_midi la usa para volver a ponerlas en su lugar).
    quant: 0 = libre, -1 = la rejilla en que caen los ataques, n = n pasos por tiempo (2 = 1/8, 3 = tresillos...).
    strength: cuánto se acercan a la rejilla (1 = todo). fill: alarga una nota hasta el siguiente ataque de su
    instrumento si el silencio dura a lo más eso, en tiempos. trim: quita los compases vacíos del inicio."""
    import mido
    notes = [(i, n) for i in midi.instruments for n in i.notes]
    delay, sub = _onset_grid([n.start for _, n in notes], grid["pulsos"])
    sub = sub if quant == -1 else quant
    bar = grid["compas"] or 1
    times, pos = _timeline(grid)
    # el MIDI empieza en una barra antes de la primera nota y del inicio de la canción (con 0.05 tiempos de
    # holgura: unos ms de corrección de retraso no deben agregar un compás vacío)
    first = _ext(min([n.start - delay for _, n in notes] + [0.0]), times, pos)
    pos = pos + bar * np.ceil((-first - 0.05) / bar)
    beat = lambda t: _ext(t - delay, times, pos)  # noqa: E731  ataques corridos por su retraso medido
    placed = {}  # instrumento -> [[inicio, fin, nota, velocity]] en tiempos desde el tick 0
    for inst, n in notes:
        a, b = beat(n.start), beat(n.end)
        if sub:
            qa, qb = round(a * sub) / sub, round(b * sub) / sub
            qb = max(qb, qa + 1 / sub)  # una nota no desaparece al cuantizar
            a, b = a + strength * (qa - a), b + strength * (qb - b)
        placed.setdefault(inst, []).append([a, b, n.pitch, n.velocity])
    for inst, ns in placed.items():
        ns.sort()
        last = {}  # una nota no se monta sobre la siguiente de la misma altura
        for n in reversed(ns):
            n[1] = min(n[1], last.get(n[2], n[1]))
            last[n[2]] = n[0]
        onsets = sorted({n[0] for n in ns})
        for n in (ns if fill and not inst.is_drum else ()):
            nxt = next((o for o in onsets if o > n[0] + 1e-6), None)
            if nxt is not None and 0 < nxt - n[1] <= fill + 1e-6:
                n[1] = nxt
    if trim and notes:
        empty = bar * np.floor(min(n[0] for ns in placed.values() for n in ns) / bar + 1e-6)
        pos = pos - empty
        for ns in placed.values():
            for n in ns:
                n[0] -= empty
                n[1] -= empty
    tick = lambda b: max(0, round(b * 480))  # noqa: E731
    f = mido.MidiFile(ticks_per_beat=480)
    head = [(0, mido.MetaMessage("text", text=f"rdstems:inicio={_ext(0.0, pos, times) + delay:.6f}"))]
    if sub:
        head.append((0, mido.MetaMessage("text", text="rdstems:cuantizado")))
    if grid["compas"]:
        head.append((0, mido.MetaMessage("time_signature", numerator=grid["compas"], denominator=4)))
    head += [(t, mido.MetaMessage("set_tempo", tempo=us)) for t, us in _tempos(times, pos)]
    tracks = [head]
    for ch, (inst, ns) in enumerate(placed.items()):
        ch = 9 if inst.is_drum else ch + (ch >= 9)
        ev = [(0, mido.Message("program_change", channel=ch, program=inst.program))]
        if inst.name:
            ev.insert(0, (0, mido.MetaMessage("track_name", name=inst.name)))
        for a, b, p, v in ns:
            ev += [(tick(a), mido.Message("note_on", channel=ch, note=p, velocity=v)),
                   (max(tick(b), tick(a) + 1), mido.Message("note_off", channel=ch, note=p))]
        if bends:
            ev += [(tick(beat(pb.time)), mido.Message("pitchwheel", channel=ch, pitch=pb.pitch))
                   for pb in inst.pitch_bends]
        tracks.append(ev)
    for ev in tracks:
        track, now = mido.MidiTrack(), 0
        for t, m in sorted(ev, key=lambda e: (e[0], e[1].type == "note_on")):  # en el mismo tick, apagar antes
            track.append(m.copy(time=t - now))
            now = t
        f.tracks.append(track)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    f.save(out)
    secs = lambda b: float(_ext(b, pos, times)) + delay  # noqa: E731  donde suena en la canción
    return sorted((secs(a), secs(b), int(p)) for ns in placed.values() for a, b, p, _ in ns)


def read_midi(path):
    """Notas de un .mid ya escrito, en segundos de la canción: [(inicio_s, fin_s, nota)]."""
    import mido
    import pretty_midi
    start = next((float(m.text.split("=")[1]) for t in mido.MidiFile(path).tracks for m in t
                  if m.type == "text" and m.text.startswith("rdstems:inicio=")), 0.0)
    midi = pretty_midi.PrettyMIDI(path)
    return sorted((float(n.start) + start, float(n.end) + start, int(n.pitch)) for i in midi.instruments for n in i.notes)


# instrumento General MIDI por stem; lo demás (teclado, mezcla, resto) queda en piano
PROGRAMS = {"bajo": 33, "guitarra": 27, "sintetizador": 81, "viento": 65, "cuerdas": 48}


def program(base):
    return 53 if base.startswith(("voz", "coros")) else PROGRAMS.get(base, 0)


def to_midi(wav, out, grid, sensitivity=0.5, min_ms=128.0, kind="todo", bends=True, band=None, program=0, name="",
            **quant):
    """Basic Pitch (Spotify, Apache 2.0): notas polifónicas con pitch bend, escritas en out (.mid).
    Corre con su modelo ONNX y el onnxruntime que ya trae RD Stems; no necesita TensorFlow.
    sensitivity 0..1: más alto = más notas (0.5 = valores de fábrica de Basic Pitch).
    Devuelve [(inicio_s, fin_s, nota_midi)] para dibujarlas sobre el espectrograma. quant: ver _finish_midi."""
    from basic_pitch.inference import predict
    fmin, fmax = band or MIDI_RANGES[kind]  # band: rango propio (CUSTOM) en Hz
    _, midi, _ = predict(wav, onset_threshold=0.8 - 0.6 * sensitivity, frame_threshold=0.5 - 0.4 * sensitivity,
                         minimum_note_length=min_ms, minimum_frequency=fmin, maximum_frequency=fmax)
    for inst in midi.instruments:
        inst.program, inst.name = program, name
    return _finish_midi(midi, out, grid, bends=bends, **quant)


def midi_audio(notes, sr=SR):
    """Las notas como tonos simples, para escuchar el MIDI antes de llevarlo al DAW."""
    end = max((e for _, e, _ in notes), default=0)
    y = np.zeros(int(end * sr) + sr // 10, np.float32)
    for s, e, p in notes:
        t = np.arange(int((e - s) * sr)) / sr
        tone = np.sin(2 * np.pi * 440 * 2 ** ((p - 69) / 12) * t) * np.minimum(1, (e - s - t) * 50)  # sin clics
        y[int(s * sr):int(s * sr) + len(tone)] += tone * 0.15
    return np.clip(y, -1, 1)


def drums_to_midi(pieces, out, grid, sensitivity=0.5, **quant):
    """Batería 6 a MIDI: cada golpe de cada pieza es una nota General MIDI (bombo 36, tarola 38...).
    La fuerza del golpe es la velocity. Devuelve [(inicio_s, fin_s, nota)] como to_midi."""
    import librosa
    import pretty_midi
    midi = pretty_midi.PrettyMIDI()
    kit = pretty_midi.Instrument(program=0, is_drum=True, name="Batería")
    floor = 10 ** ((-30 + 20 * (1 - sensitivity)) / 20)  # sensibilidad 0.5 = -20 dB; 1 = -30 dB; 0 = -10 dB
    for name, path in pieces.items():
        y, sr = librosa.load(path, sr=22050, mono=True)
        if not np.abs(y).max() or 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12) < -60:
            continue  # pieza vacía: el ruido de fondo no son golpes
        amp, win = np.abs(y), int(0.03 * sr)
        for i in librosa.onset.onset_detect(y=y, sr=sr, units="samples"):
            ratio = amp[i:i + win].max() / amp.max()  # pico del golpe frente al golpe más fuerte de la pieza
            if ratio < floor:  # sangrado de otras piezas y colas, no golpes
                continue
            t = i / sr
            vel = int(np.clip(127 + 3 * 20 * np.log10(ratio), 1, 127))  # -20 dB -> velocity 67
            kit.notes.append(pretty_midi.Note(velocity=vel, pitch=GM_DRUMS[name], start=t, end=t + 0.1))
    midi.instruments.append(kit)
    return _finish_midi(midi, out, grid, **quant)


# ---------------------------------------------------------------- partituras (MuseScore 4, idea de MuScriptor)

# Cómo importa MuseScore el MIDI (-M). Tresillos solo si las notas ya están en una rejilla: sin cuantizar, el
# vaivén del toque saldría como tresillos y ligaduras de 1/128.
MSCORE_IMPORT = """<?xml version="1.0" encoding="UTF-8"?>
<MidiOptions><QuantValue>2</QuantValue><HumanPerformance>true</HumanPerformance><Duplets>false</Duplets>
<Triplets>{}</Triplets><Quadruplets>false</Quadruplets><Quintuplets>false</Quintuplets><Septuplets>false</Septuplets>
<Nonuplets>false</Nonuplets><SimplifyDurations>true</SimplifyDurations><DottedNotes>true</DottedNotes></MidiOptions>
"""


def find_musescore():
    """MuseScore 4 o más nuevo, o None. Solo donde lo deja su instalador; agregar otras rutas si alguien
    lo tiene en otra parte. MuseScore 3 no sirve: no dice cómo está afinada la guitarra y no habría tablatura."""
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    found = [shutil.which("MuseScore4")] + sorted(glob.glob(os.path.join(pf, "MuseScore [4-9]*", "bin", "MuseScore*.exe")),
                                                  reverse=True)
    return next((f for f in found if f), None)


def _tab_staves(mscx):
    """Las partes con 4 a 9 cuerdas (guitarras, bajos) pasan a tablatura, en el mismo archivo. True si hubo alguna."""
    import xml.etree.ElementTree as ET
    tree = ET.parse(mscx)
    any_tab = False
    for part in tree.getroot().find("Score").findall("Part"):
        n, staff = len(part.findall("Instrument/StringData/string")), part.find("Staff")
        if not 4 <= n <= 9 or staff is None:
            continue
        st = staff.find("StaffType")
        st = ET.SubElement(staff, "StaffType") if st is None else st
        st.set("group", "tablature")
        name = st.find("name")
        (ET.SubElement(st, "name") if name is None else name).text = f"tab{n}StrCommon"
        for tag in ("lines", "lineDistance"):  # MuseScore no lee el preset por su nombre: hay que dar las líneas
            for e in st.findall(tag):
                st.remove(e)
        ET.SubElement(st, "lines").text = str(n)
        ET.SubElement(st, "lineDistance").text = "1.5"
        any_tab = True
    tree.write(mscx, encoding="UTF-8", xml_declaration=True)
    return any_tab


def sheets(mid):
    """Partitura de un .mid con MuseScore 4, junto a él: <nombre>.pdf, <nombre>.musicxml (para editarla en
    cualquier editor de partituras) y, si es guitarra o bajo, <nombre>-tab.pdf. Devuelve las rutas."""
    import subprocess
    import mido
    exe = find_musescore()
    if not exe:
        raise RuntimeError("Hace falta MuseScore 4 (gratis, musescore.org). Instálalo y vuelve a intentar.")
    base = os.path.splitext(mid)[0]
    song = mido.MidiFile(mid)
    quantized = any(m.type == "text" and m.text == "rdstems:cuantizado" for t in song.tracks for m in t)
    tmp = tempfile.mkdtemp(prefix="rds_score_")
    for t in song.tracks:  # las marcas rdstems: son para la app; MuseScore las imprimiría como texto
        carry, keep = 0, []
        for m in t:
            if m.type == "text" and m.text.startswith("rdstems:"):
                carry += m.time
            else:
                keep.append(m.copy(time=m.time + carry))
                carry = 0
        t[:] = keep
    mid = os.path.join(tmp, "clean.mid")
    song.save(mid)

    def make(out, *args):  # MuseScore sale con 0 aunque no escriba nada: se revisa el archivo
        p = subprocess.run([exe, *args], capture_output=True, text=True, errors="replace", timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not os.path.isfile(out):
            raise RuntimeError(f"MuseScore no escribió {os.path.basename(out)}: {(p.stderr or p.stdout).strip()[-300:]}")
        return out
    try:
        opts, score, tab = (os.path.join(tmp, n) for n in ("import.xml", "score.mscx", "tab.mscx"))
        with open(opts, "w", encoding="utf-8") as f:
            f.write(MSCORE_IMPORT.format("true" if quantized else "false"))
        make(score, "-M", opts, "-o", score, mid)
        out = [make(base + ext, "-o", base + ext, score) for ext in (".pdf", ".musicxml")]
        shutil.copyfile(score, tab)
        if _tab_staves(tab):
            out.append(make(base + "-tab.pdf", "-o", base + "-tab.pdf", tab))
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- proceso aparte

if __name__ == "__main__":
    # La app separa cada canción en este proceso para poder cancelarlo (taskkill /T /F).
    # argv[1] = JSON con los argumentos de process(); por stdout salen líneas JSON [tipo, texto].
    out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)  # lo que impriman las librerías va a stderr y no ensucia el protocolo
    sys.stdout = sys.stderr
    utf8_console()

    def say(kind, val):
        out.write(json.dumps([kind, val]) + "\n")
        out.flush()

    try:
        src, dst, stems, extras, *rest = json.loads(sys.argv[1])  # JSON no tiene sets: llegan como listas
        process(src, dst, set(stems), set(extras), *rest, log=lambda m: say("log", m), step=lambda m: say("step", m))
    except Exception:
        import traceback
        say("error", traceback.format_exc())
        sys.exit(1)
