"""Doctor command — diagnose local Nudge setup without writing data."""

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import click

from nudge.apple.adapters import (
    UnsupportedAppleBackendError,
    get_calendar_backend,
    get_clock_backend,
    get_notes_backend,
    get_reminders_backend,
)
from nudge.apple.mail import read_unread_count
from nudge.config import (
    DEFAULT_LLM_CONFIG,
    DEFAULT_SECRETS_PATH,
    get_configured_calendar_names,
    get_defaults,
    get_llm_config,
    load_config,
    resolve_state_dir,
)
from nudge.json_contract import versioned_payload
from nudge.llm import LLMError, create_provider
from nudge.runtime_log import log_doctor_checks


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


_PROVIDER_ENV_HINTS = {
    "anthropic": "ANTHROPIC_API_KEY 或 secrets.yaml: anthropic_api_key",
    "openai": "OPENAI_API_KEY 或 secrets.yaml: openai_api_key",
    "deepseek": "DEEPSEEK_API_KEY 或 secrets.yaml: deepseek_api_key",
    "qwen": "DASHSCOPE_API_KEY / QWEN_API_KEY 或 secrets.yaml: dashscope_api_key",
    "dashscope": "DASHSCOPE_API_KEY / QWEN_API_KEY 或 secrets.yaml: dashscope_api_key",
}
DEFAULT_DAEMON_STALE_MINUTES = 30


@dataclass(frozen=True)
class CheckResult:
    """One doctor check result."""

    status: str
    name: str
    message: str
    hint: str = ""


def _configured_calendars(config: dict) -> list[str]:
    """Collect all calendar names referenced by config."""
    return sorted(get_configured_calendar_names(config))


def _configured_reminder_lists(config: dict) -> list[str]:
    """Collect all Reminders list names referenced by config."""
    names = []
    default_list = get_defaults(config).get("default_reminder_list")
    if default_list:
        names.append(default_list)

    names.extend(config.get("reminders", {}).values())
    for member in config.get("family", {}).values():
        if member.get("reminder_list"):
            names.append(member["reminder_list"])

    return sorted(set(names))


def _check_llm(config: dict) -> CheckResult:
    """Check LLM provider configuration and local API key presence."""
    llm_config = get_llm_config(config)
    provider_name = llm_config.get("provider", DEFAULT_LLM_CONFIG["provider"])
    models = llm_config.get("models", {})
    default_model = (
        models.get("default")
        or llm_config.get("model")
        or DEFAULT_LLM_CONFIG["models"]["default"]
    )

    try:
        provider = create_provider(llm_config)
    except LLMError as e:
        return CheckResult(FAIL, "LLM", str(e))

    if provider_name == "ollama":
        return CheckResult(
            PASS,
            "LLM",
            f"provider={provider_name}, model={default_model}, base_url={provider.base_url}",
        )

    if not getattr(provider, "api_key", ""):
        hint = _PROVIDER_ENV_HINTS.get(provider_name, "设置 provider 专用环境变量，或写入本机 secrets.yaml")
        return CheckResult(
            FAIL,
            "LLM",
            f"LLM API key missing for provider={provider_name}, model={default_model}",
            f"请设置 {hint}；或在 config.toml [llm] 配置 secrets_path。默认路径：{DEFAULT_SECRETS_PATH}",
        )

    base_url = getattr(provider, "base_url", None)
    suffix = f", base_url={base_url}" if base_url else ""
    return CheckResult(PASS, "LLM", f"provider={provider_name}, model={default_model}, API key found{suffix}")


def _check_llm_ping(config: dict) -> CheckResult:
    """Optionally make a tiny provider call to verify LLM connectivity."""
    llm_config = get_llm_config(config)
    models = llm_config.get("models", {})
    model = (
        models.get("default")
        or llm_config.get("model")
        or DEFAULT_LLM_CONFIG["models"]["default"]
    )
    provider_name = llm_config.get("provider", DEFAULT_LLM_CONFIG["provider"])
    try:
        provider = create_provider(llm_config)
        response = provider.call(
            "Nudge doctor connectivity check.",
            "Reply with pong.",
            model,
            max_tokens=8,
            temperature=0,
        )
    except LLMError as e:
        return CheckResult(
            WARN,
            "LLM Ping",
            f"provider={provider_name}, model={model}, ping failed: {e}",
            "这是显式开启的联网/本地模型探测；不影响默认 doctor。请检查 provider、base_url、API key 或本地模型服务。",
        )
    except Exception as e:
        return CheckResult(
            WARN,
            "LLM Ping",
            f"provider={provider_name}, model={model}, ping failed: {e}",
            "这是显式开启的联网/本地模型探测；不影响默认 doctor。请检查 provider、base_url、API key 或本地模型服务。",
        )

    text = str(response).strip()
    if not text:
        return CheckResult(
            WARN,
            "LLM Ping",
            f"provider={provider_name}, model={model}, empty response",
        )
    return CheckResult(PASS, "LLM Ping", f"provider={provider_name}, model={model}, response={text[:40]}")


