# Referencia de TalkToMe

Referencia técnica: comandos, configuración, contrato con Claude Code, API de cada módulo y archivos de estado. La explicación del diseño, con diagramas, está en [ARQUITECTURA.md](ARQUITECTURA.md).

## Comandos

### Para el usuario

| Comando | Qué hace |
|---|---|
| `talktome.py say [texto]` | Dice el texto (sin texto, una frase de prueba). Toma la palabra de inmediato. |
| `talktome.py repite` · `repeat` | Repite la última respuesta dicha, de cualquier proyecto. |
| `talktome.py detalle` · `detail` | Narra el detalle de la última respuesta. |
| `talktome.py design [--acento A] [--description D] [--name N] [--no-play]` | Voice Design: genera voces candidatas, elige una, la guarda y la activa. |
| `talktome.py voices` | Lista las voces de su cuenta de ElevenLabs. |
| `talktome.py quota` | Caracteres usados y disponibles. |
| `talktome.py frases [--inventa]` · `lines` | Banco de frases e inventadas; `--inventa` pide nuevas ya. |
| `talktome.py escucha [--tecla T]` · `listen` | Dictado (solo Windows): mantenga la tecla, hable y suéltela; el texto se escribe en la ventana activa y se envía. Ctrl+C para salir. Una sola escucha a la vez. Normalmente no hace falta: arranca sola con Claude Code. |
| `talktome.py escucha --detener` | Termina la escucha en segundo plano. |
| `talktome.py despierta [--instalar] [--prueba]` · `wake` | Activación por voz: estado; instala Vosk y el modelo de español; muestra en vivo lo que entiende. |
| `talktome.py oye [archivo]` · `hear` | Transcribe sin enviar nada: un archivo de audio o, en Windows, el micrófono hasta Enter. |
| `talktome.py avisos [--preparar] [--prueba TIPO]` · `alerts` | Lista los avisos de error y si están en caché; genera los que falten; dice uno. |
| `talktome.py stop` | Calla lo que se esté diciendo. |
| `talktome.py mute` / `unmute` | Silencia o reactiva a Rachel (bandera `~/.talktome/muted`). |
| `talktome.py doctor` | Diagnóstico: config, clave, reproductor, silencio, micrófono y escucha, cuota. Sale con 1 si algo falta. |
| `install.py [--no-style] [--uninstall]` | Instala o quita los hooks y el estilo Rachel. |

### Internos

| Comando | Lo lanza | Qué hace |
|---|---|---|
| `hook <session\|prompt\|notification\|stop\|end>` | Claude Code | Lee el JSON de stdin y llama a `hooks.handle`; imprime la decisión si la hay. |
| `escucha --fondo` | hook `session` (o `prompt` tras una pausa) | La escucha sin consola; se va cuando Claude Code se cierra. |
| `_speak <reply\|say> <payload.json>` | `hooks._enqueue` | Worker: `hooks.work`. Borra el payload al leerlo. |
| `_repeat [sesión] [cwd]` | hook `prompt` | Repite la última respuesta de esa sesión. |
| `_detail [sesión] [cwd]` | hook `prompt` | Narra el detalle de la última respuesta de esa sesión. |
| `_prepara` | hook `session` | Genera en caché los avisos de error y las frases cortas que falten (`alerts.warm` + `persona.stock_lines`). |
| `_acompana <sesión> <transcript>` | hook `prompt` (turno por voz) | Interjecciones y progreso hasta que llegue la respuesta (`companion.accompany`). |

## Contrato con Claude Code

Cada hook recibe un JSON por stdin. TalkToMe usa estos campos:

| Campo | Eventos | Uso |
|---|---|---|
| `session_id` | todos | Separa la memoria y la interrupción por terminal. |
| `cwd` | todos | Identifica el proyecto (`projects.identify`). |
| `source` | `SessionStart` | Solo saluda con `startup` (no con `resume` ni `clear`). |
| `prompt` / `prompt_text` | `UserPromptSubmit` | Detecta "repite", "detalle" y "calla". |
| `notification_type`, `message` | `Notification` | Tipo de aviso y herramienta que pide permiso. |
| `last_assistant_message` | `Stop` | Respuesta final (versiones nuevas de Claude Code). |
| `transcript_path` | `Stop` | Respaldo: se lee el JSONL si no llegó la respuesta. |

