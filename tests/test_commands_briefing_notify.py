"""早晚报通知投递失败必须可见（不得静默丢弃 notify 返回值）。"""

from click.testing import CliRunner

from nudge.commands import briefing as briefing_module
from nudge.runtime_log import runtime_log_path


BRIEFING_TEXT = "今天有 3 个日程。"
DAEMON_ALERT_TEXT = "\n".join([
    "Nudge daemon 告警:",
    "- WARN DEAD_LETTER_COMMANDS: 死信队列有 2 条",
    "处理：nudge daemon health --json",
])


def _run(monkeypatch, *, text, notify_impl, args=("--notify",)):
    monkeypatch.setattr(briefing_module, "_morning_briefing", lambda: text)
    monkeypatch.setattr(briefing_module, "notify", notify_impl)
    return CliRunner().invoke(
        briefing_module.briefing_command,
        ["morning", *args],
        prog_name="nudge",
    )


def _read_runtime_log() -> str:
    path = runtime_log_path()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_briefing_notify_failure_is_visible(monkeypatch):
    """正文通知失败时:stderr 有可见提示,runtime_log 有 WARN 记录。"""
    before = len(_read_runtime_log())
    result = _run(
        monkeypatch,
        text=BRIEFING_TEXT,
        notify_impl=lambda *a, **kw: (False, "osascript: not authorized to send notifications"),
    )

    assert result.exit_code == 0, result.output
    assert BRIEFING_TEXT in result.output

    assert "通知发送失败（briefing）" in result.stderr
    assert "not authorized" in result.stderr

    appended = _read_runtime_log()[before:]
    assert "briefing.notify.briefing" in appended
    assert "not authorized" in appended
    assert "WARN" in appended


def test_briefing_daemon_alert_notify_failure_is_distinguishable(monkeypatch):
    """daemon 健康告警这条通知失败时,要能与正文通知区分开。"""
    def notify_impl(title, message, subtitle=None, **kwargs):
        if subtitle == "daemon health":
            return (False, "osascript: timed out")
        return (True, "")

    before = len(_read_runtime_log())
    result = _run(
        monkeypatch,
        text=f"{BRIEFING_TEXT}\n\n{DAEMON_ALERT_TEXT}",
        notify_impl=notify_impl,
    )

    assert result.exit_code == 0, result.output
    assert "通知发送失败（daemon_alert）" in result.stderr
    assert "通知发送失败（briefing）" not in result.stderr
    assert "timed out" in result.stderr

    appended = _read_runtime_log()[before:]
    assert "briefing.notify.daemon_alert" in appended
    assert "briefing.notify.briefing" not in appended


def test_briefing_notify_success_emits_no_failure_signal(monkeypatch):
    """成功路径:stderr 无失败提示,runtime_log 不新增记录。"""
    before = len(_read_runtime_log())
    result = _run(
        monkeypatch,
        text=f"{BRIEFING_TEXT}\n\n{DAEMON_ALERT_TEXT}",
        notify_impl=lambda *a, **kw: (True, ""),
    )

    assert result.exit_code == 0, result.output
    assert "通知发送失败" not in result.stderr
    assert _read_runtime_log()[before:] == ""


def test_send_briefing_notifications_reports_per_channel(monkeypatch):
    """内部结果 dict 逐通道回填 {sent, ok, error},供将来的机器可读输出复用。"""
    def notify_impl(title, message, subtitle=None, **kwargs):
        if subtitle == "daemon health":
            return (False, "osascript: timed out")
        return (True, "")

    monkeypatch.setattr(briefing_module, "notify", notify_impl)
    result = briefing_module._send_briefing_notifications(
        "morning",
        f"{BRIEFING_TEXT}\n\n{DAEMON_ALERT_TEXT}",
    )

    assert result["sent"] is False
    assert result["failed_channels"] == ["daemon_alert"]
    assert result["channels"]["briefing"] == {
        "channel": "briefing",
        "sent": True,
        "ok": True,
        "error": None,
    }
    assert result["channels"]["daemon_alert"]["sent"] is False
    assert "timed out" in result["channels"]["daemon_alert"]["error"]


def test_briefing_text_output_unchanged_without_notify(monkeypatch):
    """默认文本路径保持原有输出格式。"""
    result = _run(monkeypatch, text=BRIEFING_TEXT, notify_impl=lambda *a, **kw: (True, ""), args=())
    assert result.exit_code == 0
    assert result.output == f"Generating morning briefing...\n\n{BRIEFING_TEXT}\n"


def test_briefing_notify_success_output_unchanged(monkeypatch):
    """--notify 成功路径的 stdout 也与修复前一致。"""
    result = _run(monkeypatch, text=BRIEFING_TEXT, notify_impl=lambda *a, **kw: (True, ""))
    assert result.exit_code == 0
    assert result.output == f"Generating morning briefing...\n\n{BRIEFING_TEXT}\n"
