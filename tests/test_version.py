"""Tests for the single Nudge package version source."""

import importlib.metadata

from nudge.version import PACKAGE_NAME, get_version


def test_get_version_prefers_package_metadata(monkeypatch):
    calls = []

    def fake_version(package_name):
        calls.append(package_name)
        return "7.6.5"

    monkeypatch.setattr(importlib.metadata, "version", fake_version)

    assert get_version() == "7.6.5"
    assert calls == [PACKAGE_NAME]


def test_get_version_falls_back_to_pyproject_version(monkeypatch):
    def missing_metadata(package_name):
        raise importlib.metadata.PackageNotFoundError(package_name)

    monkeypatch.setattr(importlib.metadata, "version", missing_metadata)

    assert get_version() == "0.5.2"
