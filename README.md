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
| `UserPromptSubmit` | Se calla al instante: usted tiene la palabra (solo en esa terminal) |
| Escribes **"repite"** | Repite su última respuesta, sin gastar créditos ni turno de Claude |
| Escribes **"detalle"** | Le narra el resto de la última respuesta, más allá del resumen |
| Mantienes **F9** y hablas | Se calla, te escucha y le manda tus palabras a Claude Code; mientras Claude piensa, te acompaña |
| Algo falla | Te dice qué componente revisar: "Falla de red, señor: no llego a ElevenLabs…" |
| `SessionEnd` | Al cerrar la última sesión, deja de escuchar y libera F9 |

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

Abre una sesión nueva de Claude Code y deberías oír el saludo. En Windows ya puedes hablarle: mantén F9, habla y suelta.

Si ya tenías TalkToMe instalado, después de `git pull` vuelve a correr `python install.py`: registra el hook `SessionEnd`, con el que la escucha sabe cuándo irse. `install.py` hace copia de seguridad de `~/.claude/settings.json` y es idempotente; `python install.py --uninstall` lo deja todo como estaba. Con `--no-style` instalas solo la voz, sin cambiar el estilo de Claude (en ese caso se lee el primer párrafo de cada respuesta, sea cual sea).

Sin mpv/ffmpeg también funciona (Windows usa `winsound`), pero espera a tener el audio completo antes de hablar.

## Comandos

| Comando | Para qué |
|---|---|
| `python talktome.py repite` | Repite la última respuesta (de cualquier proyecto) desde la terminal |
| `python talktome.py detalle` | Narra el detalle de la última respuesta desde la terminal |
| `python talktome.py say "texto"` | Decir algo (sin texto: frase de prueba) |
| `python talktome.py design` | Crear su voz con Voice Design (ver abajo) |
| `python talktome.py voices` | Listar tus voces con su ID |
| `python talktome.py quota` | Caracteres disponibles en tu plan |
| `python talktome.py frases` | Ver el banco de frases y las que inventó Claude (`--inventa`: pedir nuevas ya) |
| `python talktome.py escucha` | Dictado a mano (normalmente arranca solo con Claude Code); `--detener` termina el de fondo |
| `python talktome.py oye [archivo]` | Probar la transcripción sin enviar nada |
| `python talktome.py avisos` | Avisos de error: cuáles hay, si están en caché (`--prueba mic` para oír uno) |
| `python talktome.py stop` | Callar la frase en curso |
| `python talktome.py mute` / `unmute` | Silenciar / reactivar a Rachel |
| `python talktome.py doctor` | Diagnóstico completo |

Para que no hable en ejecuciones automáticas (por ejemplo `claude -p` en scripts), define la variable de entorno `TALKTOME_DISABLE=1`. Para apagarlo del todo: `"enabled": false` en la config.

## Que te repita algo

Escribe **repite** en Claude Code y pulsa Enter. También sirven "repítelo", "otra vez", "¿qué dijiste?" o "no te escuché", con o sin "Rachel" y "por favor". Tiene que ser el mensaje completo: "repite la prueba con más datos" sigue yendo a Claude como siempre.

Ese mensaje nunca llega a Claude: un hook lo intercepta, así que no consume tu plan ni aparece en la conversación. Rachel reproduce el audio guardado de su última respuesta, sin gastar créditos de ElevenLabs; solo si la habías interrumpido a mitad de frase la vuelve a generar completa.

## Que te lea el detalle

Por defecto Rachel solo dice el resumen: leer en voz alta cada respuesta completa, con sus pines, rutas y tablas, cansa. Cuando quieras el resto, escribe **detalle** (también "léeme el detalle", "dame el detalle", "léelo todo"), como mensaje completo.

Rachel dice "Deme unos segundos" y le pide a Claude (la misma red de seguridad, con tu plan) que convierta la respuesta en una lectura para el oído: completa, sin repetir el resumen que ya oíste, con las tablas dichas como frases, el código descrito en vez de leído y terminando en lo que te pide. Suele tardar de 10 a 20 segundos. Si Claude no responde, lee la respuesta tal cual, limpia de símbolos.

