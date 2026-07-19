"""Guardrails that keep pytest away from the user's real Nudge state."""

import os
from pathlib import Path


def test_pytest_session_uses_an_ephemeral_nudge_state_dir():
    isolated = os.environ.get("NUDGE_TEST_STATE_DIR")

    assert isolated, "pytest must install an isolated Nudge state directory before test imports"
    assert os.environ.get("NUDGE_STATE_DIR") == isolated

    parent = os.environ.get("NUDGE_TEST_PARENT_STATE_DIR")
    if parent:
        assert Path(isolated).resolve() != Path(parent).resolve()

    from nudge import state

    assert state.STATE_DIR.resolve() == Path(isolated).resolve()
    assert state.DB_PATH.resolve() == (Path(isolated) / "nudge.db").resolve()