Salida: solo el hook `prompt` puede responder, con `{"decision": "block", "reason": "…"}` para "repite", "detalle" y "calla". Los demás no imprimen nada. Todos salen con código 0, incluso si fallan.

Tipos de notificación que Rachel dice (`persona.ATTENTION`): `permission_prompt`, `idle_prompt`, `elicitation_dialog`, `agent_needs_input`. Los demás (por ejemplo `auth_success`) se ignoran.

## Configuración

Orden de precedencia, de menor a mayor: `config.DEFAULTS` → `talktome.config.json` (o el antiguo `jarvis.config.json`) → variables de entorno. `voice_settings` se combina clave por clave.

| Clave | Por defecto | Descripción |
|---|---|---|
| `enabled` | `true` | Apaga todo salvo la intercepción de "repite"/"detalle". |
| `honorific` | `"señor"` | Cómo llama Rachel al usuario. |
| `voice_id` | Lily | Voz de ElevenLabs; `design` la reemplaza. |
| `model_id` | `eleven_multilingual_v2` | También `eleven_flash_v2_5`, `eleven_v3`. |
| `language_code` | `"es"` | Solo se envía a los modelos que lo aceptan. |
| `voice_settings` | stability 0.4 · similarity_boost 0.8 · style 0.35 · use_speaker_boost · speed 0.97 | Ajustes de la voz. |
| `mode` | `"auto"` | `auto`, `lead` (solo el resumen) o `full`. |
| `max_chars` | 450 | En `auto`, respuestas hasta este largo se dicen completas. |
| `summary_max_chars` | 650 | Tope del resumen hablado. |
| `detail_max_chars` | 2500 | Tope de "detalle". |
| `summarizer` | `"claude"` | `"off"` apaga la red de seguridad y las frases inventadas. |
| `summarizer_command` | `["claude", "-p", "--model", "sonnet"]` | Comando del resumidor (opcional). |
| `summarizer_timeout` | 60 | Segundos máximos del resumidor (opcional). |
| `invent_chance` | 0.2 | Probabilidad de inventar frases tras un recordatorio. |
| `invented_max` | 60 | Frases inventadas que se conservan. |
| `announce_project` | `"switch"` | Distintivo de proyecto: `switch`, `always` u `off`. |
| `projects` | `{}` | Carpeta → nombre hablado, o `{"name", "voice_id", "voice_settings", "honorific", …}`. |
| `greet_on_start` | `true` | Saludo al abrir sesión. |
| `speak_notifications` | `true` | Decir permisos y recordatorios. |
| `interrupt_on_prompt` | `true` | Escribir calla a Rachel en esa terminal. |
| `listen_key` | `"F9"` | Tecla de `escucha`: F1–F24, `Pause`, `ScrollLock`, `RightCtrl`, `RightAlt` o un código `0x..`. |
| `report_errors` | `true` | Decir en voz alta qué falló (una vez cada 10 min por tipo). |
| `wake` | `"auto"` | Escuchar su nombre: `auto` (si Vosk y el modelo están), `true` (y avisa si falta) o `false`. |
| `wake_words` | `[]` | Formas extra de escribir su nombre, sumadas a `wake.WAKE_WORDS`. |
| `wake_model` | `""` | Carpeta del modelo Vosk (por defecto `~/.talktome/models/vosk-model-small-es-0.42`). |
| `wake_timeout` | 6 | Segundos para empezar a hablar tras "¿Sí, señor?". |
| `wake_silence` | 1.2 | Segundos de silencio que terminan la orden. |
| `wake_flavor` | 0.3 | Probabilidad de una respuesta con guiño a las películas. |
| `listen_on_start` | `true` | Arrancar la escucha en segundo plano con cada sesión (Windows). |
| `listen_idle_minutes` | 120 | Sin ninguna actividad de Claude Code durante este tiempo, la escucha se va. |
| `listen_min_seconds` | 0.4 | Pulsaciones más cortas se ignoran. |
| `listen_max_seconds` | 120 | Al llegar aquí se envía aunque siga presionada. |
| `stt_model` | `"scribe_v2"` | Modelo de Speech-to-Text de ElevenLabs. |
| `stt_keyterms` | `[]` | Palabras que Scribe debe esperar (proyectos, jerga, nombres). En tiempo real se usan hasta 50, de 20 caracteres como máximo. |
| `stt_realtime` | `true` | Transcribir mientras se habla (Scribe v2 Realtime); si falla, Scribe por lotes. |
| `stt_realtime_model` | `"scribe_v2_realtime"` | Modelo en tiempo real. |
| `stt_realtime_timeout` | 5 | Segundos de espera del texto tras soltar la tecla antes de pasar a lotes. |
| `voice_ack` | `true` | Acuse inmediato al enviar un dictado. |
| `narrate_progress` | `"voice"` | Interjecciones y progreso: `voice` (turnos dictados), `always` u `off`. |
| `cache_max_chars` | 160 | Frases hasta este largo se guardan en caché. |
| `player` | `"auto"` | `mpv`, `ffplay` o `auto`. |

