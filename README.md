# TalkToMe — Claude Code con la voz de Rachel

Proyecto RocketYeah: que Claude Code **hable** con la naturalidad de las conversaciones de Tony Stark con J.A.R.V.I.S. Su voz es **Rachel**, como la replicante de Blade Runner: latinoamericana, veinteañera, aterciopelada, enigmática, de cine negro, con el humor negro de un mayordomo británico. Cada vez que Claude termina una respuesta, TalkToMe la convierte en habla natural con ElevenLabs y la dice en voz alta. Te saluda al abrir sesión, te avisa cuando necesita permiso y se calla en cuanto le hablas.

```
 Tú escribes ──► Claude Code ──► respuesta en pantalla
                     │
                     │ hook Stop (≈100 ms, no bloquea)
                     ▼
              talktome.py hook stop
                     │  proceso en segundo plano
                     ▼
   1. extrae la respuesta final (sin la narración intermedia)
   2. la vuelve "hablable": fuera markdown, código, rutas, URLs, emojis
   3. elige qué decir: completa si es corta, su resumen hablado si es larga
   4. ElevenLabs (streaming) ──► mpv: empieza a sonar antes de terminar de generarse
```

| Evento de Claude Code | Qué hace Rachel |
|---|---|
| `SessionStart` | "Buenas noches, señor. ¿Viene a hacerme otra prueba Voight-Kampff?" |
| `Stop` | Lee la respuesta (o su resumen hablado) |
| `Notification` | "Señor, necesito su permiso para usar Bash. Prometo no incendiar nada." |
| `UserPromptSubmit` | Se calla al instante: usted tiene la palabra |
| Escribes **"repite"** | Repite su última respuesta, sin gastar créditos ni turno de Claude |

## El truco para que suene humano

Leer respuestas técnicas palabra por palabra suena a robot, por buena que sea la voz. Por eso hay tres capas:

1. **Estilo de salida "Rachel"** (`claude/output-styles/rachel.md`): Claude abre cada respuesta con un *resumen hablado* de toda la respuesta (conclusión, cada elemento relevante, datos clave, riesgos y siguiente paso), escrito para el oído: sin símbolos, con ritmo y con humor negro británico. Su largo se adapta: una frase si la respuesta es trivial, hasta cinco si es grande. El detalle técnico va debajo, solo en pantalla.
2. **Red de seguridad**: si una respuesta no trae resumen hablado (por ejemplo, porque el `CLAUDE.md` de un proyecto impone su propio formato), TalkToMe se lo pide en segundo plano a Claude Code (`claude -p` con Sonnet y esfuerzo bajo, usando tu plan, sin herramientas y sin guardar la sesión). Tarda unos segundos más y sigue las mismas reglas: si te piden algo, eso va primero. Si esa llamada falla, al menos te avisa: "Señor, necesito que me responda algo. Está en pantalla."
3. **Voz de ElevenLabs** bien afinada: modelo multilingüe, estabilidad media (más expresiva que monótona), streaming y frases cortas en caché.

## Puesta en marcha (≈10 minutos)

Requisitos: Python 3.9+ (sin dependencias externas) y un reproductor con streaming.

```powershell
# 1. Reproductor de baja latencia (Windows; en macOS: brew install mpv)
winget install mpv            # o: winget install ffmpeg

# 2. Clave de ElevenLabs
cd E:\AI\Claude\TalkToMe
copy .env.example .env        # y pon tu ELEVENLABS_API_KEY

# 3. Verificar, crear la voz de ella y escucharla
python talktome.py doctor
python talktome.py design     # genera voces candidatas, eliges una y queda activada
python talktome.py say

# 4. Conectar a Claude Code (todos tus proyectos)
python install.py
```

Abre una sesión nueva de Claude Code y deberías oír el saludo. `install.py` hace copia de seguridad de `~/.claude/settings.json` y es idempotente; `python install.py --uninstall` lo deja todo como estaba. Con `--no-style` instalas solo la voz, sin cambiar el estilo de Claude (en ese caso se lee el primer párrafo de cada respuesta, sea cual sea).

Sin mpv/ffmpeg también funciona (Windows usa `winsound`), pero espera a tener el audio completo antes de hablar.

## Comandos

