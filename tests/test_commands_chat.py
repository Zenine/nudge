"""Tests for nudge.commands.chat — action extraction and JSON stripping."""

from click.testing import CliRunner

from nudge.commands import chat
from nudge.commands.chat import _extract_actions, _strip_json_blocks


class TestExtractActions:
    def test_single_action(self):
        text = '好的！```json\n[{"type": "calendar_event", "summary": "开会"}]\n```\n已创建。'
        actions = _extract_actions(text)
        assert len(actions) == 1
        assert actions[0]["type"] == "calendar_event"

    def test_no_json(self):
        assert _extract_actions("普通回复，没有 JSON") == []

    def test_multiple_actions(self):
        text = '```json\n[{"type": "calendar_event"}, {"type": "reminder"}]\n```'
        actions = _extract_actions(text)
        assert len(actions) == 2

    def test_invalid_json_ignored(self):
        text = '```json\n{invalid}\n```'
        assert _extract_actions(text) == []


class TestStripJsonBlocks:
    def test_strip(self):
        text = '好的！```json\n[{"type": "x"}]\n```\n已创建。'
        clean = _strip_json_blocks(text)
        assert "```" not in clean
        assert "已创建" in clean

    def test_no_json(self):
        assert _strip_json_blocks("普通文本") == "普通文本"


def test_chat_family_group_event_writes_reminders_not_calendar(monkeypatch):
    from nudge.commands.chat import chat_command

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "family": {
            "dad": {"aliases": ["爸爸"], "calendar": "个人", "reminder_list": "家庭"},
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
        },
    }
    response = """安排好了。
```json
[{"type":"calendar_event","summary":"家庭会议","start":"2026-05-10 20:00","end":"2026-05-10 21:00","person":"家庭组"}]
```"""
    executed = []
    logged = []

    monkeypatch.setattr(chat, "_build_context", lambda: {
        "current_datetime": "2026-05-09 17:00 (Saturday)",
        "events": "",
        "reminders": "",
        "actions": "",
        "habits": "",
    })
    monkeypatch.setattr(chat, "call_llm", lambda system, prompt, task="default": response)
    monkeypatch.setattr("nudge.config.load_config", lambda: config)
    monkeypatch.setattr("nudge.apple.adapters.resolve_apple_backends", lambda config: object())
    monkeypatch.setattr(
        "nudge.commands.do.execute_action",
        lambda action, alias_map, defaults, apple_backends=None: executed.append(action) or True,
    )
    monkeypatch.setattr("nudge.state.log_action", lambda **kwargs: logged.append(kwargs))

    result = CliRunner().invoke(chat_command, input="全家明晚8点开会\ny\nexit\n")

    assert result.exit_code == 0, result.output
    assert "检测到 4 个待创建项" in result.output
    assert [action["type"] for action in executed] == ["reminder", "reminder", "reminder", "reminder"]
    assert [action["person"] for action in executed] == ["爸爸", "爸爸", "妈妈", "妈妈"]
    assert [action["due_date"] for action in executed] == [
        "2026-05-10 19:30",
        "2026-05-10 20:00",
        "2026-05-10 19:30",
        "2026-05-10 20:00",
    ]
    assert [item["action_type"] for item in logged] == ["reminder", "reminder", "reminder", "reminder"]



def test_chat_family_course_event_only_writes_preclass_reminder(monkeypatch):
    from nudge.commands.chat import chat_command

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "family": {
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {
                "default": "all",
                "rules": [{
                    "id": "kids_courses",
                    "keywords": ["课程", "上课", "跆拳道"],
                    "assignees": ["mom"],
                    "notification_policy": "prestart_only",
                }],
            },
        },
    }
    response = """安排好了。
```json
[{"type":"calendar_event","summary":"跆拳道上课","start":"2026-05-10 20:00","end":"2026-05-10 21:00","person":"家庭组"}]
```"""
    executed = []

    monkeypatch.setattr(chat, "_build_context", lambda: {
        "current_datetime": "2026-05-09 17:00 (Saturday)",
        "events": "",
        "reminders": "",
        "actions": "",
        "habits": "",
    })
    monkeypatch.setattr(chat, "call_llm", lambda system, prompt, task="default": response)
    monkeypatch.setattr("nudge.config.load_config", lambda: config)
    monkeypatch.setattr("nudge.apple.adapters.resolve_apple_backends", lambda config: object())
    monkeypatch.setattr(
        "nudge.commands.do.execute_action",
        lambda action, alias_map, defaults, apple_backends=None: executed.append(action) or True,
    )
    monkeypatch.setattr("nudge.state.log_action", lambda **kwargs: None)

    result = CliRunner().invoke(chat_command, input="家庭组周日晚上8点跆拳道上课\ny\nexit\n")

    assert result.exit_code == 0, result.output
    assert "检测到 1 个待创建项" in result.output
    assert [action["type"] for action in executed] == ["reminder"]
    assert executed[0]["person"] == "妈妈"
    assert executed[0]["due_date"] == "2026-05-10 19:30"
    assert executed[0]["name"] == "妈妈：跆拳道上课（30 分钟后开始）"