def _check_calendar(config: dict) -> CheckResult:
    """Check Calendar AppleScript access and configured calendar names."""
    try:
        backend = get_calendar_backend(config)
    except UnsupportedAppleBackendError as e:
        return _unsupported_backend_result("Calendar", e)

    ok, result = backend.list_calendars()
    if not ok:
        return CheckResult(
            FAIL,
            "Calendar",
            f"backend={backend.name}; Calendar AppleScript/EventKit failed: {result}",
            "先打开一次 Calendar；再到 系统设置 → 隐私与安全性 → 日历，允许当前终端/IDE/Python 访问 Calendar。",
        )

    available = set(result)
    required = _configured_calendars(config)
    missing = [name for name in required if name not in available]
    if missing:
        return CheckResult(
            FAIL,
            "Calendar",
            f"Missing configured calendars: {', '.join(missing)}",
            f"当前可见日历：{', '.join(result) if result else '无'}",
        )

    checked = ", ".join(required) if required else "未配置目标日历"
    return CheckResult(
        PASS,
        "Calendar",
        f"backend={backend.name}; AppleScript/EventKit readable; configured calendars found: {checked}",
    )


def _check_reminders(config: dict) -> CheckResult:
    """Check Reminders AppleScript access and configured list names."""
    try:
        backend = get_reminders_backend(config)
    except UnsupportedAppleBackendError as e:
        return _unsupported_backend_result("Reminders", e)

    ok, result = backend.list_lists()
    if not ok:
        return CheckResult(
            WARN,
            "Reminders",
            f"backend={backend.name}; Reminders AppleScript/EventKit not verified: {result}",
            _reminders_fix_hint(str(result)),
        )

    available = set(result)
    required = _configured_reminder_lists(config)
    missing = [name for name in required if name not in available]
    if missing:
        return CheckResult(
            FAIL,
            "Reminders",
            f"Missing configured reminder lists: {', '.join(missing)}",
            f"当前可见列表：{', '.join(result) if result else '无'}",
        )

    checked = ", ".join(required) if required else "未配置目标列表"
    probe_targets = required or result
    for probe_target in probe_targets:
        read_ok, read_result = backend.probe_read(probe_target)
        if not read_ok:
            return CheckResult(
                WARN,
                "Reminders",
                (
                    f"backend={backend.name}; Lists readable; reminder data read not verified; "
                    f"probe list={probe_target}: {read_result}"
                ),
                _reminders_fix_hint(read_result),
            )

    return CheckResult(
        PASS,
        "Reminders",
        f"backend={backend.name}; AppleScript/EventKit readable; configured lists found: {checked}",
    )


def _reminders_fix_hint(error: str) -> str:
    """Return a user-actionable Reminders permission/sync hint."""
    lower = error.lower()
    base = "先打开一次 Reminders；再到 系统设置 → 隐私与安全性 → 提醒事项，允许当前终端/IDE/Python 访问 Reminders。"
    if "timed out" in lower or "timeout" in lower:
        return (
            "Reminders 列表可见，但读取提醒事项数据超时。"
            "请打开 Reminders.app，等待 iCloud 同步/权限弹窗完成；"
            "同时检查 系统设置 → 隐私与安全性 → 提醒事项 中当前终端/IDE/Python 是否已被允许；必要时退出并重开 Reminders，"
            "再重新运行 nudge doctor。"
        )
    if "not authorized" in lower or "not permitted" in lower or "-1743" in lower:
        return base
    return base


def _check_mail() -> CheckResult:
    """Check read-only Mail AppleScript access."""
    ok, result = read_unread_count(timeout=5)
    if not ok:
        return CheckResult(
            WARN,
            "Mail",
            f"Mail AppleScript not verified: {result}",
            "先打开一次 Mail；再到 系统设置 → 隐私与安全性 → 自动化，允许当前终端/IDE/Python 控制 Mail。",
        )
    return CheckResult(PASS, "Mail", f"AppleScript readable; unread_count={result}")