| Comando | Para qué |
|---|---|
| `python talktome.py repite` | Repite la última respuesta desde la terminal |
| `python talktome.py say "texto"` | Decir algo (sin texto: frase de prueba) |
| `python talktome.py design` | Crear su voz con Voice Design (ver abajo) |
| `python talktome.py voices` | Listar tus voces con su ID |
| `python talktome.py quota` | Caracteres disponibles en tu plan |
| `python talktome.py stop` | Callar la frase en curso |
| `python talktome.py mute` / `unmute` | Silenciar / reactivar a Rachel |
| `python talktome.py doctor` | Diagnóstico completo |

Para que no hable en ejecuciones automáticas (por ejemplo `claude -p` en scripts), define la variable de entorno `TALKTOME_DISABLE=1`. Para apagarlo del todo: `"enabled": false` en la config.

## Que te repita algo

Escribe **repite** en Claude Code y pulsa Enter. También sirven "repítelo", "otra vez", "¿qué dijiste?" o "no te escuché", con o sin "Rachel" y "por favor". Tiene que ser el mensaje completo: "repite la prueba con más datos" sigue yendo a Claude como siempre.

Ese mensaje nunca llega a Claude: un hook lo intercepta, así que no consume tu plan ni aparece en la conversación. Rachel reproduce el audio guardado de su última respuesta, sin gastar créditos de ElevenLabs; solo si la habías interrumpido a mitad de frase la vuelve a generar completa.

## Configuración (`talktome.config.json`)

| Clave | Valor por defecto | Notas |
|---|---|---|
| `honorific` | `"señor"` | Cómo te llama Rachel |
| `voice_id` | Lily (`pFZP5JQG7iQjIQuC4Bku`) | Provisional (británica, habla español con acento inglés). `design` la reemplaza |
| `model_id` | `eleven_multilingual_v2` | Ver tabla de modelos |
| `voice_settings` | stability 0.4 · similarity 0.8 · style 0.35 · speed 0.97 | Menos stability = más emoción |
| `mode` | `auto` | `auto`, `lead` (solo el resumen hablado) o `full` |
| `max_chars` | 450 | En `auto`, respuestas hasta este largo se leen completas |
| `summary_max_chars` | 650 | Tope del resumen hablado: protege tus créditos |
| `summarizer` | `"claude"` | Red de seguridad para respuestas sin resumen; `"off"` la apaga |
| `greet_on_start`, `speak_notifications`, `interrupt_on_prompt` | `true` | |
| `player` | `auto` | `mpv`, `ffplay` o `auto` |

| Modelo | Cuándo usarlo |
|---|---|
| `eleven_multilingual_v2` | El español más natural y estable. **Recomendado para empezar.** |
| `eleven_flash_v2_5` | Latencia ~75 ms y la mitad de créditos por carácter; algo menos de matiz. |
| `eleven_v3` | El más expresivo; entiende etiquetas como `[sighs]`, `[whispers]`, `[sarcastic]` (TalkToMe las conserva solo con este modelo). Más latencia. |

## La voz: más humana que un humano

Rachel: latinoamericana de veintitantos, voz grave y aterciopelada, un punto ronca, sensual, fría y enigmática como una heroína de cine negro pero cálida por dentro, con humor negro impasible. Habla español latino, nunca de España: la voz lo pide explícitamente y el estilo le prohíbe el vocabulario peninsular ("vale", "ordenador", "he revisado"...).

1. **Voice Design, el camino recomendado.** `python talktome.py design` le describe esa voz a ElevenLabs (la descripción está en inglés porque así la sigue con más fidelidad), genera varias candidatas diciendo una frase en personaje, te las reproduce y guarda la que elijas en tu biblioteca y en `talktome.config.json`. Con `r` generas otra tanda. Elige el acento con `--acento`: `latino` (neutro, por defecto), `mexicano`, `colombiano`, `venezolano`, `argentino` o `chileno`. Puedes pasar tu propia descripción con `--description "..."`. Cada tanda consume algunos créditos.
2. **Mientras tanto**, la voz por defecto es *Lily*, británica: al hablar español tiene acento inglés, así que es solo un comodín. Plan B a `design`: en la web de ElevenLabs, Voice Library, filtra por idioma español, acento latinoamericano y voz femenina, añade la que te guste y pega su ID en la config. Otras prediseñadas: `talktome.py voices`, y para probar una sin tocar la config: `ELEVENLABS_VOICE_ID=<id> python talktome.py say`.
3. **Afinado fino** en `voice_settings`: `stability` 0.3–0.4 da más vida y picardía; `style` hasta ~0.45 da más interpretación (más arriba sobreactúa); `speed` 0.95–0.97 da la cadencia pausada y seductora.
4. **Máxima expresividad**: `"model_id": "eleven_v3"` permite etiquetas como `[whispers]`, `[laughs softly]` o `[sarcastic]` en el párrafo hablado.

