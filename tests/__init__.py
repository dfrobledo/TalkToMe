import os
import tempfile

# Before any `voice` import: tests never touch the user's ~/.talktome.
os.environ["TALKTOME_STATE"] = tempfile.mkdtemp(prefix="talktome-test-")
os.environ["TALKTOME_LOCAL_CONFIG"] = os.path.join(os.environ["TALKTOME_STATE"], "local.json")
