import os
import tempfile

# Before any `voice` import: tests never touch the user's ~/.talktome.
os.environ["TALKTOME_STATE"] = tempfile.mkdtemp(prefix="talktome-test-")
# Nor the user's own config, nor the project's .env.
os.environ["TALKTOME_USER_DIR"] = os.path.join(os.environ["TALKTOME_STATE"], "usuario")
os.environ["TALKTOME_ENV_FILE"] = os.path.join(os.environ["TALKTOME_STATE"], "env")