> Ojo: no clones la voz de una actriz real (tampoco la de Sean Young) sin su consentimiento; va contra los términos de ElevenLabs. Voice Design te da una voz propia y original.

## Costos

Solo se envía a ElevenLabs lo que se va a decir: el resumen hablado, normalmente de 150 a 600 caracteres por respuesta en modo `auto`, con un tope de `summary_max_chars`. "Repite" reproduce el audio guardado y no gasta nada. Saludos y avisos se guardan en caché local (`~/.talktome/cache`) y a partir de la segunda vez no gastan nada. Con `eleven_multilingual_v2` (1 crédito/carácter), unas 100 respuestas al día rondan los 30–50 mil créditos; con `eleven_flash_v2_5` es la mitad. Revisa tu saldo con `talktome.py quota`.

La red de seguridad (resumen generado cuando una respuesta no trae el suyo) usa tu plan de Claude, no ElevenLabs. Con el estilo Rachel activo casi nunca hace falta.

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `syntax error near unexpected token '&'` al abrir Claude Code | Instalación anterior a la corrección de rutas con espacios. `git pull` y `python install.py`. |
| Rachel solo lee el primer párrafo y no tiene su tono | El proyecto usa otro estilo de salida (por ejemplo "Concise"), que gana sobre el de usuario. En ese proyecto: `/config` → Output style → Rachel. Si vuelve a cambiar, edita `outputStyle` en su `.claude/settings.json`. Mientras tanto, la red de seguridad genera el resumen (con unos segundos de espera). |
| Acento de España | Voz generada antes del cambio a español latino: `python talktome.py design` (opción `--acento`). |
| `Invalid API key` (401) | `python talktome.py doctor` muestra el principio y el final de la clave y de dónde sale (`.env` o una variable de entorno de Windows que tiene prioridad). |
| A veces no lee la respuesta | `type $HOME\.talktome\talktome.log`: cada respuesta deja una línea (si trajo resumen propio, si hubo que generarlo y cuánto tardó, o si llegó vacía), además de cualquier error. |

## Hoja de ruta

- **Fase 1 — Rachel habla** ✅ (este repo): voz latina diseñada a medida, estilo Rachel, resumen hablado de cada respuesta con la pregunta pendiente primero, red de seguridad, saludos, avisos que esperan su turno, interrupción al escribir, "repite" y caché.
- **Fase 2 — Rachel escucha**: dictado por voz hacia Claude Code. Hoy ya funciona sin código con el dictado del sistema (Windows `Win+H`, macOS doble `Fn`). Siguiente paso: push-to-talk con ElevenLabs Speech-to-Text (Scribe) y palabra de activación "Rachel".
- **Fase 3 — Conversación fluida**: modo manos libres de ida y vuelta (voz → Claude Code → voz) con turnos, interrupciones naturales y resumen hablado del progreso de tareas largas.

## Desarrollo

```bash
python -m unittest -v      # pruebas (sin red ni audio)
```

Estructura: `voice/speakable.py` (markdown → habla, detección del resumen y de preguntas pendientes), `transcript.py` (respuesta final), `summarizer.py` (red de seguridad con `claude -p`), `tts.py` (ElevenLabs y Voice Design), `player.py` (audio, segundo plano, turnos, interrupción, repetir), `hooks.py` (eventos de Claude Code), `persona.py` (frases de Rachel), `cli.py` (comandos). `tests/` incluye respuestas reales de RockAvionics como casos de prueba. Los errores nunca rompen Claude Code: se registran en `~/.talktome/talktome.log`.
