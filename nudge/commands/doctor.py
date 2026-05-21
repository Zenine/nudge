"""Doctor command — diagnose local Nudge setup without writing data."""

import json
from dataclasses import dataclass

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


def run_checks(config_path: str | None = None, config: dict | None = None) -> list[CheckResult]:
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
    checks.append(_check_llm(config))
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
@click.pass_context
def doctor_command(ctx, config_path, json_output):
    """Check local configuration, LLM keys, and macOS app access."""
    checks = run_checks(config_path)
    try:
        config = load_config(config_path)
    except Exception:
        config = None
    log_doctor_checks(checks, config=config)
    if json_output:
        click.echo(json.dumps(doctor_payload(checks), ensure_ascii=False))
    else:
        _print_checks(checks)
    if any(check.status == FAIL for check in checks):
        ctx.exit(1)