def test_chat_passes_family_routing_config_to_group_rewrite(monkeypatch):
    from nudge.commands.chat import chat_command

    routing = {
        "default": "all",
        "rules": [{"id": "kids_courses", "keywords": ["科学实验"], "assignees": ["mom"]}],
    }
    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "family": {
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": routing,
        },
    }
    response = """安排好了。
```json
[{"type":"reminder","name":"科学实验课带材料","due_date":"2026-05-10 20:00","person":"家庭组"}]
```"""
    rewrite_calls = []

    monkeypatch.setattr(chat, "_build_context", lambda: {
        "current_datetime": "2026-05-09 17:00 (Saturday)",
        "events": "",
        "reminders": "",
        "actions": "",
        "habits": "",
    })
    monkeypatch.setattr(chat, "call_llm", lambda system, prompt, task="default": response)
    monkeypatch.setattr("nudge.config.load_config", lambda: config)
    monkeypatch.setattr("nudge.apple.adapters.resolve_apple_backends", lambda config: object())

    def fake_rewrite(actions, family_members, alias_map, routing_arg=None, llm_router=None):
        rewrite_calls.append((routing_arg, llm_router))
        return actions

    monkeypatch.setattr("nudge.commands.do._rewrite_family_group_actions", fake_rewrite)
    monkeypatch.setattr("nudge.commands.do.execute_action", lambda *args, **kwargs: True)
    monkeypatch.setattr("nudge.state.log_action", lambda **kwargs: None)

    result = CliRunner().invoke(chat_command, input="提醒妈妈科学实验课带材料\ny\nexit\n")

    assert result.exit_code == 0, result.output
    assert rewrite_calls == [
        (
            {
                "default": "all",
                "llm_fallback": False,
                "llm_confidence_threshold": 0.65,
                "display": {
                    "title_prefix": True,
                    "body_assignee_note": False,
                },
                "rules": routing["rules"],
            },
            None,
        )
    ]


def test_chat_passes_llm_router_when_family_routing_fallback_enabled(monkeypatch):
    from nudge.commands.chat import chat_command

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "family": {
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {"default": "all", "llm_fallback": True, "rules": []},
        },
    }
    response = """安排好了。
```json
[{"type":"reminder","name":"买材料","due_date":"2026-05-10 20:00","person":"家庭组"}]
```"""
    rewrite_calls = []

    monkeypatch.setattr(chat, "_build_context", lambda: {
        "current_datetime": "2026-05-09 17:00 (Saturday)",
        "events": "",
        "reminders": "",
        "actions": "",
        "habits": "",
    })
    monkeypatch.setattr(chat, "call_llm", lambda system, prompt, task="default": response)
    monkeypatch.setattr("nudge.config.load_config", lambda: config)
    monkeypatch.setattr("nudge.apple.adapters.resolve_apple_backends", lambda config: object())

    def fake_rewrite(actions, family_members, alias_map, routing_arg=None, llm_router=None):
        rewrite_calls.append((routing_arg, llm_router))
        return actions

    monkeypatch.setattr("nudge.commands.do._rewrite_family_group_actions", fake_rewrite)
    monkeypatch.setattr("nudge.commands.do.execute_action", lambda *args, **kwargs: True)
    monkeypatch.setattr("nudge.state.log_action", lambda **kwargs: None)

    result = CliRunner().invoke(chat_command, input="提醒全家买材料\ny\nexit\n")

    assert result.exit_code == 0, result.output
    assert len(rewrite_calls) == 1
    routing_arg, llm_router = rewrite_calls[0]
    assert routing_arg["llm_fallback"] is True
    assert llm_router is not None


