# RD Stems

Separador de stems para Windows, con análisis de tempo, tonalidad y acordes, conversión de audio a MIDI y partituras. Separa con los modelos abiertos más limpios que hay hoy, de la familia RoFormer (los mismos que usan UVR y MVSEP), y corre en tu computadora: no sube nada a ningún servidor.

## Descargar y usar

1. En [Releases](../../releases/latest) baja `RD-Stems-windows.zip`.
2. Clic derecho en el zip, "Extraer todo", y abre `RD Stems.exe` desde la carpeta extraída.
3. La primera vez se abre una ventana negra que instala lo que hace falta dentro de esa misma carpeta: su propio Python, PyTorch y las librerías. Tarda unos 10 minutos según tu internet. Cuando termina, presiona una tecla y se abre RD Stems.

Las siguientes veces `RD Stems.exe` abre la app directo. La carpeta puede ir donde quieras, pero el .exe tiene que quedarse dentro de ella; un acceso directo en el escritorio sí funciona. También puedes soltar canciones o una carpeta sobre el .exe o sobre la ventana.

Con Windows al 125% o 150% la ventana se dibuja a tamaño real, así que se ve un poco más chica.

Windows puede avisar que el programa no es de un editor conocido, porque el .exe no está firmado. Para abrirlo: "Más información" y luego "Ejecutar de todas formas".

### Qué necesitas

