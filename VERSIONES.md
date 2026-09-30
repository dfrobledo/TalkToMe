# Versiones de TalkToMe

Cada versión estable, con el commit exacto para volver a ella. Tu voz, tu clave y tu configuración no dependen de la versión: sobreviven a cualquier cambio (ver [abajo](#qué-está-en-git-y-qué-no)).

| Versión | Commit | Qué trae | Necesita |
|---|---|---|---|
| Primera (Jarvis) | `8ce24f7` | Claude Code habla con ElevenLabs | Python 3.9+, mpv o ffmpeg |
| Llega Rachel | `3ae400a` | La asistente es Rachel, al estilo Blade Runner | Igual |
| **Fase 1 — Rachel habla** | `deb1f83` | Resumen hablado, red de seguridad, "repite", "detalle", varias terminales, mazos de frases | Igual |
| **Fase 2a — Rachel escucha** | `42c092e` | Dictado con F9, Scribe en tiempo real, compañía mientras Claude piensa, arranque automático, avisos de error en voz alta | Igual + Windows para el dictado |
| **Blindaje de la voz** | `103e462` | Tu configuración fuera del repositorio, respaldos, historial de voces, autorreparación, copia en `.env` para cualquier versión, `voices --recuperar` | Igual |

La **Fase 2c** (llamarla por su nombre) está en desarrollo en su propia rama y todavía no es una versión estable.

## Volver a una versión anterior, sin perder nada

```powershell
cd E:\AI\Claude\TalkToMe
git status                                            # ¿hay cambios sin guardar?
git stash push -u -m "antes de cambiar de versión"    # solo si los hay
git switch --detach 42c092e                           # el commit de la tabla
python install.py                                     # los hooks de esa versión
```

Para volver a la última versión:

```powershell
git switch main
git pull
python install.py
git stash pop                                         # solo si guardaste cambios arriba
```

Nunca uses `git reset --hard` ni `git clean`: borran lo que no está en git.

## Qué está en git y qué no

| Qué | Dónde | ¿En git? | Si se pierde |
|---|---|---|---|
| Código, pruebas, documentación, estilo Rachel | El repositorio | Sí, con historia completa | Se recupera de git |
| Valores por defecto del proyecto | `talktome.config.json` | Sí | Se recupera de git |
| **Tu configuración** (voz, ajustes, proyectos) | `%APPDATA%\TalkToMe\config.json` | No, a propósito: ninguna operación de git puede tocarla | 10 respaldos en `respaldos\`, y el historial de voces la repara sola |
| **Historial de tus voces** | `%APPDATA%\TalkToMe\voces.json` | No | La voz sigue en tu biblioteca de ElevenLabs: `voices --recuperar` |
| **Tu clave de ElevenLabs** | `.env` | **Nunca**: expondría tu cuenta | Se copia de nuevo desde la web de ElevenLabs |
| Copia de tu voz para versiones anteriores | Bloque `# >>> TalkToMe` en `.env` | No | Se reescribe sola al cargar la configuración |
| Caché de audio, memoria de sesiones, log | `~/.talktome` | No | Se regenera; borrarla es seguro |
| Hooks de Claude Code | `~/.claude/settings.json` | No | `python install.py` los vuelve a poner (deja copia en `settings.json.bak-talktome`) |

Incluye `%APPDATA%\TalkToMe` en tu respaldo habitual (OneDrive, Historial de archivos): es lo único que no puede reconstruirse solo si falla el disco.

## Compatibilidad hacia atrás

- **Tu voz** la encuentra cualquier versión, desde la primera: todas leen `ELEVENLABS_VOICE_ID` de `.env`, y ahí queda una copia. `tests/test_protection.py` lo comprueba con el código real de cada versión de la tabla.
- **Tus ajustes finos** (velocidad, estabilidad) y tus proyectos solo los leen las versiones desde el blindaje. Las anteriores usan los valores por defecto del proyecto con tu voz.
- **Los hooks** cambian entre versiones (la Fase 2a agregó `SessionEnd`). Por eso se corre `python install.py` después de cada cambio de versión: primero quita los hooks de TalkToMe y luego pone los de esa versión.