def test_chat_llm_fallback_uses_patchable_module_router(monkeypatch):
    from nudge.commands.chat import chat_command

    config = {
        "general": {"default_calendar": "个人", "default_reminder_list": "日常"},
        "family": {
            "mom": {"aliases": ["妈妈"], "calendar": "个人", "reminder_list": "家庭"},
            "routing": {"default": "all", "llm_fallback": True, "rules": []},
        },
    }
    response = """安排好了。
```json
[{"type":"reminder","name":"买材料","due_date":"2026-05-10 20:00","person":"家庭组"}]
```"""
    rewrite_calls = []

    def replacement_router(action, members, routing):
        return {"assignees": ["mom"], "confidence": 0.9, "reason": "妈妈处理"}

    monkeypatch.setattr(chat, "_build_context", lambda: {
        "current_datetime": "2026-05-09 17:00 (Saturday)",
        "events": "",
        "reminders": "",
        "actions": "",
        "habits": "",
    })
    monkeypatch.setattr(chat, "call_llm", lambda system, prompt, task="default": response)
    monkeypatch.setattr(chat, "suggest_family_routing", replacement_router)
    monkeypatch.setattr("nudge.config.load_config", lambda: config)
    monkeypatch.setattr("nudge.apple.adapters.resolve_apple_backends", lambda config: object())

    def fake_rewrite(actions, family_members, alias_map, routing_arg=None, llm_router=None):
        rewrite_calls.append(llm_router)
        return actions

    monkeypatch.setattr("nudge.commands.do._rewrite_family_group_actions", fake_rewrite)
    monkeypatch.setattr("nudge.commands.do.execute_action", lambda *args, **kwargs: True)
    monkeypatch.setattr("nudge.state.log_action", lambda **kwargs: None)

    result = CliRunner().invoke(chat_command, input="提醒全家买材料\ny\nexit\n")

    assert result.exit_code == 0, result.output
    assert rewrite_calls == [replacement_router]


def test_chat_plain_reminder_defaults_remind_date_to_due_date(monkeypatch):
    from nudge.commands.chat import chat_command

    config = {"general": {"default_calendar": "个人", "default_reminder_list": "日常"}}
    response = """安排好了。
```json
[{"type":"reminder","name":"准备公众号发布","due_date":"2026-07-07 09:00"}]
```"""
    executed = []

    monkeypatch.setattr(chat, "_build_context", lambda: {
        "current_datetime": "2026-07-06 17:00 (Monday)",
        "events": "",
        "reminders": "",
        "actions": "",
        "habits": "",
    })
    monkeypatch.setattr(chat, "call_llm", lambda system, prompt, task="default": response)
    monkeypatch.setattr("nudge.config.load_config", lambda: config)
    monkeypatch.setattr("nudge.apple.adapters.resolve_apple_backends", lambda config: object())
    monkeypatch.setattr(
        "nudge.commands.do.execute_action",
        lambda action, alias_map, defaults, apple_backends=None: executed.append(action) or True,
    )
    monkeypatch.setattr("nudge.state.log_action", lambda **kwargs: None)

    result = CliRunner().invoke(chat_command, input="明早9点提醒我准备公众号发布\ny\nexit\n")

    assert result.exit_code == 0, result.output
    assert executed[0]["due_date"] == "2026-07-07 09:00"
    assert executed[0]["remind_date"] == "2026-07-07 09:00"


def test_chat_rejects_non_boolean_notify_before_confirmation(monkeypatch):
    from nudge.commands.chat import chat_command

    config = {"general": {"default_calendar": "个人", "default_reminder_list": "日常"}}
    response = """安排好了。
```json
[{"type":"reminder","name":"仅作截止记录","due_date":"2026-07-07 09:00","notify":"false"}]
```"""
    executed = []

    monkeypatch.setattr(chat, "_build_context", lambda: {
        "current_datetime": "2026-07-06 17:00 (Monday)",
        "events": "",
        "reminders": "",
        "actions": "",
        "habits": "",
    })
    monkeypatch.setattr(chat, "call_llm", lambda system, prompt, task="default": response)
    monkeypatch.setattr("nudge.config.load_config", lambda: config)
    monkeypatch.setattr("nudge.apple.adapters.resolve_apple_backends", lambda config: object())
    monkeypatch.setattr(
        "nudge.commands.do.execute_action",
        lambda *args, **kwargs: executed.append(args[0]) or True,
    )

    result = CliRunner().invoke(chat_command, input="只记截止时间，不要通知\nexit\n")

    assert result.exit_code == 0, result.output
    assert "notify must be a boolean" in result.output
    assert "创建？" not in result.output
    assert executed == []