def _check_notes_for_config(config: dict) -> CheckResult:
    """Check optional Notes AppleScript access without reading note bodies."""
    try:
        backend = get_notes_backend(config)
    except UnsupportedAppleBackendError as e:
        return _unsupported_backend_result("Notes", e)

    ok, result = backend.list_folders()
    if not ok:
        return CheckResult(
            WARN,
            "Notes",
            f"backend={backend.name}; Notes AppleScript not verified: {result}",
            "先打开一次 Notes；再到 系统设置 → 隐私与安全性 → 自动化，允许当前终端/IDE/Python 控制 Notes。",
        )

    return CheckResult(
        PASS,
        "Notes",
        f"backend={backend.name}; AppleScript readable; visible folders={len(result)}; default write folder=Nudge",
    )


def _check_clock_for_config(config: dict) -> CheckResult:
    """Check optional Clock alarm bridge through configured backend."""
    try:
        backend = get_clock_backend(config)
    except UnsupportedAppleBackendError as e:
        return _unsupported_backend_result("Clock", e)

    ok, message = backend.check()
    if ok:
        return CheckResult(PASS, "Clock", f"backend={backend.name}; {message}")
    return CheckResult(
        WARN,
        "Clock",
        f"backend={backend.name}; {message}",
        (
            f"如需真实写入 Clock alarm，请在 Shortcuts.app 新建 `{backend.shortcut_name}`，"
            "读取输入 JSON 的 time/label，并调用 Clock → Create Alarm；否则可继续用 Calendar/Reminders 提醒替代。"
        ),
    )


def _unsupported_backend_result(name: str, error: UnsupportedAppleBackendError) -> CheckResult:
    """Render unsupported Apple backend config as a doctor failure."""
    default_backend = {
        "calendar": "native",
        "reminders": "native",
        "notes": "native",
        "clock": "shortcuts",
    }.get(error.service, "native")
    return CheckResult(
        FAIL,
        name,
        str(error),
        (
            f"当前版本先保留默认 runtime；请把 config.toml 中 "
            f"`[apple.{error.service}] backend = \"{default_backend}\"`，"
            "外部 ical/rem/ekctl/MCP backend 后续再接入。"
        ),
    )


def _state_db_path(config: dict) -> Path:
    return resolve_state_dir(config) / "nudge.db"


def _open_readonly_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _check_sqlite_integrity(config: dict) -> CheckResult:
    """Run SQLite PRAGMA integrity_check through a read-only connection."""
    db_path = _state_db_path(config)
    if not db_path.exists():
        return CheckResult(
            WARN,
            "SQLite",
            f"state database not found: {db_path}",
            "首次写入本地状态后会创建 SQLite；doctor 不会为了检查而创建数据库。",
        )

    try:
        with _open_readonly_db(db_path) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as e:
        return CheckResult(
            FAIL,
            "SQLite",
            f"integrity_check failed to run: {e}",
            "请先备份状态目录，再排查 SQLite 文件。",
        )

    result = row[0] if row else ""
    if result == "ok":
        return CheckResult(PASS, "SQLite", f"path={db_path}; integrity_check=ok")
    return CheckResult(
        FAIL,
        "SQLite",
        f"path={db_path}; integrity_check={result}",
        "请先备份状态目录，再考虑从同步盘或备份恢复。",
    )