Un detalle largo puede ocupar unos 2.500 caracteres de ElevenLabs (unos tres minutos de voz); el tope es `detail_max_chars`. Escribir cualquier cosa la interrumpe, como siempre.

## Háblale: dictado con una tecla

**Arranca sola con Claude Code**: al abrir una sesión, Rachel empieza a escuchar en segundo plano, sin ventana, y se va cuando cierras la última sesión (o tras 2 horas sin actividad). No hay nada que lanzar. Si prefieres controlarla a mano: `"listen_on_start": false`, y luego `python talktome.py escucha` en su propia consola (`escucha --detener` para terminar la de fondo).

Mantén **F9** mientras hablas y suéltala: suena un bip corto y Rachel se calla al instante. Al soltar la tecla, tus palabras se escriben en la terminal que tenías al frente y se envían solas, como si las hubieras tecleado.

```
 mantienes F9    ─► graba al instante y Rachel se calla      (en tu PC)
 mientras hablas ─► el audio ya va llegando a Scribe         (ElevenLabs, voz → texto, en tiempo real)
 sueltas F9      ─► texto + Enter en la terminal             (llega a Claude como si lo teclearas)
                 ─► "Entendido, señor."                      (de inmediato, desde la caché)
 Claude trabaja  ─► "Mmm, a ver..." · "Corriendo las pruebas..."
 Claude responde ─► Rachel lo dice                           (ElevenLabs, texto → voz, como siempre)
```

**Mientras Claude piensa, Rachel no se queda muda.** En los turnos que empiezas por voz:

- **Acuse inmediato** al soltar la tecla: "Entendido, señor.", "Mmm, buena pregunta.", "Me pongo en eso."
- **Interjecciones**: los sonidos cortos de alguien hilando ideas ("Mmm...", "A ver, a ver...", "Déjeme hilar esto..."). Con `eleven_v3` además suspira y murmura de verdad.
- **Progreso**: qué está haciendo Claude, leído de las herramientas que usa ("Revisando el código...", "Corriendo las pruebas...", "Mandé a un replicante a investigar.").
- **Con mesura**: la primera a los 5 segundos, y cada vez más espaciadas (hasta 30 s). Nunca habla encima de nadie y se calla en cuanto llega la respuesta. No frena a Claude, porque solo lee el transcript. El análisis y el estilo siguen siendo de Claude: esto es solo compañía.
- **Sin costo extra**: son frases cortas que después de la primera vez salen de la caché. `"narrate_progress": "always"` las activa también cuando escribes, y `"off"` las apaga; `"voice_ack": false` quita el acuse.

- A Claude solo le llega texto, nunca tu audio. "Repite" y "detalle" dichos en voz alta funcionan igual que escritos, y **"calla"** o "silencio" solo la callan, sin gastar un turno de Claude.
- Si cambias de ventana mientras transcribe, el texto no se escribe en otra aplicación: queda en el portapapeles (bip grave).
- Una pulsación demasiado corta suena con un bip medio: no se envía nada.
- Si la transcripción en tiempo real falla (red, clave, proxy), el dictado usa Scribe normal sin que hagas nada; `talktome.log` lo registra. `"stt_realtime": false` la apaga.
- Otra tecla: `--tecla F8` o `"listen_key"` en la config (F1–F24, `Pause`, `ScrollLock`, `RightCtrl`, `RightAlt`).
- Para que Scribe acierte nombres propios y jerga: `"stt_keyterms": ["RockAvionics", "RocketYeah", "Rachel"]`.
- Scribe cobra por minuto de audio, aparte de los caracteres de voz; un dictado corto cuesta poco. `python talktome.py oye` transcribe sin enviar nada, para probar, y `oye` con el archivo `~/.talktome/dictado.wav` revisa el último dictado.
- **Tiempos**: `talktome.log` anota cuánto tardó cada tramo: la transcripción después de soltar la tecla, el turno de Claude y cuánto tardó Rachel en empezar a hablar.
- Si la terminal corre como administrador, `escucha` también debe hacerlo: Windows no deja escribir en una ventana con más privilegios.

