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


import pytest


@pytest.fixture(autouse=True)
def _restore_state_module_globals():
    """Undo `configure_state()` side effects between tests.

    Commands that take ``--config`` call ``nudge.state.configure_state`` which
    rebinds module globals outside any monkeypatch. Without restoring them,
    a later test that expects a missing state directory can silently hit the
    previous test's temporary database.
    """
    import nudge.state as state

    saved = {
        name: getattr(state, name)
        for name in ("STATE_DIR", "DB_PATH", "LEGACY_JSON", "_schema_initialized_for", "_migrated")
        if hasattr(state, name)
    }
    yield
    for name, value in saved.items():
        setattr(state, name, value)
