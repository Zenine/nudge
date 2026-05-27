"""Config loading and access."""

import tomllib
import os
from pathlib import Path


FAMILY_GROUP_ALIASES = ["家庭组", "家人", "全家", "大家", "所有人"]
FAMILY_GROUP_PERSON = "__family_group__"
DEFAULT_CALENDAR_NAME = "Personal"
DEFAULT_REMINDER_LIST = "Tasks"
DEFAULT_NOTES_FOLDER = "Nudge"
DEFAULT_CLOCK_SHORTCUT_NAME = "Nudge Create Alarm"
DEFAULT_SECRETS_PATH = Path.home() / ".config" / "nudge" / "secrets.yaml"
DEFAULT_LLM_CONFIG = {
    "provider": "qwen",
    "model": "qwen-plus",
    "models": {
        "default": "qwen-plus",
        "fast": "qwen-plus",
        "strong": "qwen-plus",
    },
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR_KEY = "__nudge_config_dir"


def load_config(path: str | Path | None = None) -> dict:
    """Load config.toml.

    Precedence: explicit path, NUDGE_CONFIG, repository config.toml.
    """
    if path is None:
        env_path = os.environ.get("NUDGE_CONFIG")
        path = Path(env_path).expanduser() if env_path else PROJECT_ROOT / "config.toml"
    else:
        path = Path(path).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path

    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Create one by copying config.example.toml, or run with --config."
        )
    with open(path, "rb") as f:
        config = tomllib.load(f)
    config[CONFIG_DIR_KEY] = str(path.resolve().parent)
    return config


def resolve_state_dir(config: dict | None = None) -> Path:
    """Resolve the local state directory for databases and runtime logs."""
    configured = os.environ.get("NUDGE_STATE_DIR")
    if configured:
        return Path(configured).expanduser()

    config = config or {}
    state_config = config.get("state", {}) if isinstance(config, dict) else {}
    configured = state_config.get("dir") or state_config.get("directory")
    if configured:
        path = Path(str(configured)).expanduser()
        if path.is_absolute():
            return path
        base = Path(str(config.get(CONFIG_DIR_KEY) or PROJECT_ROOT))
        return base / path

    return PROJECT_ROOT / ".nudge"


def get_family_aliases(config: dict) -> tuple[list[str], dict[str, dict]]:
    """Build alias -> member routing metadata.

    Returns (all_aliases, alias_map).
    """
    alias_map = {}
    all_aliases = []
    for key, member in config.get("family", {}).items():
        if key == "routing":
            continue
        aliases = list(member.get("aliases", []))
        display_name = member.get("display_name") or (aliases[0] if aliases else key)
        cal = member.get("calendar")
        rlist = member.get("reminder_list")
        role = member.get("role")
        for alias in aliases:
            alias_map[alias] = {
                "member_key": key,
                "display_name": display_name,
                "role": role,
                "calendar": cal,
                "reminder_list": rlist,
            }
            all_aliases.append(alias)
    members = get_family_members(config)
    if members:
        group_calendar = _first_configured_value(members, "calendar")
        group_list = _first_configured_value(members, "reminder_list")
        for alias in FAMILY_GROUP_ALIASES:
            alias_map[alias] = {
                "calendar": group_calendar,
                "reminder_list": group_list,
                "family_group": True,
            }
            all_aliases.append(alias)
    return all_aliases, alias_map


def get_family_members(config: dict) -> list[dict]:
    """Return configured family members with stable identity fields."""
    members = []
    for key, member in config.get("family", {}).items():
        if key == "routing":
            continue
        aliases = list(member.get("aliases", []))
        display_name = member.get("display_name") or (aliases[0] if aliases else key)
        members.append({
            "key": key,
            "name": display_name,
            "display_name": display_name,
            "role": member.get("role"),
            "aliases": aliases,
            "calendar": member.get("calendar"),
            "reminder_list": member.get("reminder_list"),
        })
    return members


def get_family_routing(config: dict) -> dict:
    """Return configured family routing rules."""
    family = config.get("family", {})
    routing = family.get("routing", {}) if isinstance(family, dict) else {}
    if not isinstance(routing, dict):
        routing = {}
    display = routing.get("display", {})
    if not isinstance(display, dict):
        display = {}
    threshold = _float_or_default(routing.get("llm_confidence_threshold", 0.65), 0.65)
    rules = routing.get("rules", [])
    return {
        "default": routing.get("default", "all"),
        "llm_fallback": bool(routing.get("llm_fallback", False)),
        "llm_confidence_threshold": threshold,
        "display": {
            "title_prefix": bool(display.get("title_prefix", True)),
            "body_assignee_note": bool(display.get("body_assignee_note", False)),
        },
        "rules": list(rules) if isinstance(rules, list) else [],
    }


def _float_or_default(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_configured_value(items: list[dict], key: str) -> str | None:
    for item in items:
        if item.get(key):
            return item[key]
    return None


def get_defaults(config: dict) -> dict:
    """Get general defaults."""
    return config.get("general", {})


def get_user_profile(config: dict) -> dict:
    """Get user profile section."""
    return config.get("user", {})


def get_calendar_map(config: dict) -> dict:
    """Get calendar name mapping (workout, personal, work)."""
    return config.get("calendars", {})


def get_configured_calendar_names(config: dict) -> list[str]:
    """Collect calendar names that Nudge should query for user context.

    Apple Calendar accounts can contain many subscribed or system calendars.
    Querying all of them is slow and can timeout, so commands that need busy
    context should query only the calendars configured for Nudge.
    """
    names = []

    default_calendar = get_defaults(config).get("default_calendar")
    if default_calendar:
        names.append(default_calendar)

    names.extend(name for name in get_calendar_map(config).values() if name)

    for member in config.get("family", {}).values():
        if member.get("calendar"):
            names.append(member["calendar"])

    unique = []
    seen = set()
    for name in names:
        if name not in seen:
            unique.append(name)
            seen.add(name)
    return unique


def get_reminder_map(config: dict) -> dict:
    """Get reminder list mapping (workout, habits)."""
    return config.get("reminders", {})


def get_llm_config(config: dict) -> dict:
    """Get LLM configuration ([llm] section)."""
    return config.get("llm", {})


def get_apple_backend_config(config: dict, service: str, default_backend: str) -> dict:
    """Return one Apple service adapter config with a stable default backend.

    `config.toml` may omit the whole `[apple]` tree; the runtime must then keep
    the historical local implementation unchanged:

    - Calendar: `native`
    - Reminders: `native`
    - Clock: `shortcuts`

    The returned dict is intentionally small and plain so command modules can
    pass it to backend selectors without depending on TOML layout details.
    """
    apple_config = config.get("apple", {})
    service_config = apple_config.get(service, {}) if isinstance(apple_config, dict) else {}
    result = dict(service_config) if isinstance(service_config, dict) else {}
    result["backend"] = str(result.get("backend", default_backend)).strip().lower()
    return result