## Si algo falla, Rachel lo dice

Casi todo TalkToMe corre sin ventana, así que un error silencioso sería invisible. En lugar de eso, Rachel lo dice en voz alta, empezando por el componente que hay que revisar:

- "Falla en ElevenLabs, señor: la clave no es válida. Revise el archivo punto env de TalkToMe."
- "Falla de red, señor: no llego a ElevenLabs. Revise su conexión a internet."
- "Falla en el micrófono, señor. Revise que esté conectado y permitido en la privacidad de Windows."

Hay avisos para la clave, los créditos, la red, el micrófono, Scribe, la escucha, el resumidor, el reproductor y la terminal como administrador.

- **Con su voz aunque ElevenLabs falle.** Al abrir sesión, los avisos se generan una sola vez y quedan en caché (unos 1.200 caracteres por voz). Si ElevenLabs se cae, ella los dice igual desde la caché. Si no estuvieran en caché, habla la voz de Windows.
- **Sin letanías.** Cada tipo de aviso se dice como mucho una vez cada 10 minutos. El registro completo sigue en `talktome.log`.
- `python talktome.py avisos` los lista y muestra cuáles ya están en caché; `--prueba mic` te deja escuchar uno. `"report_errors": false` los apaga.

## Varias terminales, varios proyectos

Cada terminal es una sesión de Claude Code, y Rachel las trata por separado:

- **Cada una con su memoria.** "Repite" y "detalle" usan la última respuesta de *esa* terminal, nunca la del otro proyecto.
- **Escribir solo calla a la suya.** Si RocketYeah está hablando y usted escribe en RockAvionics, RocketYeah termina su frase.
- **Una sola voz, por turnos.** Si dos proyectos terminan a la vez, el segundo espera a que el primero acabe en lugar de cortarlo (hasta 5 minutos para respuestas y 3 para avisos). El recordatorio de espera no hace fila: si alguien está hablando, se omite. Dentro de una misma terminal, una respuesta nueva sí interrumpe a la anterior, como siempre.
- **Distintivo de proyecto.** Cuando la voz salta de un proyecto a otro, Rachel dice primero desde dónde habla, con un mazo de frases de cine negro: "En Rock Avionics, señor:", "Transmisión desde Rocket Yeah.", "Ampliar sector Rock Avionics. Detener.", "Otra ventana encendida en la ciudad: Talk To Me." Si sigue en el mismo proyecto no lo repite, y los permisos también lo llevan ("Desde Rock Avionics, señor. Necesito su permiso para usar Bash…"). Al abrir sesión, el saludo lo incluye: "Buenas noches, señor. Expediente Rock Avionics abierto."

El nombre sale de la carpeta del repositorio (aunque abra Claude en una subcarpeta), separado para que se pronuncie bien: `RockAvionics` se dice "Rock Avionics". En la config puede darle a cada proyecto un nombre propio, o incluso otra voz, otro trato o su propio ajuste de voz, para reconocerlo sin que diga nada:

```json
"announce_project": "switch",
"projects": {
  "RockAvionics": "la aviónica del cohete",
  "RocketYeah": {"name": "la Torre Tyrell", "voice_id": "<otra voz>", "voice_settings": {"speed": 1.02}}
}
```

`announce_project`: `"switch"` (por defecto, solo al cambiar de proyecto), `"always"` (antes de cada respuesta) u `"off"`. Los distintivos son cortos y quedan en caché: después de la primera vez no gastan créditos.

## Frases de Rachel: nunca la misma dos veces

Saludos, avisos de permiso y recordatorios de espera salen de un banco de frases del universo Blade Runner (`voice/lines.py`): la película, 2049 y la novela de Philip K. Dick.

