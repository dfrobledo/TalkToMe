# TalkToMe — Claude Code con voz de Jarvis

Proyecto RocketYeah: que Claude Code **hable** como J.A.R.V.I.S., en versión femenina: veinteañera, voz aterciopelada y humor negro de mayordomo británico. Cada vez que Claude termina una respuesta, TalkToMe la convierte en habla natural con ElevenLabs y la dice en voz alta. Te saluda al abrir sesión, te avisa cuando necesita permiso y se calla en cuanto le hablas.

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
   3. elige qué decir: completa si es corta, el párrafo hablado si es larga
   4. ElevenLabs (streaming) ──► mpv: empieza a sonar antes de terminar de generarse
```

| Evento de Claude Code | Qué hace Jarvis |
|---|---|
| `SessionStart` | "Buenas noches, señor. ¿Qué vamos a romper hoy?" |
| `Stop` | Lee la respuesta (o su resumen hablado) |
| `Notification` | "Señor, necesito su permiso para usar Bash. Prometo no incendiar nada." |
| `UserPromptSubmit` | Se calla al instante: usted tiene la palabra |

## El truco para que suene humano

Leer respuestas técnicas palabra por palabra suena a robot, por buena que sea la voz. Por eso hay dos capas:

1. **Estilo de salida "Jarvis"** (`claude/output-styles/jarvis.md`): Claude abre cada respuesta con un *párrafo hablado* de 1–3 frases, escrito para el oído: sin símbolos, con ritmo y con humor negro británico. El detalle técnico va debajo, solo en pantalla.
2. **Voz de ElevenLabs** bien afinada: modelo multilingüe, estabilidad media (más expresiva que monótona), streaming y frases cortas en caché.

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
| `python talktome.py say "texto"` | Decir algo (sin texto: frase de prueba) |
| `python talktome.py design` | Crear su voz con Voice Design (ver abajo) |
| `python talktome.py voices` | Listar tus voces con su ID |
| `python talktome.py quota` | Caracteres disponibles en tu plan |
| `python talktome.py stop` | Callar la frase en curso |
| `python talktome.py mute` / `unmute` | Silenciar / reactivar a Jarvis |
| `python talktome.py doctor` | Diagnóstico completo |

Para que no hable en ejecuciones automáticas (por ejemplo `claude -p` en scripts), define la variable de entorno `TALKTOME_DISABLE=1`. Para apagarlo del todo: `"enabled": false` en la config.

## Configuración (`jarvis.config.json`)

| Clave | Valor por defecto | Notas |
|---|---|---|
| `honorific` | `"señor"` | Cómo te llama Jarvis |
| `voice_id` | Lily (`pFZP5JQG7iQjIQuC4Bku`) | Provisional: británica, aterciopelada. `design` la reemplaza |
| `model_id` | `eleven_multilingual_v2` | Ver tabla de modelos |
| `voice_settings` | stability 0.4 · similarity 0.8 · style 0.35 · speed 0.97 | Menos stability = más emoción |
| `mode` | `auto` | `auto`, `lead` (solo párrafo hablado) o `full` |
| `max_chars` | 450 | Tope por respuesta: protege tus créditos |
| `greet_on_start`, `speak_notifications`, `interrupt_on_prompt` | `true` | |
| `player` | `auto` | `mpv`, `ffplay` o `auto` |

| Modelo | Cuándo usarlo |
|---|---|
| `eleven_multilingual_v2` | El español más natural y estable. **Recomendado para empezar.** |
| `eleven_flash_v2_5` | Latencia ~75 ms y la mitad de créditos por carácter; algo menos de matiz. |
| `eleven_v3` | El más expresivo; entiende etiquetas como `[sighs]`, `[whispers]`, `[sarcastic]` (TalkToMe las conserva solo con este modelo). Más latencia. |

## La voz: más humana que un humano

Ella: británica de veintitantos, voz grave y aterciopelada, un punto ronca, íntima pero serena, que habla español con un leve acento inglés y humor negro impasible.

1. **Voice Design, el camino recomendado.** `python talktome.py design` le describe esa voz a ElevenLabs (la descripción está en inglés porque así la sigue con más fidelidad), genera varias candidatas diciendo una frase en personaje, te las reproduce y guarda la que elijas en tu biblioteca y en `jarvis.config.json`. Con `r` generas otra tanda. Puedes pasar tu propia descripción con `--description "..."`. Cada tanda consume algunos créditos.
2. **Mientras tanto**, la voz por defecto es *Lily*, británica y aterciopelada pero algo mayor. Otras prediseñadas: `talktome.py voices`, y para probar una sin tocar la config: `ELEVENLABS_VOICE_ID=<id> python talktome.py say`.
3. **Afinado fino** en `voice_settings`: `stability` 0.3–0.4 da más vida y picardía; `style` hasta ~0.45 da más interpretación (más arriba sobreactúa); `speed` 0.95–0.97 da la cadencia pausada y seductora.
4. **Máxima expresividad**: `"model_id": "eleven_v3"` permite etiquetas como `[whispers]`, `[laughs softly]` o `[sarcastic]` en el párrafo hablado.

> Ojo: no clones la voz de una actriz real sin su consentimiento; va contra los términos de ElevenLabs. Voice Design te da una voz propia y original.

## Costos

Solo se envía a ElevenLabs lo que se va a decir (normalmente 100–300 caracteres por respuesta en modo `auto`). Saludos y avisos se guardan en caché local (`~/.talktome/cache`) y a partir de la segunda vez no gastan nada. Con `eleven_multilingual_v2` (1 crédito/carácter), unas 100 respuestas al día rondan los 20–30 mil créditos; con `eleven_flash_v2_5` es la mitad. Revisa tu saldo con `talktome.py quota`.

## Hoja de ruta

- **Fase 1 — Jarvis habla** ✅ (este repo): voz, estilo, saludos, avisos, interrupción, caché.
- **Fase 2 — Jarvis escucha**: dictado por voz hacia Claude Code. Hoy ya funciona sin código con el dictado del sistema (Windows `Win+H`, macOS doble `Fn`). Siguiente paso: push-to-talk con ElevenLabs Speech-to-Text (Scribe) y palabra de activación "Jarvis".
- **Fase 3 — Conversación fluida**: modo manos libres de ida y vuelta (voz → Claude Code → voz) con turnos, interrupciones naturales y resumen hablado del progreso de tareas largas.

## Desarrollo

```bash
python -m unittest -v      # pruebas (sin red ni audio)
```

Estructura: `jarvis/speakable.py` (markdown → habla), `transcript.py` (respuesta final), `tts.py` (ElevenLabs), `player.py` (audio, segundo plano, interrupción), `hooks.py` (eventos de Claude Code), `persona.py` (frases de Jarvis), `cli.py` (comandos). Los errores nunca rompen Claude Code: se registran en `~/.talktome/talktome.log`.