Variables de entorno:

| Variable | Efecto |
|---|---|
| `ELEVENLABS_API_KEY` | Clave (gana sobre `.env`). |
| `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID` | Reemplazan la voz o el modelo de la config. |
| `ELEVENLABS_API_BASE` | Otra URL de la API (pruebas, proxy). |
| `ELEVENLABS_WS_BASE` | Otra URL para Scribe en tiempo real (por defecto `wss://api.elevenlabs.io`). |
| `TALKTOME_DISABLE` | Si existe, los hooks no hacen nada (lo usa el resumidor). |
| `TALKTOME_STATE` | Carpeta de estado en lugar de `~/.talktome`. |
| `TALKTOME_CONFIG` | Ruta del archivo de configuración. |
| `CLAUDE_CONFIG_DIR` | Carpeta de Claude Code para `install.py` (por defecto `~/.claude`). |

`.env` se lee aunque venga con BOM o en UTF-16 (Bloc de notas, `>` de PowerShell).

## API de los módulos

### `hooks.py`

| Función | Descripción |
|---|---|
| `handle(event, payload, cfg)` | Entrada de cada hook. Nunca bloquea en audio. Devuelve la decisión (o `None`). |
| `work(kind, payload_file, cfg)` | Worker: arma la frase y la dice, esperando su turno. |
| `detail(cfg, session=None)` | Narra el detalle de la última respuesta de la sesión. |
| `compose_reply(markdown, cfg, summarize=None)` | Qué decir de una respuesta (ver las tres capas en ARQUITECTURA). |
| `is_repeat(prompt)` / `is_detail(prompt)` / `is_stop(prompt)` | ¿El mensaje completo es "repite"/"detalle"/"calla"? |
| `remember_window(session)` / `session_windows()` | La ventana al frente al abrir sesión o enviar un prompt; las de las sesiones abiertas, la más reciente primero. |
| `track(event, session)` / `claude_open(idle, grace)` / `start_listening()` | Sesiones abiertas y actividad; ¿sigue Claude Code en uso?; lanza la escucha si no corre. |
| `mark_dictated(text)` / `was_dictated(prompt)` | La escucha anota lo que dictó; el hook `prompt` reconoce el turno por voz (una vez, hasta 30 s). |
| `narrates(cfg, voice)` | ¿Acompañar este turno? Según `narrate_progress`, silencio y clave. |
| `announces(cfg)` | ¿Está activo el distintivo de proyecto? |
| `log(message)` | Una línea en `talktome.log`; rota a los 500 KB. |

### `player.py`

| Función | Descripción |
|---|---|
| `cached(text, cfg)` / `prefetch(text, cfg)` | ¿Está `text` en caché con esta voz? / Sintetizarlo a la caché sin reproducirlo (avisos de error). |
| `speak(text, cfg, keep=False, session=None, intro=None, wait=300)` | Espera el turno (hasta `wait` s), dice `intro(proyecto_anterior)` si devuelve texto y luego `text`. `False` si no consiguió el turno. |
| `replay(cfg, session=None)` | Repite la última respuesta de la sesión (audio guardado si está completo). |
| `claim(session=None)` | Registra el proceso como worker de la sesión y corta al anterior de esa sesión. Sin sesión: toma la palabra ya. |
| `release(session=None)` | Suelta la palabra y el registro de la sesión si son propios. |
| `stop(session=None)` | Con sesión, mata a su worker; sin sesión, a quien habla. |
| `busy()` / `wait_turn(timeout)` | ¿Habla otro proceso? / esperar a que termine. |
| `session_dir(session=None)` | Carpeta de la sesión; sin sesión, la de la última respuesta. |
| `remember_project`, `keep_markdown`, `last_markdown`, `last_spoken` | Memoria de la sesión. |
| `spawn(*args)` | Lanza `talktome.py <args>` desacoplado de Claude Code. |
| `play_mp3(data, cfg)` / `describe(cfg)` | Reproducir mp3 en memoria / describir el reproductor elegido. |