- **Mazo barajado.** Ninguna frase se repite hasta que salieron todas las de su mazo, y al barajar de nuevo nunca repite la última.
- **Escalada.** Si la dejas esperando varias veces seguidas (en menos de hora y media), el recordatorio sube de tono: primero suave ("Llueve en Los Ángeles…"), luego irónico ("Mis pupilas no se dilatan…") y al tercero dramático ("…como lágrimas en la lluvia"). Después vuelve a empezar.
- **Hora del día.** De noche hay lluvia, neón y la pirámide Tyrell; de día, sol sobre las granjas de proteínas.
- **Efemérides.** El 8 de enero (activación de Roy Batty), el 25 de junio (estreno de Blade Runner), el 6 de octubre (estreno de 2049), el 1 de noviembre (el mes de la película) y el 16 de diciembre (natalicio de Philip K. Dick) la primera frase del día lo recuerda.
- **Frases inventadas.** Después de un recordatorio, una de cada cinco veces (`invent_chance`), Claude escribe tres frases nuevas con tu plan y se suman al mazo. Nunca retrasa a Rachel: ocurre cuando ya terminó de hablar. Se guardan en `~/.talktome/lines.json` (las últimas `invented_max`), aparecen en `talktome.log` y las ves con `python talktome.py frases`. Si alguna no te gusta, bórrala de ese archivo.

Todas caben en la caché: cada frase gasta caracteres de ElevenLabs solo la primera vez que se dice.

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
| `detail_max_chars` | 2500 | Tope de la lectura del detalle |
| `summarizer` | `"claude"` | Red de seguridad para respuestas sin resumen; `"off"` la apaga (y también las frases inventadas) |
| `invent_chance` | 0.2 | Probabilidad de que Claude invente frases nuevas tras un recordatorio; 0 lo apaga |
| `invented_max` | 60 | Cuántas frases inventadas se conservan |
| `announce_project` | `"switch"` | Decir desde qué proyecto habla: `switch`, `always` u `off` |
| `projects` | `{}` | Nombre hablado de cada proyecto (carpeta → nombre) u overrides por proyecto |
| `greet_on_start`, `speak_notifications`, `interrupt_on_prompt` | `true` | |
| `player` | `auto` | `mpv`, `ffplay` o `auto` |
| `listen_key` | `"F9"` | Tecla del dictado |
| `listen_on_start` | `true` | Escuchar en segundo plano mientras Claude Code esté abierto |
| `report_errors` | `true` | Rachel dice en voz alta qué falló y qué revisar |
| `stt_model` | `"scribe_v2"` | Modelo de Speech-to-Text de ElevenLabs |
| `stt_keyterms` | `[]` | Palabras que Scribe debe esperar |
| `stt_realtime` | `true` | Transcribir mientras hablas (Scribe v2 Realtime) |
| `voice_ack` | `true` | "Entendido, señor." al enviar un dictado |
| `narrate_progress` | `"voice"` | Interjecciones y progreso: `voice` (turnos por voz), `always` u `off` |

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

