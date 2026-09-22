"""Tests for nudge.commands.do module."""

import json

import pytest
from click.testing import CliRunner

from nudge.apple.adapters import AppleBackends, WriteResult
from nudge.commands.do import (
    _action_to_json,
    _parse_datetime,
    _resolve_target,
    _rewrite_family_group_actions,
    execute_action,
    format_action,
)
from nudge.config import FAMILY_GROUP_PERSON


@pytest.fixture(autouse=True)
def isolate_state_db(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")


class _FailingCalendarBackend:
    shortcut_name = "unused"

    def create_event(self, **kwargs):
        raise AssertionError("invalid family routing must not write Calendar")


class _FailingRemindersBackend:
    def create_reminder(self, **kwargs):
        raise AssertionError("invalid family routing must not write Reminders")


class _UnusedClockBackend:
    shortcut_name = "unused"

    def create_alarm(self, **kwargs):
        return WriteResult(ok=True, message="unused")


class _UnusedNotesBackend:
    def create_note(self, **kwargs):
        return WriteResult(ok=True, message="unused")


class _SuccessfulCalendarBackend:
    shortcut_name = "unused"

    def create_event(self, **kwargs):
        return WriteResult(ok=True, message="uid-123", external_id="Family::uid-123")


class _SuccessfulRemindersBackend:
    def create_reminder(self, **kwargs):
        return WriteResult(ok=True, message="ok", external_id="reminder-123")


def _no_write_backends() -> AppleBackends:
    return AppleBackends(
        calendar=_FailingCalendarBackend(),
        reminders=_FailingRemindersBackend(),
        notes=_UnusedNotesBackend(),
        clock=_UnusedClockBackend(),
    )


def _successful_backends() -> AppleBackends:
    return AppleBackends(
        calendar=_SuccessfulCalendarBackend(),
        reminders=_SuccessfulRemindersBackend(),
        notes=_UnusedNotesBackend(),
        clock=_UnusedClockBackend(),
    )


class TestResolveTarget:
    def test_no_person(self):
        action = {"type": "calendar_event", "summary": "test"}
        cal, rlist = _resolve_target(action, {}, {})
        assert cal == "Personal"
        assert rlist == "Tasks"

    def test_no_person_prefers_configured_defaults(self):
        action = {"type": "calendar_event", "summary": "test"}
        defaults = {"default_calendar": "Family", "default_reminder_list": "家庭"}
        cal, rlist = _resolve_target(action, {}, defaults)
        assert cal == "Family"
        assert rlist == "家庭"

    def test_with_known_person(self):
        action = {"type": "calendar_event", "person": "爸爸"}
        alias_map = {"爸爸": {"calendar": "Dad", "reminder_list": "Dad提醒"}}
        defaults = {"default_calendar": "Family", "default_reminder_list": "Reminders"}
        cal, rlist = _resolve_target(action, alias_map, defaults)
        assert cal == "Dad"
        assert rlist == "Dad提醒"

    def test_with_unknown_person(self):
        action = {"type": "calendar_event", "person": "unknown"}
        alias_map = {"爸爸": {"calendar": "Dad", "reminder_list": "Dad提醒"}}
        defaults = {"default_calendar": "Family", "default_reminder_list": "Reminders"}
        cal, rlist = _resolve_target(action, alias_map, defaults)
        assert cal == "Family"  # falls back to default

    def test_person_none(self):
        action = {"type": "reminder", "person": None}
        defaults = {"default_calendar": "Work", "default_reminder_list": "Work"}
        cal, rlist = _resolve_target(action, {}, defaults)
        assert cal == "Work"


def test_family_group_reminder_expands_to_each_member():
    actions = [
        {
            "type": "reminder",
            "name": "倒垃圾",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]
    family_members = [
        {"name": "爸爸", "reminder_list": "家庭"},
        {"name": "妈妈", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map)

    assert [action["person"] for action in expanded] == ["爸爸", "妈妈"]
    assert [action["name"] for action in expanded] == ["爸爸：倒垃圾", "妈妈：倒垃圾"]


def test_family_group_sentinel_reminder_expands_to_each_member():
    actions = [
        {
            "type": "reminder",
            "name": "倒垃圾",
            "due_date": "2026-05-10 20:00",
            "person": FAMILY_GROUP_PERSON,
        }
    ]
    family_members = [
        {"name": "爸爸", "reminder_list": "家庭"},
        {"name": "妈妈", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map)

    assert [action["person"] for action in expanded] == ["爸爸", "妈妈"]
    assert [action["name"] for action in expanded] == ["爸爸：倒垃圾", "妈妈：倒垃圾"]
    assert all(action["_family_group_alias"] == FAMILY_GROUP_PERSON for action in expanded)


def test_family_group_reminder_routes_course_keyword_to_mom_with_metadata():
    actions = [
        {
            "type": "reminder",
            "name": "科学实验课带材料",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]
    family_members = [
        {"key": "dad", "name": "爸爸", "reminder_list": "家庭"},
        {"key": "mom", "name": "妈妈", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}
    routing = {
        "default": "all",
        "rules": [
            {"id": "kids_courses", "keywords": ["科学实验", "课程"], "assignees": ["mom"]}
        ],
    }

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map, routing)

    assert [action["person"] for action in expanded] == ["妈妈"]
    assert expanded[0]["name"] == "妈妈：科学实验课带材料"
    assert expanded[0]["_family_group_alias"] == "家庭组"
    assert expanded[0]["_family_routing"]["source"] == "keyword"
    assert expanded[0]["_family_routing"]["rule_id"] == "kids_courses"
    assert expanded[0]["_family_routing"]["original_person"] == "家庭组"
    assert expanded[0]["_family_routing"]["assignees"] == ["mom"]


def test_family_group_reminder_can_hide_title_prefix_and_note_assignee_in_body():
    actions = [
        {
            "type": "reminder",
            "name": "科学实验课带材料",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
            "body": "带实验服",
        }
    ]
    family_members = [
        {"key": "dad", "name": "爸爸", "reminder_list": "家庭"},
        {"key": "mom", "name": "李梅", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}
    routing = {
        "default": "all",
        "display": {
            "title_prefix": False,
            "body_assignee_note": True,
        },
        "rules": [
            {"id": "kids_courses", "keywords": ["科学实验"], "assignees": ["mom"]}
        ],
    }

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map, routing)

    assert [action["person"] for action in expanded] == ["李梅"]
    assert expanded[0]["name"] == "科学实验课带材料"
    assert expanded[0]["body"] == "带实验服\n负责人：李梅"


def test_family_group_calendar_event_becomes_two_reminders_for_each_member():
    actions = [
        {
            "type": "calendar_event",
            "summary": "家庭会议",
            "start": "2026-05-10 20:00",
            "end": "2026-05-10 21:00",
            "person": "家庭组",
            "location": "客厅",
        }
    ]
    family_members = [
        {"name": "爸爸", "reminder_list": "家庭"},
        {"name": "妈妈", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map)

    assert [action["type"] for action in expanded] == ["reminder", "reminder", "reminder", "reminder"]
    assert [action["person"] for action in expanded] == ["爸爸", "爸爸", "妈妈", "妈妈"]
    assert [action["due_date"] for action in expanded] == [
        "2026-05-10 19:30",
        "2026-05-10 20:00",
        "2026-05-10 19:30",
        "2026-05-10 20:00",
    ]
    assert [action["name"] for action in expanded] == [
        "爸爸：家庭会议（30 分钟后开始）",
        "爸爸：家庭会议（现在开始）",
        "妈妈：家庭会议（30 分钟后开始）",
        "妈妈：家庭会议（现在开始）",
    ]
    assert all(action["remind_date"] == action["due_date"] for action in expanded)
    assert "地点：客厅" in expanded[0]["body"]


def test_family_group_course_policy_keeps_only_prestart_reminder():
    actions = [{
        "type": "calendar_event",
        "summary": "跆拳道上课",
        "start": "2026-05-10 20:00",
        "end": "2026-05-10 21:00",
        "person": "家庭组",
    }]
    family_members = [{"key": "mom", "name": "妈妈", "reminder_list": "家庭"}]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}
    routing = {
        "default": "all",
        "rules": [{
            "id": "kids_courses",
            "keywords": ["跆拳道"],
            "assignees": ["mom"],
            "notification_policy": "prestart_only",
        }],
    }

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map, routing)

    assert len(expanded) == 1
    assert expanded[0]["due_date"] == "2026-05-10 19:30"
    assert expanded[0]["_family_routing"]["notification_policy"] == "prestart_only"


def test_family_group_pickup_rule_without_policy_keeps_start_reminder():
    actions = [{
        "type": "calendar_event",
        "summary": "接送孩子去机场",
        "start": "2026-05-10 20:00",
        "end": "2026-05-10 21:00",
        "person": "家庭组",
    }]
    family_members = [{"key": "mom", "name": "妈妈", "reminder_list": "家庭"}]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}
    routing = {
        "default": "all",
        "rules": [{"id": "kids_courses", "keywords": ["接送"], "assignees": ["mom"]}],
    }

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map, routing)

    assert [item["due_date"] for item in expanded] == ["2026-05-10 19:30", "2026-05-10 20:00"]


def test_family_group_calendar_event_display_options_apply_to_reminders():
    actions = [
        {
            "type": "calendar_event",
            "summary": "家庭会议",
            "start": "2026-05-10 20:00",
            "end": "2026-05-10 21:00",
            "person": "家庭组",
        }
    ]
    family_members = [
        {"key": "dad", "name": "爸爸", "reminder_list": "家庭"},
        {"key": "mom", "name": "李梅", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}
    routing = {
        "default": "all",
        "display": {
            "title_prefix": False,
            "body_assignee_note": True,
        },
        "rules": [],
    }

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map, routing)

    assert [action["name"] for action in expanded] == [
        "家庭会议（30 分钟后开始）",
        "家庭会议（现在开始）",
        "家庭会议（30 分钟后开始）",
        "家庭会议（现在开始）",
    ]
    assert [action["person"] for action in expanded] == ["爸爸", "爸爸", "李梅", "李梅"]
    assert expanded[0]["body"].endswith("负责人：爸爸")
    assert expanded[2]["body"].endswith("负责人：李梅")


def test_family_group_calendar_event_routes_family_meeting_all_with_metadata():
    actions = [
        {
            "type": "calendar_event",
            "summary": "家庭会议",
            "start": "2026-05-10 20:00",
            "end": "2026-05-10 21:00",
            "person": "家庭组",
        }
    ]
    family_members = [
        {"key": "dad", "name": "爸爸", "reminder_list": "家庭"},
        {"key": "mom", "name": "妈妈", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}
    routing = {
        "default": "mom",
        "rules": [
            {"id": "family_meeting", "keywords": ["家庭会议"], "assignees": "all"}
        ],
    }

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map, routing)

    assert [action["person"] for action in expanded] == ["爸爸", "爸爸", "妈妈", "妈妈"]
    assert [action["due_date"] for action in expanded] == [
        "2026-05-10 19:30",
        "2026-05-10 20:00",
        "2026-05-10 19:30",
        "2026-05-10 20:00",
    ]
    assert all(action["_family_group_alias"] == "家庭组" for action in expanded)
    assert all(action["_family_routing"]["source"] == "keyword" for action in expanded)
    assert all(action["_family_routing"]["rule_id"] == "family_meeting" for action in expanded)
    assert all(action["_family_routing"]["original_person"] == "家庭组" for action in expanded)
    assert all(action["_family_routing"]["assignees"] == ["all"] for action in expanded)


def test_family_group_calendar_event_expanded_actions_have_independent_routing_metadata():
    actions = [
        {
            "type": "calendar_event",
            "summary": "家庭会议",
            "start": "2026-05-10 20:00",
            "end": "2026-05-10 21:00",
            "person": "家庭组",
        }
    ]
    family_members = [
        {"key": "dad", "name": "爸爸", "reminder_list": "家庭"},
        {"key": "mom", "name": "妈妈", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}
    routing = {"default": "all", "rules": []}

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map, routing)

    assert len(expanded) == 4
    assert expanded[0]["_family_routing"] is not expanded[1]["_family_routing"]
    expanded[0]["_family_routing"]["source"] = "mutated"
    assert expanded[1]["_family_routing"]["source"] == "default"


def test_action_to_json_exposes_sanitized_family_routing_metadata():
    action = {
        "type": "reminder",
        "name": "科学实验课带材料",
        "due_date": "2026-05-10 20:00",
        "person": "妈妈",
        "_family_routing": {
            "source": "keyword",
            "rule_id": "kids_courses",
            "original_person": "家庭组",
            "assignees": ["mom", 123],
            "reason": "命中关键词：科学实验",
        },
    }

    item = _action_to_json(
        action,
        1,
        {"妈妈": {"reminder_list": "家庭"}},
        {"default_reminder_list": "日常"},
        "dry_run",
    )

    assert item["routing"] == {
        "source": "keyword",
        "rule_id": "kids_courses",
        "original_person": "家庭组",
        "assignees": ["mom", "123"],
        "reason": "命中关键词：科学实验",
    }
    assert "_family_routing" not in item


def test_action_to_json_sanitizes_non_string_invalid_assignees_for_json_output():
    action = {
        "type": "reminder",
        "name": "倒垃圾",
        "due_date": "2026-05-10 20:00",
        "person": "家庭组",
        "_family_routing": {
            "source": "keyword_invalid",
            "rule_id": "broken",
            "original_person": "家庭组",
            "assignees": [],
            "reason": "keyword rule has invalid assignees",
            "invalid_assignees": [{"name": "grandma", "rank": 1}],
            "confidence": float("nan"),
        },
    }

    item = _action_to_json(
        action,
        1,
        {"家庭组": {"reminder_list": "家庭", "family_group": True}},
        {"default_reminder_list": "日常"},
        "failed",
    )

    assert item["routing"]["invalid_assignees"] == ['{"name": "grandma", "rank": 1}']
    assert item["routing"]["confidence"] == "nan"
    json.dumps(item)


def test_action_to_json_includes_llm_confidence_for_fallback_metadata():
    action = {
        "type": "reminder",
        "name": "倒垃圾",
        "due_date": "2026-05-10 20:00",
        "person": "家庭组",
        "_family_routing": {
            "source": "default",
            "rule_id": None,
            "original_person": "家庭组",
            "assignees": ["dad", "mom"],
            "reason": "低置信 LLM 后使用默认路由",
            "llm_error": "low_confidence",
            "llm_confidence": 0.4,
        },
    }

    item = _action_to_json(
        action,
        1,
        {"家庭组": {"reminder_list": "家庭", "family_group": True}},
        {"default_reminder_list": "日常"},
        "dry_run",
    )

    assert item["routing"]["llm_confidence"] == 0.4
    json.dumps(item)


def test_action_to_json_sanitizes_non_finite_and_string_llm_confidence():
    action = {
        "type": "reminder",
        "name": "倒垃圾",
        "due_date": "2026-05-10 20:00",
        "person": "家庭组",
        "_family_routing": {
            "source": "default",
            "rule_id": None,
            "original_person": "家庭组",
            "assignees": ["dad", "mom"],
            "reason": "LLM 置信度不可用，使用默认路由",
            "llm_error": "non_finite_confidence",
            "llm_confidence": "NaN",
            "confidence": float("inf"),
        },
    }

    item = _action_to_json(
        action,
        1,
        {"家庭组": {"reminder_list": "家庭", "family_group": True}},
        {"default_reminder_list": "日常"},
        "dry_run",
    )

    assert item["routing"]["llm_confidence"] == "NaN"
    assert item["routing"]["confidence"] == "inf"
    json.dumps(item, allow_nan=False)


def test_rewrite_family_group_actions_uses_llm_router_when_enabled():
    calls = []
    actions = [
        {
            "type": "reminder",
            "name": "买材料",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]
    family_members = [
        {"key": "dad", "name": "爸爸", "reminder_list": "家庭"},
        {"key": "mom", "name": "妈妈", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}
    routing = {"default": "all", "llm_fallback": True, "rules": []}

    def router(action, members, routing_arg):
        calls.append((action, members, routing_arg))
        return {"assignees": ["mom"], "confidence": 0.9, "reason": "妈妈处理"}

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map, routing, llm_router=router)

    assert len(calls) == 1
    assert [action["person"] for action in expanded] == ["妈妈"]
    assert expanded[0]["_family_routing"]["source"] == "llm"
    assert expanded[0]["_family_routing"]["confidence"] == 0.9


def test_do_json_llm_fallback_routes_family_group_to_mom(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
        "family": {
            "dad": {"aliases": ["爸爸"], "calendar": "个人", "reminder_list": "家庭"},
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {"default": "all", "llm_fallback": True, "rules": []},
        },
    }
    actions = [
        {
            "type": "reminder",
            "name": "买材料",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]
    llm_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.commands.do.suggest_family_routing",
        lambda action, members, routing: llm_calls.append(action) or {
            "assignees": ["mom"],
            "confidence": 0.9,
            "reason": "妈妈处理",
        },
    )

    result = CliRunner().invoke(cli, ["do", "--json", "--dry-run", "提醒家庭组买材料"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(llm_calls) == 1
    assert payload["total"] == 1
    assert payload["actions"][0]["person"] == "妈妈"
    assert payload["actions"][0]["routing"]["source"] == "llm"
    assert payload["actions"][0]["routing"]["confidence"] == 0.9


def test_do_json_llm_fallback_disabled_does_not_call_router(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
        "family": {
            "dad": {"aliases": ["爸爸"], "calendar": "个人", "reminder_list": "家庭"},
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {"default": "all", "llm_fallback": False, "rules": []},
        },
    }
    actions = [
        {
            "type": "reminder",
            "name": "买材料",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.commands.do.suggest_family_routing",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM fallback disabled")),
    )

    result = CliRunner().invoke(cli, ["do", "--json", "--dry-run", "提醒家庭组买材料"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 2
    assert [action["person"] for action in payload["actions"]] == ["爸爸", "妈妈"]
    assert all(action["routing"]["source"] == "default" for action in payload["actions"])


def test_do_json_keyword_route_does_not_call_llm_even_when_enabled(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
        "family": {
            "dad": {"aliases": ["爸爸"], "calendar": "个人", "reminder_list": "家庭"},
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {
                "default": "all",
                "llm_fallback": True,
                "rules": [{"id": "kids_courses", "keywords": ["科学实验"], "assignees": ["mom"]}],
            },
        },
    }
    actions = [
        {
            "type": "reminder",
            "name": "科学实验课带材料",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.commands.do.suggest_family_routing",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("keyword route should skip LLM")),
    )

    result = CliRunner().invoke(cli, ["do", "--json", "--dry-run", "科学实验课带材料"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 1
    assert payload["actions"][0]["person"] == "妈妈"
    assert payload["actions"][0]["routing"]["source"] == "keyword"


def test_do_family_group_calendar_event_writes_reminders_not_calendar(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
        "family": {
            "dad": {"aliases": ["爸爸"], "calendar": "个人", "reminder_list": "家庭"},
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
        },
    }
    actions = [
        {
            "type": "calendar_event",
            "summary": "家庭会议",
            "start": "2026-05-10 20:00",
            "end": "2026-05-10 21:00",
            "person": "家庭组",
        }
    ]
    reminder_calls = []
    log_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("family group event must not write Calendar")),
    )
    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: reminder_calls.append(kwargs) or (True, "reminder-id"),
    )
    monkeypatch.setattr("nudge.commands.do.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(cli, ["do", "全家明晚8点开会"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    assert "Done. (4/4 succeeded)" in result.output
    assert [call["list_name"] for call in reminder_calls] == ["家庭", "家庭", "家庭", "家庭"]
    assert [call["due_date"].strftime("%Y-%m-%d %H:%M") for call in reminder_calls] == [
        "2026-05-10 19:30",
        "2026-05-10 20:00",
        "2026-05-10 19:30",
        "2026-05-10 20:00",
    ]
    assert all(call["remind_date"] == call["due_date"] for call in reminder_calls)
    assert [call["action_type"] for call in log_calls] == ["reminder", "reminder", "reminder", "reminder"]


def test_specific_family_member_reminder_does_not_expand():
    actions = [
        {
            "type": "reminder",
            "name": "带药",
            "due_date": "2026-05-10 20:00",
            "person": "妈妈",
        }
    ]
    family_members = [
        {"name": "爸爸", "reminder_list": "家庭"},
        {"name": "妈妈", "reminder_list": "家庭"},
    ]
    alias_map = {"妈妈": {"reminder_list": "家庭"}}

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map)

    assert expanded == actions


def test_family_group_invalid_routing_does_not_expand_to_all_and_keeps_metadata():
    actions = [
        {
            "type": "reminder",
            "name": "科学实验课带材料",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]
    family_members = [
        {"key": "dad", "name": "爸爸", "reminder_list": "家庭"},
        {"key": "mom", "name": "妈妈", "reminder_list": "家庭"},
    ]
    alias_map = {"家庭组": {"reminder_list": "家庭", "family_group": True}}
    routing = {
        "default": "all",
        "rules": [
            {"id": "broken_courses", "keywords": ["科学实验"], "assignees": ["grandma"]}
        ],
    }

    expanded = _rewrite_family_group_actions(actions, family_members, alias_map, routing)

    assert len(expanded) == 1
    assert expanded[0]["person"] == "家庭组"
    assert expanded[0]["name"] == "科学实验课带材料"
    assert expanded[0]["_family_group_alias"] == "家庭组"
    assert expanded[0]["_family_routing"]["source"] == "keyword_invalid"
    assert expanded[0]["_family_routing"]["rule_id"] == "broken_courses"
    assert expanded[0]["_family_routing"]["original_person"] == "家庭组"
    assert expanded[0]["_family_routing"]["assignees"] == []
    assert expanded[0]["_family_routing"]["invalid_assignees"] == ["grandma"]


def test_execute_action_blocks_invalid_family_routing_before_apple_write(capsys):
    action = {
        "type": "reminder",
        "name": "科学实验课带材料",
        "due_date": "2026-05-10 20:00",
        "person": "家庭组",
        "_family_routing": {
            "source": "keyword_invalid",
            "rule_id": "broken_courses",
            "original_person": "家庭组",
            "assignees": [],
            "invalid_assignees": ["grandma"],
            "reason": "keyword rule has invalid assignees",
        },
    }

    ok = execute_action(
        action,
        {"家庭组": {"reminder_list": "家庭", "family_group": True}},
        {"default_reminder_list": "日常"},
        quiet=False,
        apple_backends=_no_write_backends(),
    )

    assert ok is False
    assert action["_error"].code == "FAMILY_ROUTING_INVALID"
    captured = capsys.readouterr()
    assert "FAMILY_ROUTING_INVALID" in captured.err
    assert "家庭组路由无效" in captured.err


def test_execute_action_blocks_invalid_family_calendar_route_before_calendar_write():
    action = {
        "type": "calendar_event",
        "summary": "家庭会议",
        "start": "2026-05-10 20:00",
        "end": "2026-05-10 21:00",
        "person": "家庭组",
        "_family_routing": {
            "source": "default_invalid",
            "rule_id": None,
            "original_person": "家庭组",
            "assignees": [],
            "reason": "default route has no valid assignees",
        },
    }

    ok = execute_action(
        action,
        {"家庭组": {"calendar": "家庭日历", "family_group": True}},
        {"default_calendar": "个人"},
        quiet=True,
        apple_backends=_no_write_backends(),
    )

    assert ok is False
    assert action["_error"].code == "FAMILY_ROUTING_INVALID"


def test_do_invalid_family_group_routing_does_not_write_reminders(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
        "family": {
            "dad": {"aliases": ["爸爸"], "calendar": "个人", "reminder_list": "家庭"},
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {
                "default": "all",
                "rules": [
                    {"id": "broken_courses", "keywords": ["科学实验"], "assignees": ["grandma"]}
                ],
            },
        },
    }
    actions = [
        {
            "type": "reminder",
            "name": "科学实验课带材料",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("invalid routing must not write Reminders")),
    )

    result = CliRunner().invoke(cli, ["do", "科学实验课带材料"], prog_name="nudge")

    assert result.exit_code == 1
    assert "FAMILY_ROUTING_INVALID" in result.output
    assert "Done. (0/1 succeeded)" in result.output


def test_do_json_invalid_family_group_routing_reports_failure(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
        "family": {
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {
                "default": "unknown",
                "rules": [],
            },
        },
    }
    actions = [
        {
            "type": "reminder",
            "name": "倒垃圾",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("invalid routing must not write Reminders")),
    )

    result = CliRunner().invoke(cli, ["do", "--json", "提醒全家倒垃圾"], prog_name="nudge")

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["succeeded"] == 0
    assert payload["actions"][0]["status"] == "failed"
    assert payload["actions"][0]["routing"]["source"] == "default_invalid"
    assert payload["actions"][0]["routing"]["invalid_assignees"] == ["unknown"]
    assert payload["failures"][0]["error_code"] == "FAMILY_ROUTING_INVALID"
    assert payload["errors"][0]["code"] == "FAMILY_ROUTING_INVALID"


def test_do_invalid_family_group_calendar_route_does_not_write_calendar(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
        "family": {
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {
                "default": "unknown",
                "rules": [],
            },
        },
    }
    actions = [
        {
            "type": "calendar_event",
            "summary": "家庭会议",
            "start": "2026-05-10 20:00",
            "end": "2026-05-10 21:00",
            "person": "家庭组",
        }
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("invalid routing must not write Calendar")),
    )
    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("invalid routing must not write Reminders")),
    )

    result = CliRunner().invoke(cli, ["do", "全家明晚8点开会"], prog_name="nudge")

    assert result.exit_code == 1
    assert "FAMILY_ROUTING_INVALID" in result.output
    assert "Done. (0/1 succeeded)" in result.output


class TestParseDatetime:
    def test_valid_datetime(self):
        dt = _parse_datetime("2026-04-14 10:30", "start")
        assert dt.year == 2026
        assert dt.month == 4
        assert dt.hour == 10
        assert dt.minute == 30

    def test_invalid_format(self):
        from click import ClickException
        with pytest.raises(ClickException, match="Invalid start"):
            _parse_datetime("not-a-date", "start")

    def test_none_value(self):
        from click import ClickException
        with pytest.raises(ClickException):
            _parse_datetime(None, "due date")


class TestFormatAction:
    def test_calendar_event(self):
        action = {
            "type": "calendar_event",
            "summary": "Meeting",
            "start": "2026-04-14 10:00",
            "end": "2026-04-14 11:00",
            "person": None,
            "location": "Office",
        }
        result = format_action(action, 1, {}, {"default_calendar": "Work"})
        assert "[CALENDAR]" in result
        assert "Meeting" in result
        assert "Office" in result
        assert "Work" in result

    def test_reminder(self):
        action = {
            "type": "reminder",
            "name": "Buy milk",
            "due_date": "2026-04-14 18:00",
            "person": None,
        }
        result = format_action(action, 1, {}, {"default_reminder_list": "Groceries"})
        assert "[REMINDER]" in result
        assert "Buy milk" in result
        assert "Groceries" in result

    def test_alarm(self):
        action = {"type": "alarm", "time": "07:00", "label": "Wake up"}
        result = format_action(action, 1, {}, {})
        assert "[ALARM]" in result
        assert "07:00" in result

    def test_calendar_with_person(self):
        action = {
            "type": "calendar_event",
            "summary": "Dentist",
            "start": "2026-04-14 14:00",
            "end": "2026-04-14 15:00",
            "person": "爸爸",
        }
        alias_map = {"爸爸": {"calendar": "Dad", "reminder_list": "R"}}
        result = format_action(action, 1, alias_map, {"default_calendar": "Family"})
        assert "Dad" in result
        assert "爸爸" in result


def test_root_cli_e2e_parses_and_writes_calendar_and_reminder(monkeypatch):
    """Mock E2E: root CLI message -> LLM parse -> Apple writers -> SQLite log."""
    from click.testing import CliRunner

    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "Family", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
        "family": {
            "dad": {"aliases": ["爸爸"], "calendar": "Family", "reminder_list": "家庭"}
        },
    }
    actions = [
        {
            "type": "calendar_event",
            "summary": "看牙医",
            "start": "2026-04-26 14:00",
            "end": "2026-04-26 15:00",
            "person": "爸爸",
        },
        {
            "type": "reminder",
            "name": "买菜",
            "due_date": "2026-04-26 18:00",
        },
    ]
    calendar_calls = []
    reminder_calls = []
    log_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: calendar_calls.append(kwargs) or (True, "event-id"),
    )
    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: reminder_calls.append(kwargs) or (True, "reminder-id"),
    )
    monkeypatch.setattr(
        "nudge.commands.do.log_action",
        lambda **kwargs: log_calls.append(kwargs),
    )

    result = CliRunner().invoke(cli, ["爸爸明天下午2点看牙医，提醒我傍晚买菜"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    assert 'Parsing: 爸爸明天下午2点看牙医，提醒我傍晚买菜' in result.output
    assert '[CALENDAR] "看牙医" for 爸爸' in result.output
    assert '[REMINDER] "买菜"' in result.output
    assert "Done. (2/2 succeeded)" in result.output
    assert calendar_calls == [
        {
            "summary": "看牙医",
            "start": _parse_datetime("2026-04-26 14:00", "expected start"),
            "end": _parse_datetime("2026-04-26 15:00", "expected end"),
            "calendar_name": "Family",
            "location": None,
            "notes": None,
        }
    ]
    assert reminder_calls == [
        {
            "name": "买菜",
            "due_date": _parse_datetime("2026-04-26 18:00", "expected due"),
            "list_name": "日常",
            "body": None,
            "priority": 0,
            "remind_date": _parse_datetime("2026-04-26 18:00", "expected remind"),
            "notify": True,
            "external_id": reminder_calls[0]["external_id"],
        }
    ]
    assert reminder_calls[0]["external_id"].startswith("nudge://reminder/")
    assert log_calls == [
        {
            "action_type": "calendar_event",
            "summary": "看牙医",
            "scheduled_at": "2026-04-26 14:00",
            "external_id": "Family::event-id",
            "reminder_list": None,
        },
        {
            "action_type": "reminder",
            "summary": "买菜",
            "scheduled_at": "2026-04-26 18:00",
            "external_id": reminder_calls[0]["external_id"],
            "reminder_list": "日常",
        },
    ]


def test_do_normalizes_reminder_title_before_display_write_and_log(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "Family", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
    }
    actions = [
        {
            "type": "reminder",
            "name": "[Nudge Liver W1] 晨起称重 + 睡眠记录 2026-04-27",
            "due_date": "2026-04-27 06:40",
        }
    ]
    reminder_calls = []
    log_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: reminder_calls.append(kwargs) or (True, "reminder-id"),
    )
    monkeypatch.setattr("nudge.commands.do.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(cli, ["提醒我晨起称重"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    assert '[REMINDER] "[Nudge Liver W1] 晨起称重 + 睡眠记录"' in result.output
    assert "2026-04-27\"" not in result.output
    assert reminder_calls[0]["name"] == "[Nudge Liver W1] 晨起称重 + 睡眠记录"
    assert log_calls[0]["summary"] == "[Nudge Liver W1] 晨起称重 + 睡眠记录"


def test_do_partial_write_returns_nonzero_and_logs_only_success(monkeypatch):
    """Partial Apple write failure should be explicit and non-zero."""
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "Family", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
    }
    actions = [
        {
            "type": "calendar_event",
            "summary": "成功会议",
            "start": "2026-04-26 14:00",
            "end": "2026-04-26 15:00",
        },
        {
            "type": "calendar_event",
            "summary": "失败会议",
            "start": "2026-04-26 16:00",
            "end": "2026-04-26 17:00",
        },
    ]
    log_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (
            (True, "uid-ok")
            if kwargs["summary"] == "成功会议"
            else (False, 'Can’t get calendar "Family".')
        ),
    )
    monkeypatch.setattr("nudge.commands.do.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(cli, ["安排两个会议"], prog_name="nudge")

    assert result.exit_code == 1
    assert "Done. (1/2 succeeded)" in result.output
    assert "部分 action 写入失败" in result.output
    assert "不要直接整条重试" in result.output
    assert "目标 Calendar 不存在：Family" in result.output
    assert log_calls == [
        {
            "action_type": "calendar_event",
            "summary": "成功会议",
            "scheduled_at": "2026-04-26 14:00",
            "external_id": "Family::uid-ok",
            "reminder_list": None,
        }
    ]


def test_do_llm_invalid_json_returns_actionable_error(monkeypatch):
    """LLM JSON failures should tell the caller what to do next."""
    from nudge.brain import NudgeBrainError
    from nudge.cli import cli

    config = {"general": {}, "llm": {"provider": "qwen"}}

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr(
        "nudge.commands.do.parse_actions",
        lambda text, aliases: (_ for _ in ()).throw(
            NudgeBrainError("LLM returned invalid JSON after retry: nope")
        ),
    )

    result = CliRunner().invoke(cli, ["明天下午3点开会"], prog_name="nudge")

    assert result.exit_code == 1
    assert "LLM 返回了无效 JSON" in result.output
    assert "docs/PROMPT_PLAYBOOK.md" in result.output
    assert "nudge --dry-run" in result.output


def test_do_invalid_action_schema_returns_actionable_error(monkeypatch):
    """Valid JSON with missing action fields should fail before writing anything."""
    from nudge.cli import cli

    config = {"general": {}, "llm": {"provider": "qwen"}}

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr(
        "nudge.commands.do.parse_actions",
        lambda text, aliases: [{"type": "calendar_event", "summary": "缺少结束时间", "start": "2026-04-26 14:00"}],
    )
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not write Apple Calendar")),
    )

    result = CliRunner().invoke(cli, ["明天下午3点开会"], prog_name="nudge")

    assert result.exit_code == 1
    assert "LLM JSON 结构不符合 action schema" in result.output
    assert "missing fields: end" in result.output


def test_do_json_dry_run_outputs_only_machine_readable_json(monkeypatch):
    """JSON dry-run should be stable stdout and should not write Apple apps."""
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "Family", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
    }
    actions = [
        {
            "type": "calendar_event",
            "summary": "项目会",
            "start": "2026-04-26 14:00",
            "end": "2026-04-26 15:00",
        }
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not write")),
    )

    result = CliRunner().invoke(cli, ["do", "--json", "--dry-run", "明天下午2点项目会"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["total"] == 1
    assert payload["succeeded"] == 0
    assert payload["failures"] == []
    assert payload["errors"] == []
    assert payload["actions"][0]["status"] == "dry_run"
    assert payload["actions"][0]["target"] == {"kind": "Calendar", "name": "Family"}
    assert "Parsing:" not in result.output


def test_do_reminder_dry_run_shows_effective_default_notification(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
    }
    actions = [{
        "type": "reminder",
        "name": "准备发布",
        "due_date": "2026-07-13 09:00",
        "remind_date": None,
    }]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)

    text_result = CliRunner().invoke(cli, ["do", "--dry-run", "提醒我准备发布"], prog_name="nudge")
    json_result = CliRunner().invoke(cli, ["do", "--json", "--dry-run", "提醒我准备发布"], prog_name="nudge")

    assert text_result.exit_code == 0, text_result.output
    assert "Remind: 2026-07-13 09:00" in text_result.output
    payload = json.loads(json_result.output)
    assert payload["actions"][0]["notify"] is True
    assert payload["actions"][0]["remind_at"] == "2026-07-13 09:00"


def test_do_reminder_notify_false_keeps_due_date_without_notification(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
    }
    actions = [{
        "type": "reminder",
        "name": "仅作截止记录",
        "due_date": "2026-07-13 09:00",
        "remind_date": None,
        "notify": False,
    }]
    calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: calls.append(kwargs) or (True, "reminder-id"),
    )

    dry_run = CliRunner().invoke(cli, ["do", "--json", "--dry-run", "只记截止时间"], prog_name="nudge")
    real_run = CliRunner().invoke(cli, ["do", "--json", "只记截止时间"], prog_name="nudge")

    assert dry_run.exit_code == 0, dry_run.output
    dry_payload = json.loads(dry_run.output)
    assert dry_payload["actions"][0]["notify"] is False
    assert dry_payload["actions"][0]["remind_at"] is None
    assert real_run.exit_code == 0, real_run.output
    assert calls[0]["notify"] is False
    assert calls[0]["remind_date"] is None


