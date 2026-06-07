"""Shared runtime configuration wiring."""

from __future__ import annotations

from pathlib import Path

from nudge.config import PROJECT_ROOT, load_config
from nudge.state import configure_state


def load_runtime_config(config_path: str | Path | None = None, *, loader=load_config) -> dict:
    """Load config and synchronize process-wide runtime state."""
    config = loader(config_path)
    configure_runtime_state(config)
    return config


def configure_runtime_state(config: dict) -> Path:
    """Point process-wide state globals at the loaded config."""
    state_dir = configure_state(config)

    from nudge.commands import agent as agent_command_module
    from nudge.commands import dogfood as dogfood_command_module
    import nudge.dogfood as dogfood_module

    agent_command_module.configure_agent_state(config)
    dogfood_command_module.STATE_DIR = state_dir
    dogfood_module.STATE_DIR = state_dir
    return state_dir


def resolve_config_path(config_path: str | Path) -> Path:
    """Resolve CLI config paths with the same base as load_config."""
    path = Path(config_path).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path