### `speakable.py`

| Función | Descripción |
|---|---|
| `to_speech(markdown, code_phrase=…, keep_tags=False)` | Markdown → párrafos hablables. |
| `spoken_summary(markdown)` | Primer párrafo si es un resumen de prosa pura; si no, `""`. |
| `needs_input(markdown)` / `asks(text)` | ¿La respuesta termina pidiendo algo? / ¿el texto pide algo? |
| `truncate(text, max_chars)` | Corta en el último fin de frase; devuelve `(texto, cortado)`. |

### `persona.py`

| Función | Descripción |
|---|---|
| `greeting(h, now=None, project="")` | Saludo según la hora, con el proyecto y la efeméride si toca. |
| `notification(payload, h, now=None)` | Frase para un aviso, o `""` si no requiere al usuario. |
| `idle(h, now=None)` | Recordatorio de espera con escalada. |
| `callsign(project, h, now=None)` | Distintivo de proyecto. |
| `invent(cfg)` / `clean_invented(...)` | Pide frases a Claude y filtra las utilizables. |
| `one_moment`, `nothing_to_detail`, `needs_answer`, `done`, `more_on_screen` | Frases fijas. |

### Otros

| Módulo | API |
|---|---|
| `projects.py` | `identify(cwd, cfg) → (nombre, cfg)`, `root(cwd)`, `speakable_name(nombre)`. |
| `persona.py` (dictado) | `ack(h)`, `thinking(h, tone, expressive)`, `activity(tool, input)` → read/edit/test/git/shell/web/agent/plan/other o `None`, `progress(kind, h)`. |
| `deck.py` | `draw(nombre, opciones, fits)`, `waits(now)`, `first_time_today(clave, hoy)`, `invented()`, `add_invented(frases, keep)`. |
| `summarizer.py` | `summarize(reply, cfg)`, `narrate(reply, spoken, cfg)`, `invent_lines(known, cfg, count)`; `""` si falla. |
| `transcript.py` | `final_reply(path)`: texto final del último turno del asistente; `tool_calls(path, offset)` → herramientas nuevas y offset; `size(path)`. |
| `tts.py` | `stream`, `wav`, `cache_path`, `design`, `save_voice`, `voices`, `subscription`; errores como `TTSError`. |
| `stt.py` | `transcribe(audio, cfg, filename)` (Scribe, multipart), `clean(text)` (una línea sin etiquetas de sonido; `""` si no hay palabras), `multipart(fields, files)`. |
| `listen.py` | `Listener(cfg, desk, transcribe, stream, hush, acknowledge, …).dictate()`: un dictado completo; `run()` los encadena; `serve(cfg, key)` es `escucha`; `running()` → pid de la escucha activa. |
| `realtime.py` | `Stream(cfg)`: `feed(pcm)`, `finish(timeout)` → texto, `cancel()`; `url(cfg)`; `WebSocket` mínimo; `encode_frame` / `read_frame`. |
| `mic.py` | Solo Windows, con `ctypes`: `Desk(key)` (tecla por gancho de teclado de bajo nivel, o hotkey si no se puede; ventana activa, `type_text`, `copy`, `beep`), `KeyWatcher`, `Recorder` (waveIn, 16 kHz mono en trozos de 100 ms, `start(on_chunk)`, `stop(path)` → WAV), `vk_code`, `key_events`. |
| `persona.py` (voz) | `wake(h, flavor)`, `wake_timeout(h)`, `wake_cancel(h)`, `stock_lines(h, expressive)`: frases cortas a pre-generar. |
| `alerts.py` | `classify(error)` → auth/quota/no_key/network/mic/elevated/player/crash; `report(kind, cfg, detail)` (nunca lanza); `line(kind, cfg)`; `missing(cfg)` / `warm(cfg)`: avisos en caché; `system_say(text)`: voz del sistema. |
| `wake.py` | `find_wake(words)`, `strip_wake(text)`, `is_cancel(text)`, `normalize`, `level(pcm)`; `Gate` (compuerta por energía con piso adaptativo); `Wake(cfg, spotter, say, deliver, transcribe, …).handle(pcm)`: dormida → llamada → escuchando la orden; `VoskSpotter`; `Hub` / `Tap`: un micrófono abierto compartido con F9; `engine(cfg)`, `enabled(cfg)`, `install(cfg)`. |
| `listen.py` (voz) | `start_wake(cfg, desk)`, `deliverer(cfg, desk)` → `deliver(text)`, `choose_window(desk)`. |
| `companion.py` | `accompany(cfg, session, transcript)`; `Companion.run()`: lee el transcript y habla con pausas crecientes (`gap(n)`), tono de interjección según la espera (`tone(n)`); `turn_done(session)`. |
| `config.py` | `load()`, `save_voice_id(id)`, `set_muted(bool)`, `STATE_DIR`, `ROOT`, `DEFAULTS`. |