def test_do_json_dry_run_includes_keyword_family_routing_metadata(monkeypatch):
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "llm": {"provider": "qwen"},
        "family": {
            "dad": {"aliases": ["爸爸"], "calendar": "个人", "reminder_list": "家庭"},
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {
                "default": "all",
                "rules": [
                    {"id": "kids_courses", "keywords": ["科学实验"], "assignees": ["mom"]}
                ],
            },
        },
    }
    actions = [
        {
            "type": "reminder",
            "name": "科学实验课带材料",
            "due_date": "2026-05-10 20:00",
            "person": "家庭组",
        }
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)

    result = CliRunner().invoke(cli, ["do", "--json", "--dry-run", "科学实验课带材料"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["actions"][0]["routing"] == {
        "source": "keyword",
        "rule_id": "kids_courses",
        "original_person": "家庭组",
        "assignees": ["mom"],
        "reason": "命中关键词：科学实验",
    }


def test_root_cli_json_option_routes_to_do_command(monkeypatch):
    """`nudge --json "..."` should be valid for external callers."""
    from nudge.cli import cli

    config = {"general": {"default_calendar": "Family"}, "llm": {"provider": "qwen"}}
    actions = [
        {
            "type": "calendar_event",
            "summary": "项目会",
            "start": "2026-04-26 14:00",
            "end": "2026-04-26 15:00",
        }
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)

    result = CliRunner().invoke(cli, ["--json", "--dry-run", "明天下午2点项目会"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["actions"][0]["summary"] == "项目会"


def test_do_json_real_write_reports_success(monkeypatch):
    """JSON real write should report external ids and log successful actions."""
    from nudge.cli import cli

    config = {"general": {"default_calendar": "Family"}, "llm": {"provider": "qwen"}}
    actions = [
        {
            "type": "calendar_event",
            "summary": "项目会",
            "start": "2026-04-26 14:00",
            "end": "2026-04-26 15:00",
        }
    ]
    log_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr("nudge.apple.adapters.create_calendar_event", lambda **kwargs: (True, "uid-123"))
    monkeypatch.setattr("nudge.commands.do.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(cli, ["do", "--json", "明天下午2点项目会"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    assert payload["total"] == 1
    assert payload["succeeded"] == 1
    assert payload["actions"][0]["status"] == "succeeded"
    assert payload["actions"][0]["external_id"] == "Family::uid-123"
    assert payload["failures"] == []
    assert payload["errors"] == []
    assert log_calls == [
        {
            "action_type": "calendar_event",
            "summary": "项目会",
            "scheduled_at": "2026-04-26 14:00",
            "external_id": "Family::uid-123",
            "reminder_list": None,
        }
    ]


def test_do_config_state_dir_writes_action_log_to_configured_state_dir(monkeypatch, tmp_path):
    """`nudge do --config` should use that config's [state].dir for action logs."""
    from nudge.cli import cli
    from nudge.state import get_actions

    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)

    default_state_dir = tmp_path / "default-state"
    configured_state_dir = tmp_path / "configured-state"
    config_path = tmp_path / "custom.toml"
    config = {
        "general": {"default_calendar": "Family"},
        "llm": {"provider": "qwen"},
        "state": {"dir": str(configured_state_dir)},
    }
    actions = [
        {
            "type": "calendar_event",
            "summary": "项目会",
            "start": "2026-04-26 14:00",
            "end": "2026-04-26 15:00",
        }
    ]

    monkeypatch.setattr("nudge.state.STATE_DIR", default_state_dir)
    monkeypatch.setattr("nudge.state.DB_PATH", default_state_dir / "nudge.db")
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr("nudge.commands.do.resolve_apple_backends", lambda cfg: _successful_backends())

    result = CliRunner().invoke(
        cli,
        ["do", "--config", str(config_path), "--json", "明天下午2点项目会"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert not (default_state_dir / "nudge.db").exists()
    assert (configured_state_dir / "nudge.db").exists()
    actions = get_actions()
    assert [action["summary"] for action in actions] == ["项目会"]


def test_do_json_partial_failure_returns_nonzero_json_payload(monkeypatch):
    """JSON partial failure should keep stdout parseable and exit non-zero."""
    from nudge.cli import cli

    config = {"general": {"default_calendar": "Family"}, "llm": {"provider": "qwen"}}
    actions = [
        {
            "type": "calendar_event",
            "summary": "成功会议",
            "start": "2026-04-26 14:00",
            "end": "2026-04-26 15:00",
        },
        {
            "type": "calendar_event",
            "summary": "失败会议",
            "start": "2026-04-26 16:00",
            "end": "2026-04-26 17:00",
        },
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (
            (True, "uid-ok")
            if kwargs["summary"] == "成功会议"
            else (False, 'Can’t get calendar "Family".')
        ),
    )
    monkeypatch.setattr("nudge.commands.do.log_action", lambda **kwargs: None)

    result = CliRunner().invoke(cli, ["do", "--json", "安排两个会议"], prog_name="nudge")

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert payload["total"] == 2
    assert payload["succeeded"] == 1
    assert payload["actions"][0]["status"] == "succeeded"
    assert payload["actions"][1]["status"] == "failed"
    assert payload["failures"] == [
        {
            "index": 2,
            "summary": "失败会议",
            "error_code": "APPLE_TARGET_NOT_FOUND",
            "error": "目标 Calendar 不存在：Family",
        }
    ]
    assert payload["errors"][0]["code"] == "APPLE_TARGET_NOT_FOUND"
    assert "部分 action 写入失败" not in result.output


def test_do_json_llm_error_returns_nonzero_json_payload(monkeypatch):
    """JSON parse failure should still produce machine-readable stdout."""
    from nudge.brain import NudgeBrainError
    from nudge.cli import cli

    config = {"general": {}, "llm": {"provider": "qwen"}}
    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr(
        "nudge.commands.do.parse_actions",
        lambda text, aliases: (_ for _ in ()).throw(
            NudgeBrainError("LLM returned invalid JSON after retry: nope")
        ),
    )

    result = CliRunner().invoke(cli, ["do", "--json", "明天下午3点开会"], prog_name="nudge")

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert payload["total"] == 0
    assert payload["succeeded"] == 0
    assert payload["actions"] == []
    assert payload["failures"] == []
    assert payload["errors"][0]["code"] == "LLM_INVALID_JSON"


def test_do_json_unsupported_backend_returns_machine_readable_error(monkeypatch):
    """Unsupported Apple backend config should fail before writes with JSON output."""
    from nudge.cli import cli

    config = {
        "general": {"default_calendar": "Family"},
        "llm": {"provider": "qwen"},
        "apple": {"calendar": {"backend": "ical"}},
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr(
        "nudge.commands.do.parse_actions",
        lambda text, aliases: (_ for _ in ()).throw(AssertionError("backend should be validated before parse/write")),
    )

    result = CliRunner().invoke(cli, ["do", "--json", "明天下午2点项目会"], prog_name="nudge")

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "APPLE_BACKEND_UNSUPPORTED"
    assert "ical" in payload["errors"][0]["raw_error"]


def test_do_json_invalid_datetime_returns_schema_error_without_writes(monkeypatch):
    """Invalid executable datetime should stay inside the JSON error contract."""
    from nudge.cli import cli

    config = {"general": {"default_calendar": "Family"}, "llm": {"provider": "qwen"}}
    actions = [
        {
            "type": "calendar_event",
            "summary": "坏时间会议",
            "start": "tomorrow 9am",
            "end": "tomorrow 10am",
        }
    ]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("invalid date must not write")),
    )

    result = CliRunner().invoke(cli, ["do", "--json", "安排坏时间会议"], prog_name="nudge")

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "LLM_ACTION_SCHEMA_INVALID"
    assert "Invalid start time format" in payload["errors"][0]["detail"]


def test_do_json_missing_input_file_returns_machine_readable_error():
    """Preflight file read errors should not break --json consumers."""
    from nudge.cli import cli

    result = CliRunner().invoke(cli, ["do", "--json", "--file", "missing-input.txt"], prog_name="nudge")

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "CLI_INPUT_ERROR"
    assert "missing-input.txt" in payload["errors"][0]["detail"]


def test_do_alarm_writes_clock_shortcut_and_logs_action(monkeypatch):
    """Alarm actions should run the Clock Shortcuts bridge instead of staying manual."""
    from nudge.cli import cli

    config = {
        "general": {},
        "llm": {"provider": "qwen"},
        "apple": {"clock": {"backend": "shortcuts", "shortcut_name": "Nudge Test Alarm"}},
    }
    actions = [{"type": "alarm", "time": "07:00", "label": "晨起称重"}]
    calls = []
    log_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_alarm",
        lambda time, label, shortcut_name: calls.append((time, label, shortcut_name)) or (True, "Clock::Nudge Test Alarm::07:00::晨起称重"),
    )
    monkeypatch.setattr("nudge.commands.do.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(cli, ["do", "明天早上7点提醒我晨起称重"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    assert calls == [("07:00", "晨起称重", "Nudge Test Alarm")]
    assert "Done. (1/1 succeeded)" in result.output
    assert "请手动设置" not in result.output
    assert log_calls == [
        {
            "action_type": "alarm",
            "summary": "晨起称重",
            "scheduled_at": "07:00",
            "external_id": "Clock::Nudge Test Alarm::07:00::晨起称重",
            "reminder_list": None,
        }
    ]


def test_do_alarm_shortcut_failure_returns_actionable_error(monkeypatch):
    """Missing Clock shortcut should be explicit and non-zero."""
    from nudge.cli import cli

    config = {
        "general": {},
        "llm": {"provider": "qwen"},
        "apple": {"clock": {"backend": "shortcuts", "shortcut_name": "Nudge Test Alarm"}},
    }
    actions = [{"type": "alarm", "time": "07:00", "label": "晨起称重"}]

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda p=None: config)
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda text, aliases: actions)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_alarm",
        lambda time, label, shortcut_name: (False, f'Shortcut "{shortcut_name}" was not found.'),
    )
    monkeypatch.setattr(
        "nudge.commands.do.log_action",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("failed alarm must not be logged")),
    )

    result = CliRunner().invoke(cli, ["do", "明天早上7点提醒我晨起称重"], prog_name="nudge")

    assert result.exit_code == 1
    assert "CLOCK_SHORTCUT_MISSING" in result.output
    assert "Clock Shortcut 不存在：Nudge Test Alarm" in result.output
    assert "Nudge Test Alarm" in result.output
    assert "shortcuts run" in result.output
