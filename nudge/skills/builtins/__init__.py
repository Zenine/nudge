"""Built-in Skill examples bundled with Nudge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

import re
import shutil
import yaml

from nudge.skills.schema import SkillValidationError, ValidationIssue, load_skill_file, validate_skill


_BUILTIN_PACKAGE = "nudge.skills.builtins"
_BUILTIN_ORDER = [
    "strength-basics-12w",
    "deep-learning-sprint-4w",
    "deep-work-weekly-rhythm",
]
_SKILL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][\w.-]*$")


@dataclass(frozen=True)
class SkillSummary:
    """Small descriptor for one Skill in list output."""

    id: str
    title: str
    version: str
    creator: str
    category: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "version": self.version,
            "creator": self.creator,
            "category": self.category,
            "source": self.source,
        }


def _custom_skills_dir() -> Path:
    return Path.home() / ".nudge" / "skills"


def _custom_skill_history_dir() -> Path:
    return _custom_skills_dir() / ".history"


def _normalize_skill_id(skill_id: str) -> str:
    return str(skill_id).strip()


def _custom_skill_path(skill_id: str) -> Path:
    return _custom_skills_dir() / f"{_normalize_skill_id(skill_id)}.yaml"


def _ensure_custom_dirs() -> None:
    _custom_skills_dir().mkdir(parents=True, exist_ok=True)
    _custom_skill_history_dir().mkdir(parents=True, exist_ok=True)


def _ensure_valid_custom_id(skill_id: str) -> None:
    if not _SKILL_ID_PATTERN.fullmatch(skill_id):
        raise SkillValidationError([
            ValidationIssue(
                "metadata.id",
                "custom skill id must only contain letters, digits, dot, hyphen, or underscore",
            )
        ])


def is_builtin_skill(skill_id: str) -> bool:
    """Return whether a bundled Skill with this id exists."""
    return skill_id in _BUILTIN_ORDER and _builtin_resource(skill_id).is_file()


def _builtin_resource(skill_id: str):
    return resources.files(_BUILTIN_PACKAGE).joinpath(f"{skill_id}.yaml")


def get_builtin_skill(skill_id: str) -> dict[str, Any]:
    """Load and validate one bundled Skill by id."""
    if not is_builtin_skill(skill_id):
        raise SkillValidationError([ValidationIssue("skill", f"Unknown built-in Skill: {skill_id}")])
    with resources.as_file(_builtin_resource(skill_id)) as path:
        return validate_skill(load_skill_file(path))


def is_custom_skill(skill_id: str) -> bool:
    """Return whether a user-defined Skill exists in `~/.nudge/skills`."""
    candidate = _custom_skill_path(skill_id)
    return candidate.exists()


def get_custom_skill(skill_id: str) -> dict[str, Any]:
    path = _custom_skill_path(skill_id)
    if not path.exists():
        raise SkillValidationError([ValidationIssue("skill", f"Unknown custom Skill: {skill_id}")])
    return validate_skill(load_skill_file(path))


def list_builtin_skills() -> list[dict[str, str]]:
    """Return metadata summaries for bundled Skills in stable display order."""
    summaries = []
    for skill_id in _BUILTIN_ORDER:
        metadata = get_builtin_skill(skill_id)["metadata"]
        summaries.append(
            SkillSummary(
                id=str(metadata["id"]),
                title=str(metadata["title"]),
                version=str(metadata["version"]),
                creator=str(metadata["creator"]),
                category=str(metadata["category"]),
                source="builtin",
            ).to_dict()
        )
    return summaries


def list_custom_skills() -> list[dict[str, str]]:
    """Return metadata summaries for user-defined Skills."""
    if not _custom_skills_dir().exists():
        return []

    summaries: list[dict[str, str]] = []
    for path in sorted(_custom_skills_dir().glob("*.yaml")):
        if path.name.startswith("."):
            continue
        skill = load_skill_file(path)
        validated = validate_skill(skill)
        metadata = validated["metadata"]
        summaries.append(
            SkillSummary(
                id=str(metadata["id"]),
                title=str(metadata["title"]),
                version=str(metadata["version"]),
                creator=str(metadata["creator"]),
                category=str(metadata["category"]),
                source="custom",
            ).to_dict()
        )

    return summaries


def list_all_skills() -> list[dict[str, str]]:
    """Return bundled + user-defined skills in stable order."""
    return list_builtin_skills() + list_custom_skills()


def load_skill_source(source: str | Path) -> dict[str, Any]:
    """Load a Skill from a filesystem path, custom Skill id, or bundled built-in id."""
    source_text = str(source)
    path = Path(source_text).expanduser()
    if path.exists():
        return validate_skill(load_skill_file(path))

    if is_custom_skill(source_text):
        return get_custom_skill(source_text)

    return get_builtin_skill(source_text)


def load_custom_skill_text(path: Path) -> dict[str, Any]:
    return validate_skill(load_skill_file(path))


def dump_skill_yaml(skill: dict[str, Any]) -> str:
    """Render a Skill as readable YAML for `nudge skills show`."""
    return yaml.safe_dump(skill, allow_unicode=True, sort_keys=False)


def _history_path(skill_id: str, metadata: dict[str, Any], timestamp: str) -> Path:
    return _custom_skill_history_dir() / _normalize_skill_id(skill_id) / f"{metadata.get('version', 'unknown')}_{timestamp}.yaml"


def create_skill_snapshot(skill_id: str) -> None:
    """Persist current versioned copy before overwrite."""
    source = _custom_skill_path(skill_id)
    if not source.exists():
        return

    _ensure_custom_dirs()
    metadata = validate_skill(load_skill_file(source))["metadata"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history_file = _history_path(skill_id, metadata, timestamp)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, history_file)


def write_custom_skill(skill: dict[str, Any], allow_overwrite: bool = False) -> None:
    """Persist a validated Skill to `~/.nudge/skills/<id>.yaml`."""
    _ensure_valid_custom_id(skill["metadata"]["id"])
    skill_id = skill["metadata"]["id"]
    if is_builtin_skill(skill_id):
        raise SkillValidationError([
            ValidationIssue(
                "metadata.id",
                f"built-in Skill id is read-only: {skill_id}",
            )
        ])

    _ensure_custom_dirs()
    target = _custom_skill_path(skill_id)
    if target.exists() and not allow_overwrite:
        raise SkillValidationError([ValidationIssue("metadata.id", f"custom Skill already exists: {skill_id}")])
    target.write_text(dump_skill_yaml(skill), encoding="utf-8")


def write_custom_skill_with_snapshot(skill: dict[str, Any]) -> None:
    """Create or overwrite custom Skill after snapshotting current version."""
    _ensure_valid_custom_id(skill["metadata"]["id"])
    skill_id = skill["metadata"]["id"]
    create_skill_snapshot(skill_id)
    write_custom_skill(skill, allow_overwrite=True)

def delete_custom_skill(skill_id: str) -> None:
    """Delete custom Skill file from `~/.nudge/skills`."""
    _ensure_valid_custom_id(skill_id)
    if is_builtin_skill(skill_id):
        raise SkillValidationError([ValidationIssue("skill", f"built-in Skill cannot be deleted: {skill_id}")])
    path = _custom_skill_path(skill_id)
    if not path.exists():
        raise SkillValidationError([ValidationIssue("skill", f"Unknown custom Skill: {skill_id}")])
    path.unlink()