- Windows 10 u 11 de 64 bits.
- Unos 12 GB libres: 6 GB de la instalación y hasta 5 GB de modelos, que se bajan la primera vez que usas cada uno.
- Una tarjeta NVIDIA es lo ideal. Sin ella también funciona, solo que mucho más lento.
- Para las partituras, [MuseScore 4](https://musescore.org/es/download) (gratis). Todo lo demás funciona sin él.

No hace falta tener Python. La instalación no se registra en Windows ni toca otro Python que ya tengas: todo queda en la carpeta, y para desinstalar basta con borrarla.

Si algo falla, `run.bat` abre la app con una consola donde se ven los errores. Sin consola, los errores quedan en `error.log`.

## Se adapta al equipo

PyTorch se elige solo según la tarjeta: con NVIDIA se baja la versión CUDA que acepta su driver, y sin NVIDIA, la de procesador. Arriba a la derecha aparece lo que detectó (tarjeta, memoria de video y FP16, o procesador, núcleos y RAM).

- Las NVIDIA desde la serie 20 usan media precisión: van más rápido y con la mitad de memoria.
- Con menos de 8 GB de video o sin GPU, el modelo de 53 instrumentos trabaja en trozos de 3 s para caber.
- La RAM decide si una canción larga pasa completa por ese modelo o por partes.
- Sin GPU la app arranca en calidad RÁPIDA.

Los modelos se bajan a la carpeta `models` la primera vez que se usan, con el avance en la barra de estado. Si la descarga se corta, la próxima vez sigue donde quedó.

## Qué separa

| Casilla | Modelo |
|---|---|
| VOZ | MÁX: BS-RoFormer Resurrection + MelBand Big Beta 6X (ensamble). RÁPIDA: la voz del SW si ese modelo ya corre, si no Resurrection |
| BATERÍA, BAJO, GUITARRA, TECLADO | BS-RoFormer SW (un solo pase para los cuatro) |
| BATERÍA 6 | MDX23C DrumSep sobre la batería del SW: bombo, tarola, toms, hihat, ride, crash |
| SINTETIZADOR, VIENTO, CUERDAS | MVSep Mega 53 stems (ZFTurbo), el único modelo público que los separa. Más lento y menos limpio |

Siempre sale también `resto.wav`, la mezcla menos todo lo elegido, para que los stems sumen la canción completa.

La fila VOZ tiene tres extras: COROS separa la voz principal de los coros, SIN REVERB quita la reverberación y SIN RUIDO quita el ruido de fondo. Cada uno es un archivo aparte y la voz original se conserva.

La calidad MÁX calcula cada trozo 4 veces y promedia (overlap 4) y usa el ensamble de voz; RÁPIDA usa overlap 2.

## Varias canciones

En la pestaña STEMS, ABRIR suma archivos y CARPETA suma todos los audios de una carpeta, sin subcarpetas. Las canciones aparecen a la izquierda en MOSAICO o LISTA, y debajo, los stems de la elegida para escuchar.

YOUTUBE acepta un link de YouTube, un link de una canción de Spotify o una búsqueda (muestra los 10 primeros resultados). Con un link de Spotify lee el título, el artista y la duración de la página pública y baja de YouTube la versión de duración más parecida; el audio sale de YouTube, porque el de Spotify está cifrado. Solo acepta canciones sueltas, no playlists ni álbumes. El audio queda en `Música\RD Stems\<título>.flac`. Usa [yt-dlp](https://github.com/yt-dlp/yt-dlp), y como YouTube cambia seguido, si deja de bajar hay que correr `install.bat` otra vez para actualizarlo. Bajar audio de YouTube va contra sus términos: úsalo solo para uso personal.

Cada canción guarda sus propias casillas de SEPARAR y VOZ; CALIDAD y ANALIZAR valen para todas. Cada tarjeta tiene tres teclas:

- ⑂ separa esa canción.
- ↓ (cuando ya está separada) abre la lista de sus stems para elegir cuáles guardar. Los casi vacíos aparecen como VACÍO y sin marcar. Puedes guardar en WAV o FLAC (el mismo audio de 24 bits, sin pérdida, en más o menos la mitad de espacio), y SIEMPRE EN guarda siempre en la última carpeta sin volver a preguntar.
- ✕ la quita de la lista, sin borrar archivos.

Con SELECCIONAR marcas varias y las teclas valen para todas; se separan una tras otra. Los stems quedan en `<canción> - stems`, junto a la canción. Si vuelves a separar una canción, lo que ya está en esa carpeta con la misma calidad o mejor no se separa otra vez: marcar BATERÍA 6 después, por ejemplo, solo corre DrumSep sobre la `bateria.wav` que ya existe. Si cambias el archivo por otro con el mismo nombre, se separa todo de nuevo.

CANCELAR, junto a la barra de progreso, detiene la separación al instante, aunque esté a mitad de un modelo. Cerrar la ventana también la cancela. Si una canción falla, el error queda en `error.log` y se sigue con la siguiente.

## Escuchar

La casilla de cada stem lo suma a lo que suena (▶ o barra espaciadora). Por defecto están marcados los stems y el resto, que juntos son la canción; si desmarcas la voz queda el karaoke. Los stems se pueden arrastrar de la lista a Ableton o a cualquier DAW.

TODO, KARAOKE, VOZ y RITMO marcan de un clic la canción completa, todo menos la voz, solo la voz, o batería y bajo. VOL (de −30 dB, que lo apaga, a +6 dB), PAN y SOLO cambian el stem elegido en la lista, y con algún SOLO activo suenan solo esos. Las teclas 1 a 9 marcan o desmarcan cada stem de arriba abajo.

El volumen y el paneo se guardan en `mezcla.json`, en la carpeta de la canción, y vuelven al abrirla. Solo cambian lo que escuchas, no los archivos.

## Análisis

- Tempo, compás y dónde cae cada tiempo, con [beat-this](https://github.com/CPJKU/beat_this) (su modelo de 81 MB se baja la primera vez). Si la canción no tiene un tempo fijo aparece como VARIABLE.
- Tonalidad y acordes mayores y menores, cada dos tiempos desde el tiempo fuerte.
- Por stem: pico y RMS en dBFS, el rango donde está el 90% de su energía, el brillo (centroide espectral) y las 5 frecuencias dominantes con su nota.
- El espectrograma en escala logarítmica.

Todo queda en `analisis.json` y en la carpeta `espectrogramas/`. En el espectrograma, un clic o un arrastre mueve la reproducción, y con − y + se aleja o se acerca.

## Audio a MIDI

La pestaña MIDI convierte con [Basic Pitch](https://github.com/spotify/basic-pitch) de Spotify. A la izquierda están los stems de cada canción separada, la mezcla y lo que abras desde esta pestaña. ♪ convierte y ↓ guarda el `.mid` donde elijas. El `.mid` queda junto a su audio y lleva el instrumento de su stem (bajo eléctrico, guitarra, cuerdas, voz; lo demás, piano), así suena bien en el DAW.

- TIPO limita las notas a un rango: TODO (acordes), MELODÍA (80 a 1400 Hz), BAJO (30 a 400 Hz) o CUSTOM, donde los bordes se arrastran sobre el espectrograma. Se elige solo según el stem.
- SENSIBILIDAD más alta detecta notas más suaves, y también más ruido. NOTA MÍNIMA descarta las más cortas. PITCH BEND apagado deja notas fijas.
- TEMPO y COMPÁS vienen del análisis. El `.mid` sigue el pulso de la canción: si el tempo cambia lleva un mapa de tempo, y las barras caen en los tiempos fuertes. Si el detector se equivocó, ÷2 y ×2 corrigen cuando contó la mitad o el doble, COMPÁS cambia los tiempos por compás y AQUÍ pone una barra donde está la reproducción.
- CUANTIZAR ajusta las notas a la rejilla del pulso: AUTO elige la rejilla en que caen (también tresillos), o puedes fijar 1/8, 1/8T, 1/16, 1/16T o 1/32. FUERZA las acerca solo una parte, para conservar algo del toque. Antes de cuantizar se corrige el retraso fijo de los ataques, si lo hay.
- SILENCIOS alarga cada nota hasta la siguiente si el silencio es corto, para que el editor de partituras no se llene de silencios de 1/16. SIN INTRO VACÍA quita los compases vacíos del principio.

En una pieza de BATERÍA 6 convierte el kit completo a un MIDI de batería General MIDI (bombo 36, tarola 38, toms 45, hihat 42, ride 51, crash 49), con la fuerza de cada golpe como velocity.

PARTITURA escribe junto al `.mid` un PDF con la partitura, un `.musicxml` para seguir editándola en MuseScore, Sibelius o Guitar Pro y, si es guitarra o bajo, un PDF con la tablatura. Sale mucho mejor con CUANTIZAR y SILENCIOS.

## Lo que guarda

```
<canción> - stems/
  voz.wav  bateria.wav  bajo.wav  ...  resto.wav  voz_principal.wav  coros.wav  voz_seca.wav  voz_limpia.wav
  bateria_6/   bombo.wav  tarola.wav  ...  bateria.mid
  espectrogramas/  analisis.json  separacion.json  mezcla.json
```

## Límites

- Guitarra y teclado salen menos limpios que voz, bajo y batería, y sintetizador, viento y cuerdas todavía menos. Hoy ningún modelo abierto lo hace mejor.
- El modelo de 53 instrumentos pide mucha memoria y en equipos sin GPU es lento.
- Toms, ride y crash se cuelan unos en otros en mezclas densas.
- La tonalidad y los acordes son estimaciones; en música modal o atonal pueden fallar.

## Para modificarlo

```
git clone https://github.com/dacdemarco/rd-stems
cd rd-stems
install.bat
```

`install.bat` arma el entorno en `.venv` y construye `RD Stems.exe` a partir de `launcher.py`. La app es `app.py` (interfaz en PySide6) y `engine.py` (separación, análisis y MIDI, sin interfaz). Para probar los cambios:

```
.venv\Scripts\python test_engine.py
.venv\Scripts\python test_app.py
```

La primera prueba revisa el análisis, el MIDI y la lógica de separación sin necesitar los modelos; la segunda, la interfaz sin abrir la ventana.

## Licencias

El código es MIT (ver `LICENSE`). Los modelos no vienen en este repositorio: se bajan de sus autores y tienen sus propias licencias. El modelo SW y el de 53 instrumentos no declaran una licencia clara, así que antes de usar RD Stems para algo comercial conviene revisarlo. Departure Mono es SIL OFL 1.1 (`assets/fonts/DepartureMono-OFL.txt`). Las ideas de tempo, rejilla y partituras vienen de [MuScriptor](https://github.com/muscriptor/muscriptor), y la reutilización de stems y la cancelación, de [StemKit](https://github.com/danielravina/stemkit).
