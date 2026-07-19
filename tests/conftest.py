"""Session-wide pytest isolation for Nudge's mutable local state."""

import atexit
import os
import shutil
import tempfile
from pathlib import Path


_PARENT_STATE_DIR = os.environ.get("NUDGE_STATE_DIR")
_TEST_STATE_DIR = Path(tempfile.mkdtemp(prefix="nudge-pytest-"))

os.environ["NUDGE_TEST_STATE_DIR"] = str(_TEST_STATE_DIR)
os.environ["NUDGE_STATE_DIR"] = str(_TEST_STATE_DIR)
if _PARENT_STATE_DIR:
    os.environ["NUDGE_TEST_PARENT_STATE_DIR"] = _PARENT_STATE_DIR
else:
    os.environ.pop("NUDGE_TEST_PARENT_STATE_DIR", None)


def _cleanup_test_state() -> None:
    shutil.rmtree(_TEST_STATE_DIR, ignore_errors=True)


atexit.register(_cleanup_test_state)