El dictado usa Scribe, que ElevenLabs cobra por minuto de audio (solo mientras mantienes F9). El acuse, las interjecciones, el progreso y los avisos de error son frases cortas en caché: se pagan una sola vez por voz (los avisos se generan al abrir sesión, unos 1.200 caracteres).

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `syntax error near unexpected token '&'` al abrir Claude Code | Instalación anterior a la corrección de rutas con espacios. `git pull` y `python install.py`. |
| Rachel solo lee el primer párrafo y no tiene su tono | El proyecto usa otro estilo de salida (por ejemplo "Concise"), que gana sobre el de usuario. En ese proyecto: `/config` → Output style → Rachel. Si vuelve a cambiar, edita `outputStyle` en su `.claude/settings.json`. Mientras tanto, la red de seguridad genera el resumen (con unos segundos de espera). |
| Acento de España | Voz generada antes del cambio a español latino: `python talktome.py design` (opción `--acento`). |
| `Invalid API key` (401) | `python talktome.py doctor` muestra el principio y el final de la clave y de dónde sale (`.env` o una variable de entorno de Windows que tiene prioridad). |
| A veces no lee la respuesta | `type $HOME\.talktome\talktome.log`: cada respuesta deja una línea (si trajo resumen propio, si hubo que generarlo y cuánto tardó, o si llegó vacía), además de cualquier error. |
| F9 no hace nada | `python talktome.py doctor`: la línea "Dictado" dice si el micrófono responde y si la escucha está corriendo. Si no corre, abre una sesión nueva de Claude Code (o `python talktome.py escucha` a mano). ¿Otra app usa F9? Cambia `listen_key`. |
| Sale un bip medio y no se envía nada | La pulsación fue demasiado corta (menos de `listen_min_seconds`). Mantén la tecla mientras hablas. |
| El texto quedó en el portapapeles | Cambiaste de ventana mientras transcribía; pégalo con Ctrl+V. Si pasa siempre en una terminal, puede que corra como administrador: Rachel te lo dice. |
| El dictado se siente lento | En `talktome.log`, la línea `dictado:` dice cuánto tardó el texto y si fue "en tiempo real" o "por lotes". Si siempre es por lotes, la línea anterior dice por qué falló el tiempo real. |
| Rachel habla demasiado mientras Claude piensa | `"narrate_progress": "off"` quita interjecciones y progreso; `"voice_ack": false`, el acuse. |

## Hoja de ruta

- **Fase 1 — Rachel habla** ✅ (este repo): voz latina diseñada a medida, estilo Rachel, resumen hablado de cada respuesta con la pregunta pendiente primero, red de seguridad, saludos, avisos que esperan su turno, interrupción al escribir, "repite" y caché.
- **Fase 2 — Rachel escucha**: dictado por voz hacia Claude Code.
  - **2a — Push-to-talk** ✅: mantener F9, hablar, soltar; Scribe transcribe en tiempo real y se envía solo. Acuse inmediato, interjecciones y progreso mientras Claude trabaja. "Calla" la silencia sin gastar turno. La escucha arranca y se va sola con Claude Code, y los errores se dicen en voz alta, con el componente a revisar.
  - **2b — Comandos y permisos por voz**: responder "sí" o "no" a los permisos.
  - **2c — Palabra de activación "Rachel"**: escucha continua con un detector local.
- **Fase 3 — Conversación fluida**: modo manos libres de ida y vuelta (voz → Claude Code → voz) con turnos, interrupciones naturales y resumen hablado del progreso de tareas largas.

## Desarrollo

Documentación técnica, con diagramas:

- [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md): cómo funciona por dentro. Flujo de hooks y workers, qué decir en cada respuesta, sesiones y turnos entre terminales, mazos de frases, audio y estado en disco.
- [`docs/REFERENCIA.md`](docs/REFERENCIA.md): comandos, configuración, contrato con Claude Code, API de cada módulo y archivos de estado.

```bash
python -m unittest -v      # pruebas (sin red ni audio)
```

Estructura: `voice/speakable.py` (markdown → habla, detección del resumen y de preguntas pendientes), `transcript.py` (respuesta final), `summarizer.py` (red de seguridad con `claude -p`), `tts.py` (ElevenLabs y Voice Design), `player.py` (audio, segundo plano, turnos entre sesiones, interrupción, repetir), `projects.py` (de qué proyecto habla cada sesión), `hooks.py` (eventos de Claude Code), `stt.py` (Scribe: voz → texto), `realtime.py` (Scribe en tiempo real por WebSocket), `listen.py` (dictado con una tecla), `mic.py` (tecla, micrófono y teclado de Windows), `companion.py` (compañía mientras Claude trabaja), `alerts.py` (avisos de error en voz alta), `persona.py` (qué frase dice Rachel), `lines.py` (banco de frases), `deck.py` (mazos barajados, escalada y frases inventadas), `cli.py` (comandos). `tests/` incluye respuestas reales de RockAvionics como casos de prueba. Los errores nunca rompen Claude Code: se registran en `~/.talktome/talktome.log`.
