"""Package version helpers for Nudge runtime surfaces."""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path


PACKAGE_NAME = "nudge-ai-life-coach"


def get_version() -> str:
    """Return the installed package version, falling back to pyproject.toml."""
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return _pyproject_version()


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(data["project"]["version"])
