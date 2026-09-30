# TalkToMe: reglas para trabajar en este proyecto

Estas reglas existen porque una vez se perdió la voz de Rachel: el ID de su voz vivía en un archivo versionado y se indicó un `git reset --hard` sin revisar los cambios locales. No se relajan.

## Lo vital

- **La voz de Rachel**: `voice_id` y `voice_settings` del usuario. Es lo que la hace ser ella.
- **La clave de ElevenLabs** (`.env`). Nunca va a git.
- **La configuración del usuario**: `%APPDATA%\TalkToMe\config.json` en Windows (`~/.config/talktome` en otros sistemas), su historial de voces (`voces.json`) y sus respaldos (`respaldos/`).

## Git: nunca borrar trabajo del usuario

- **Nunca** indiques ni ejecutes en la máquina del usuario: `git reset --hard`, `git clean` (con cualquier opción), `git checkout -- <archivo>`, `git restore` sobre archivos que no creaste, `git stash drop`/`clear`, ni un `push --force` a `main`.
- **Antes de pedir un cambio de rama o de versión**, las instrucciones empiezan por:
  ```powershell
  git status
  git stash push -u -m "antes de cambiar de versión"   # solo si git status muestra cambios
  ```
  y terminan recordando `git stash pop` para recuperarlos.
- **Para volver a una versión anterior**: `git switch --detach <commit>` y `python install.py`, según [VERSIONES.md](VERSIONES.md). Nunca `reset`.
- **Una rama ya mergeada** se reinicia desde `main` solo si no tiene commits sin mergear. Si los tiene, primero se guardan en otra rama.

## Configuración

- Lo del usuario **nunca** se guarda en archivos del repositorio. Todo cambio pasa por `config.save_setting()` o `config.save_voice_id()`: respaldan antes de escribir, recuerdan la voz y la copian a `.env` para las versiones anteriores.
- `talktome.config.json` solo tiene los valores por defecto del proyecto.
- El bloque `# >>> TalkToMe` de `.env` lo mantiene el código. Las versiones anteriores leen la voz de ahí, así que no se quita.

## Antes de cada merge

- `python -m unittest` completo. `tests/test_protection.py` reproduce el accidente y cada forma de perder la voz, incluido el código real de versiones anteriores sacado del historial de git. No se debilita ni se salta.
- Cada versión estable se anota en [VERSIONES.md](VERSIONES.md) con su commit, qué trae y qué necesita.
