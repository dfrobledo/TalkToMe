import os
import tempfile

# Before any `voice` import: tests never touch the user's ~/.talktome.
os.environ["TALKTOME_STATE"] = tempfile.mkdtemp(prefix="talktome-test-")