def _check_daemon_summary(config: dict) -> CheckResult:
    """Summarize daemon queue state without recovering or mutating rows."""
    db_path = _state_db_path(config)
    if not db_path.exists():
        return CheckResult(
            WARN,
            "Daemon",
            "state database not found; daemon queue not initialized",
            "这是只读摘要；运行 daemon/agent 队列命令后会出现队列表。",
        )

    try:
        with _open_readonly_db(db_path) as conn:
            if not _sqlite_table_exists(conn, "command_queue"):
                return CheckResult(
                    PASS,
                    "Daemon",
                    "command_queue table not initialized; queue empty",
                )
            counts = {
                row["status"]: row["count"]
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM command_queue GROUP BY status"
                ).fetchall()
            }
            stale_cutoff = (
                datetime.now() - timedelta(minutes=DEFAULT_DAEMON_STALE_MINUTES)
            ).strftime("%Y-%m-%d %H:%M:%S")
            stale_running = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM command_queue
                WHERE status = 'running'
                  AND (started_at IS NULL OR started_at <= ?)
                """,
                (stale_cutoff,),
            ).fetchone()["count"]
    except sqlite3.Error as e:
        return CheckResult(WARN, "Daemon", f"daemon queue summary unavailable: {e}")

    queued = int(counts.get("queued", 0) or 0)
    running = int(counts.get("running", 0) or 0)
    failed = int(counts.get("failed", 0) or 0)
    dead_letter = int(counts.get("dead_letter", 0) or 0)
    stale_running = int(stale_running or 0)
    message = (
        f"queue queued={queued} running={running} failed={failed} "
        f"dead_letter={dead_letter} stale_running={stale_running} "
        f"stale_minutes={DEFAULT_DAEMON_STALE_MINUTES}"
    )
    if dead_letter:
        return CheckResult(
            FAIL,
            "Daemon",
            message,
            "存在 dead_letter 命令；确认不会重复写入后运行 `nudge daemon queue --status dead_letter --json` 和 `nudge daemon retry`。",
        )
    if stale_running:
        return CheckResult(
            WARN,
            "Daemon",
            message,
            "存在旧 running 命令；运行 `nudge daemon recover` 前先检查队列内容。",
        )
    return CheckResult(PASS, "Daemon", message)


def _check_disk_space(config: dict) -> CheckResult:
    """Check free space for the configured state directory path."""
    state_dir = resolve_state_dir(config)
    probe = state_dir if state_dir.exists() else state_dir.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError as e:
        return CheckResult(WARN, "Disk", f"cannot read disk usage for {state_dir}: {e}")

    free_gib = usage.free / (1024 ** 3)
    total_gib = usage.total / (1024 ** 3)
    message = f"path={state_dir}; free={free_gib:.1f}GiB total={total_gib:.1f}GiB"
    if usage.free < 1 * 1024 ** 3:
        return CheckResult(WARN, "Disk", message, "剩余空间低于 1GiB；同步盘和 SQLite 可能受影响。")
    return CheckResult(PASS, "Disk", message)


def run_checks(
    config_path: str | None = None,
    config: dict | None = None,
    *,
    llm_ping: bool = False,
) -> list[CheckResult]:
    """Run all read-only diagnostics."""
    checks: list[CheckResult] = []
    if config is None:
        try:
            config = load_config(config_path)
        except Exception as e:
            return [
                CheckResult(
                    FAIL,
                    "Config",
                    f"Cannot load config.toml: {e}",
                    "确认仓库内 config.toml 存在且 TOML 语法正确；也可用 --config 指定路径。",
                )
            ]

    checks.append(CheckResult(PASS, "Config", "config.toml loaded"))
    checks.append(_check_sqlite_integrity(config))
    checks.append(_check_daemon_summary(config))
    checks.append(_check_disk_space(config))
    checks.append(_check_llm(config))
    if llm_ping:
        checks.append(_check_llm_ping(config))
    checks.append(_check_calendar(config))
    checks.append(_check_reminders(config))
    checks.append(_check_notes_for_config(config))
    checks.append(_check_mail())
    checks.append(_check_clock_for_config(config))
    return checks


def summarize_checks(checks: list[CheckResult]) -> dict[str, int]:
    """Return PASS/WARN/FAIL counts for doctor checks."""
    summary = {PASS: 0, WARN: 0, FAIL: 0}
    for check in checks:
        if check.status in summary:
            summary[check.status] += 1
    return summary


def _check_to_json(check: CheckResult) -> dict[str, str]:
    return {
        "status": check.status,
        "name": check.name,
        "message": check.message,
        "hint": check.hint,
    }


def doctor_payload(checks: list[CheckResult], *, include_pass: bool = True) -> dict:
    """Build stable machine-readable doctor diagnostics."""
    summary = summarize_checks(checks)
    visible_checks = checks if include_pass else [check for check in checks if check.status != PASS]
    failures = [check for check in checks if check.status == FAIL]
    return versioned_payload({
        "ok": summary[FAIL] == 0,
        "summary": summary,
        "checks": [_check_to_json(check) for check in visible_checks],
        "errors": [
            {
                "code": "DOCTOR_CHECK_FAILED",
                "check": check.name,
                "message": check.message,
                "hint": check.hint,
            }
            for check in failures
        ],
    })


def _print_checks(checks: list[CheckResult]) -> None:
    click.echo("Nudge Doctor\n")
    for check in checks:
        click.echo(f"{check.status:<4}  {check.name:<10} {check.message}")
        if check.hint:
            click.echo(f"      Fix: {check.hint}")


@click.command("doctor")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
@click.option("--llm-ping", is_flag=True, help="Optionally make a tiny LLM provider call")
@click.pass_context
def doctor_command(ctx, config_path, json_output, llm_ping):
    """Check local configuration, LLM keys, and macOS app access."""
    checks = run_checks(config_path, llm_ping=True) if llm_ping else run_checks(config_path)
    try:
        config = load_config(config_path)
    except Exception:
        config = None
    if not json_output:
        log_doctor_checks(checks, config=config)
    if json_output:
        click.echo(json.dumps(doctor_payload(checks), ensure_ascii=False))
    else:
        _print_checks(checks)
    if any(check.status == FAIL for check in checks):
        ctx.exit(1)