## Archivos de estado (`~/.talktome`)

| Archivo | Quién lo escribe | Contenido |
|---|---|---|
| `speaking.pid` | `player` | PID de quien tiene la palabra (creación atómica). |
| `last-voice` | `player` | Proyecto que habló último, para el distintivo. |
| `last-session` | `player` | Sesión de la última respuesta, para `repite` desde consola. |
| `muted` | `config.set_muted` | Existe = silencio. |
| `lines.json` | `deck` | `decks`, `last`, `waits`, `said_on`, `invented`. |
| `talktome.log` / `.log.old` | `hooks.log`, `cli`, `summarizer` | Decisiones y errores. |
| `cache/<sha1>.mp3\|wav` | `player` | Frases cortas ya sintetizadas. |
| `payload-<tipo>-<ns>.json` | `hooks._enqueue` | Paso del hook al worker; se borra al leerlo. |
| `last.wav` | `player` | Audio temporal de los reproductores sin streaming. |
| `design/voz-N.mp3` | `cli design` | Candidatas de Voice Design. |
| `listen.pid` | `listen.serve` | Escucha activa (evita dos que escriban todo dos veces). |
| `dictado.wav` | `listen` / `cli oye` | Último dictado, para revisarlo con `oye dictado.wav`. |
| `dictated.json` | `hooks.mark_dictated` | Texto y hora del último dictado; el hook `prompt` lo consume. |
| `sessions/<id>/prompt-at` | hook `prompt` | Hora del último prompt, para medir el turno de Claude. |
| `sessions/<id>/window` | hooks `session` / `prompt` | Ventana de la terminal de esa sesión (Windows). |
| `speaking.txt` | `player` | Lo que está diciendo ahora: su propia voz no la despierta. |
| `models/vosk-model-small-es-0.42/` | `despierta --instalar` | Modelo del reconocedor local. |
| `sessions/<id>/turn-done` | hook `stop` | El turno terminó: el acompañante se calla. |
| `open-sessions/<id>` | hooks `session` / `end` | Sesiones de Claude Code abiertas. |
| `claude-activity` | todos los hooks | Última actividad de Claude Code. |
| `alerts.json` | `alerts.due` | Última vez que se dijo cada tipo de aviso. |
| `listen-dozed` | `listen.serve` | La escucha se fue por inactividad; el próximo prompt la despierta. |
| `sessions/<id>/project` | `player.remember_project` | Nombre hablado del proyecto. |
| `sessions/<id>/worker.pid` | `player.claim` | Worker activo de esa sesión. |
| `sessions/<id>/last-reply.txt` | `player` | Texto de la última respuesta dicha. |
| `sessions/<id>/last-reply.md` | `player.keep_markdown` | Respuesta en pantalla, para "detalle". |
| `sessions/<id>/last-reply.mp3\|wav` + `.audio.txt` | `player` | Audio completo y el texto al que corresponde. |

Borrar `~/.talktome` es seguro: se pierde la caché, la memoria de los mazos y las frases inventadas, nada más.
