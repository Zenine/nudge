"""Local daemon for queue-based Apple execution.

This runtime layer does not call LLM. It pulls structured payloads from the
`command_queue` table and dispatches to existing agent action/status engines.
"""

from __future__ import annotations

import json
import traceback
import platform
import signal
import time
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import click

from nudge.apple.notifications import notify
from nudge.commands.agent import (
    _configure_agent_state,
    _read_request_text,
    apply_action_status,
    apply_agent_request,
)
from nudge.config import load_config
from nudge.daemon_control_app import control_app_status, install_control_app, open_control_app, uninstall_control_app
from nudge.json_contract import versioned_payload
from nudge.state import (
    DEFAULT_COMMAND_QUEUE_MAX_DEPTH,
    claim_next_queued_command,
    enqueue_agent_command,
    get_daemon_runtime_status,
    list_queued_commands,
    list_stale_running_commands,
    log_daemon_run,
    mark_queued_command_complete,
    recover_stale_running_commands,
    retry_queued_command,
)

SUPPORTED_REQUEST_TYPES = {"agent.apply", "agent.status"}
DEFAULT_DAEMON_STALE_MINUTES = 30
DEFAULT_DAEMON_MAX_ATTEMPTS = 3
DAEMON_LAUNCHD_LABEL = "com.nudge.agent"
DAEMON_ALERT_POLICY = {
    "LAUNCHD_UNSUPPORTED": {
        "touch": "briefing",
        "operator_action": "ignore_or_use_cli",
        "escalation": "none",
    },
    "LAUNCHD_PLIST_MISSING": {
        "touch": "briefing+notification",
        "operator_action": "install_launchagent",
        "escalation": "same_day",
    },
    "LAUNCHD_NOT_LOADED": {
        "touch": "briefing+notification",
        "operator_action": "start_launchagent",
        "escalation": "same_day",
    },
    "STALE_RUNNING_COMMANDS": {
        "touch": "briefing+notification",
        "operator_action": "recover",
        "escalation": "same_day",
    },
    "DEAD_LETTER_COMMANDS": {
        "touch": "briefing+notification",
        "operator_action": "manual_replay",
        "escalation": "manual_review_required",
    },
}


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_iso8601(text: str | None) -> datetime | None:
    if not text:
        return None
    for candidate in [text, text.replace(" ", "T")]:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _ms_since(start_text: str | None, fallback_ms: int | None = None) -> int:
    start_time = _parse_iso8601(start_text)
    if start_time is None:
        return 0 if fallback_ms is None else fallback_ms
    return max(0, int((datetime.now() - start_time).total_seconds() * 1000))


def _int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _coerce_error_text(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first_error = errors[0]
    if not isinstance(first_error, dict):
        return str(first_error)
    return str(
        first_error.get("message")
        or first_error.get("detail")
        or first_error.get("code")
        or first_error.get("raw_error")
    )


def _exception_payload(
    *,
    request_id: str,
    source: str | None,
    exc: Exception,
) -> tuple[dict, int, str]:
    """Convert an unexpected per-command exception into a stable failure payload."""
    error_text = f"{type(exc).__name__}: {exc}"
    return {
        "ok": False,
        "request_id": request_id,
        "source": source,
        "dry_run": False,
        "errors": [
            {
                "code": "DAEMON_COMMAND_EXCEPTION",
                "message": "daemon command raised an unexpected exception",
                "detail": error_text,
            }
        ],
    }, 1, error_text


def _run_payload(
    request_type: str,
    payload: dict[str, Any],
    *,
    config: dict | None = None,
) -> tuple[dict, int, str]:
    """Run one structured request and return stable response + exit_code + optional engine error."""
    if request_type == "agent.apply":
        response, exit_code = apply_agent_request(
            request=payload,
            config=config if config is not None else load_config(),
        )
        return response, exit_code, ""

    if request_type == "agent.status":
        response, exit_code = apply_action_status(request=payload)
        return response, exit_code, ""

    return {
        "ok": False,
        "request_id": payload.get("request_id"),
        "source": payload.get("source"),
        "dry_run": False,
        "errors": [
            {
                "code": "REQUEST_TYPE_UNSUPPORTED",
                "message": f"unsupported request_type={request_type}",
                "detail": "supported types: agent.apply, agent.status",
            }
        ],
    }, 1, f"unsupported request_type={request_type}"


def _format_row(row: dict) -> str:
    status = row["status"]
    request_id = row["request_id"]
    request_type = row["request_type"]
    source = row["source"] or "n/a"
    return f"{status:<9} {request_id} {request_type} source={source}"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_nudge_cmd() -> Path:
    wrapper = _repo_root() / "bin" / "nudge"
    if wrapper.exists():
        return wrapper
    return Path("nudge")


def _launchd_paths(label: str = DAEMON_LAUNCHD_LABEL) -> dict[str, Path]:
    home = Path.home()
    launch_dir = home / "Library" / "LaunchAgents"
    log_dir = home / "Library" / "Logs"
    return {
        "launch_dir": launch_dir,
        "log_dir": log_dir,
        "plist_path": launch_dir / f"{label}.plist",
        "out_log_path": log_dir / f"{label}.out.log",
        "err_log_path": log_dir / f"{label}.err.log",
    }


def _launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchd_service(label: str = DAEMON_LAUNCHD_LABEL) -> str:
    return f"{_launchd_domain()}/{label}"


def _launchd_supported() -> bool:
    return platform.system() == "Darwin"


def _launchctl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _render_daemon_launchd_plist(
    *,
    label: str,
    nudge_cmd: Path,
    workdir: Path,
    out_log_path: Path,
    err_log_path: Path,
    sleep_ms: int,
    stale_minutes: int,
    max_attempts: int,
    max_queue_depth: int,
    config_path: Path | None = None,
) -> str:
    config_args = ""
    if config_path is not None:
        config_args = (
            f"        <string>--config</string>\n"
            f"        <string>{escape(str(config_path))}</string>\n"
        )
    values = {
        "label": escape(label),
        "nudge_cmd": escape(str(nudge_cmd)),
        "workdir": escape(str(workdir)),
        "out_log": escape(str(out_log_path)),
        "err_log": escape(str(err_log_path)),
        "sleep_ms": escape(str(sleep_ms)),
        "stale_minutes": escape(str(stale_minutes)),
        "max_attempts": escape(str(max_attempts)),
        "max_queue_depth": escape(str(max_queue_depth)),
    }
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{values["label"]}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{values["nudge_cmd"]}</string>
        <string>daemon</string>
        <string>run</string>
{config_args}
    </array>
    <key>WorkingDirectory</key>
    <string>{values["workdir"]}</string>
    <key>StandardOutPath</key>
    <string>{values["out_log"]}</string>
    <key>StandardErrorPath</key>
    <string>{values["err_log"]}</string>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NUDGE_DAEMON_SLEEP_MS</key>
        <string>{values["sleep_ms"]}</string>
        <key>NUDGE_DAEMON_STALE_MINUTES</key>
        <string>{values["stale_minutes"]}</string>
        <key>NUDGE_DAEMON_MAX_ATTEMPTS</key>
        <string>{values["max_attempts"]}</string>
        <key>NUDGE_DAEMON_MAX_QUEUE_DEPTH</key>
        <string>{values["max_queue_depth"]}</string>
    </dict>
</dict>
</plist>
"""


def _launchd_status(label: str = DAEMON_LAUNCHD_LABEL) -> dict[str, object]:
    paths = _launchd_paths(label)
    status = {
        "supported": _launchd_supported(),
        "label": label,
        "domain": _launchd_domain(),
        "service": _launchd_service(label),
        "plist_path": str(paths["plist_path"]),
        "plist_exists": paths["plist_path"].exists(),
        "out_log_path": str(paths["out_log_path"]),
        "err_log_path": str(paths["err_log_path"]),
        "loaded": False,
        "state_hint": "unsupported_platform",
        "error": None,
    }
    if not status["supported"]:
        return status

    result = _launchctl(["print", _launchd_service(label)])
    status["loaded"] = result.returncode == 0
    if result.returncode == 0:
        status["state_hint"] = "running" if "state = running" in (result.stdout or "") else "loaded"
    else:
        status["state_hint"] = "not_loaded"
        status["error"] = (result.stderr or result.stdout or "").strip() or None
    return status


def _load_launchd_plist(plist_path: Path) -> subprocess.CompletedProcess:
    result = _launchctl(["bootstrap", _launchd_domain(), str(plist_path)])
    if result.returncode == 0:
        return result
    _launchctl(["unload", "-w", str(plist_path)])
    return _launchctl(["load", "-w", str(plist_path)])


def _write_launchd_plist(
    *,
    label: str = DAEMON_LAUNCHD_LABEL,
    nudge_cmd: Path | None = None,
    workdir: Path | None = None,
    sleep_ms: int | None = None,
    stale_minutes: int | None = None,
    max_attempts: int | None = None,
    max_queue_depth: int | None = None,
    config_path: Path | None = None,
) -> Path:
    paths = _launchd_paths(label)
    paths["launch_dir"].mkdir(parents=True, exist_ok=True)
    paths["log_dir"].mkdir(parents=True, exist_ok=True)
    plist = _render_daemon_launchd_plist(
        label=label,
        nudge_cmd=nudge_cmd or _default_nudge_cmd(),
        workdir=workdir or _repo_root(),
        out_log_path=paths["out_log_path"],
        err_log_path=paths["err_log_path"],
        sleep_ms=sleep_ms or _int_from_env("NUDGE_DAEMON_SLEEP_MS", 3000),
        stale_minutes=stale_minutes or _int_from_env("NUDGE_DAEMON_STALE_MINUTES", DEFAULT_DAEMON_STALE_MINUTES),
        max_attempts=max_attempts or _int_from_env("NUDGE_DAEMON_MAX_ATTEMPTS", DEFAULT_DAEMON_MAX_ATTEMPTS),
        max_queue_depth=max_queue_depth or _int_from_env("NUDGE_DAEMON_MAX_QUEUE_DEPTH", DEFAULT_COMMAND_QUEUE_MAX_DEPTH),
        config_path=config_path,
    )
    paths["plist_path"].write_text(plist, encoding="utf-8")
    return paths["plist_path"]


def _launchd_payload(action: str, *, ok: bool, error: str | None = None) -> dict[str, object]:
    status = _launchd_status()
    return {
        "ok": ok,
        "action": action,
        "label": DAEMON_LAUNCHD_LABEL,
        "plist_path": status["plist_path"],
        "plist_exists": status["plist_exists"],
        "launchd": status,
        "error": error,
    }


def _echo_or_raise_launchd(payload: dict[str, object], json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
    elif payload.get("ok"):
        click.echo(f"{payload['action']}: {payload['label']} ok")
    else:
        click.echo(f"{payload['action']}: {payload['label']} failed")
        if payload.get("error"):
            click.echo(str(payload["error"]))
    if not payload.get("ok"):
        raise click.ClickException(str(payload.get("error") or "launchd command failed"))


@click.group("daemon")
def daemon_command():
    """Local queue runtime for Apple execution without LLM."""
    pass


@daemon_command.command("enqueue")
@click.option("--type", "request_type", default="agent.apply", type=click.Choice(sorted(SUPPORTED_REQUEST_TYPES)))
@click.option("--file", "-f", "file_path", default=None, help="Read request JSON from file")
@click.option("--request-id", "request_id", default=None, help="Optional request id (auto-generated if missing)")
@click.option("--source", default=None, help="Optional logical request source")
@click.option(
    "--max-queue-depth",
    default=None,
    type=click.IntRange(1, 100_000),
    help="Reject enqueue when queued/running depth reaches this limit",
)
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def enqueue_command(request_type, file_path, request_id, source, max_queue_depth, json_output):
    """Enqueue a structured request for daemon execution."""
    try:
        raw_request = _read_request_text(file_path)
        request_payload = json.loads(raw_request)
        if not isinstance(request_payload, dict):
            raise ValueError("request payload must be a JSON object")
    except OSError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "error": str(exc)}), ensure_ascii=False))
            raise click.ClickException(str(exc))
        raise click.ClickException(f"cannot read request payload: {exc}")
    except (json.JSONDecodeError, ValueError) as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "error": str(exc)}), ensure_ascii=False))
            raise click.ClickException(str(exc))
        raise click.ClickException(str(exc))

    final_request_id = request_id or request_payload.get("request_id")
    if source is not None:
        request_payload["source"] = source
    if final_request_id:
        request_payload["request_id"] = final_request_id

    resolved_max_depth = max_queue_depth
    if resolved_max_depth is None:
        resolved_max_depth = _int_from_env("NUDGE_DAEMON_MAX_QUEUE_DEPTH", DEFAULT_COMMAND_QUEUE_MAX_DEPTH)

    try:
        created_id = enqueue_agent_command(
            payload=request_payload,
            request_type=request_type,
            source=source or request_payload.get("source"),
            request_id=final_request_id,
            max_queue_depth=resolved_max_depth,
        )
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "error": str(exc)}), ensure_ascii=False))
            raise click.ClickException(str(exc))
        raise click.ClickException(str(exc))

    payload = {
        "ok": True,
        "request_id": created_id,
        "request_type": request_type,
        "source": source or request_payload.get("source"),
    }
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return
    click.echo(f"queued request: {created_id} ({request_type})")


@daemon_command.command("queue")
@click.option("--status", "-s", "status_filter", default=None, help="Filter by queue status")
@click.option("--limit", "-n", default=50, type=click.IntRange(1, 500))
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def queue_command(status_filter, limit, json_output):
    """List queue rows for quick troubleshooting."""
    rows = list_queued_commands(status=status_filter, limit=limit)
    payload = {
        "ok": True,
        "count": len(rows),
        "items": rows,
    }
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return
    if not rows:
        click.echo("No queued commands.")
        return
    for row in rows:
        click.echo(_format_row(row))


@daemon_command.command("status")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def status_command(json_output):
    """Show queue depth and last successful command metrics."""
    payload = get_daemon_runtime_status()
    payload["ok"] = True
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return
    click.echo(f"queued: {payload.get('queued', 0)}")
    click.echo(f"running: {payload.get('running', 0)}")
    click.echo(f"succeeded: {payload.get('succeeded', 0)}")
    click.echo(f"failed: {payload.get('failed', 0)}")
    click.echo(f"dead_letter: {payload.get('dead_letter', 0)}")
    if payload.get("last_run_at"):
        click.echo(
            f"last_run: {payload['last_run_request_id']} @ {payload['last_run_at']} ({payload.get('last_run_ms')} ms)"
        )


@daemon_command.command("recover")
@click.option(
    "--stale-minutes",
    default=None,
    type=click.IntRange(1, 10_080),
    help="Recover running commands older than this many minutes",
)
@click.option(
    "--max-attempts",
    default=None,
    type=click.IntRange(1, 100),
    help="Move stale running commands to dead_letter after this many attempts",
)
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def recover_command(stale_minutes, max_attempts, json_output):
    """Recover stale running queue rows after crash, sleep, or daemon restart."""
    resolved_stale_minutes = stale_minutes
    if resolved_stale_minutes is None:
        resolved_stale_minutes = _int_from_env("NUDGE_DAEMON_STALE_MINUTES", DEFAULT_DAEMON_STALE_MINUTES)
    resolved_max_attempts = max_attempts
    if resolved_max_attempts is None:
        resolved_max_attempts = _int_from_env("NUDGE_DAEMON_MAX_ATTEMPTS", DEFAULT_DAEMON_MAX_ATTEMPTS)

    summary = recover_stale_running_commands(
        stale_minutes=resolved_stale_minutes,
        max_attempts=resolved_max_attempts,
    )
    payload = {"ok": True, **summary}
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return

    click.echo(f"requeued: {payload['requeued_count']}")
    for row in payload["requeued"]:
        click.echo(f"  {_format_row(row)}")
    click.echo(f"dead_lettered: {payload['dead_lettered_count']}")
    for row in payload["dead_lettered"]:
        click.echo(f"  {_format_row(row)}")


@daemon_command.command("retry")
@click.option("--request-id", required=True, help="Failed/dead-letter request id to requeue")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def retry_command(request_id, json_output):
    """Explicitly requeue one failed or dead-letter command."""
    item = retry_queued_command(request_id)
    if item is None:
        payload = {
            "ok": False,
            "request_id": request_id,
            "error": "request is not failed/dead_letter or does not exist",
        }
        if json_output:
            click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
            raise click.ClickException(payload["error"])
        raise click.ClickException(payload["error"])

    payload = {"ok": True, "item": item}
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return
    click.echo(f"requeued request: {request_id}")


@daemon_command.group("launchd")
def launchd_command():
    """Install, start, stop, and inspect the macOS daemon LaunchAgent."""
    pass


@launchd_command.command("install")
@click.option("--config", "-c", "config_path", default=None, type=click.Path(path_type=Path), help="Config file path for daemon run")
@click.option("--sleep-ms", default=None, type=click.IntRange(250, 60_000))
@click.option("--stale-minutes", default=None, type=click.IntRange(1, 10_080))
@click.option("--max-attempts", default=None, type=click.IntRange(1, 100))
@click.option("--max-queue-depth", default=None, type=click.IntRange(1, 100_000))
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def launchd_install_command(config_path, sleep_ms, stale_minutes, max_attempts, max_queue_depth, json_output):
    """Write and load the daemon LaunchAgent plist."""
    if not _launchd_supported():
        _echo_or_raise_launchd(
            _launchd_payload("install", ok=False, error="launchd is only supported on macOS"),
            json_output,
        )
        return

    plist_path = _write_launchd_plist(
        sleep_ms=sleep_ms,
        stale_minutes=stale_minutes,
        max_attempts=max_attempts,
        max_queue_depth=max_queue_depth,
        config_path=config_path,
    )
    _launchctl(["bootout", _launchd_service()])
    result = _load_launchd_plist(plist_path)
    payload = _launchd_payload(
        "install",
        ok=result.returncode == 0,
        error=(result.stderr or result.stdout or "").strip() if result.returncode != 0 else None,
    )
    _echo_or_raise_launchd(payload, json_output)


@launchd_command.command("start")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def launchd_start_command(json_output):
    """Load an existing daemon LaunchAgent plist."""
    if not _launchd_supported():
        _echo_or_raise_launchd(
            _launchd_payload("start", ok=False, error="launchd is only supported on macOS"),
            json_output,
        )
        return

    plist_path = _launchd_paths()["plist_path"]
    if not plist_path.exists():
        _echo_or_raise_launchd(
            _launchd_payload("start", ok=False, error=f"plist not found: {plist_path}; run `nudge daemon launchd install`"),
            json_output,
        )
        return
    result = _load_launchd_plist(plist_path)
    payload = _launchd_payload(
        "start",
        ok=result.returncode == 0,
        error=(result.stderr or result.stdout or "").strip() if result.returncode != 0 else None,
    )
    _echo_or_raise_launchd(payload, json_output)


@launchd_command.command("stop")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def launchd_stop_command(json_output):
    """Unload the daemon LaunchAgent without deleting the plist."""
    if not _launchd_supported():
        _echo_or_raise_launchd(
            _launchd_payload("stop", ok=False, error="launchd is only supported on macOS"),
            json_output,
        )
        return

    result = _launchctl(["bootout", _launchd_service()])
    if result.returncode != 0:
        plist_path = _launchd_paths()["plist_path"]
        if plist_path.exists():
            result = _launchctl(["unload", "-w", str(plist_path)])
    payload = _launchd_payload(
        "stop",
        ok=result.returncode == 0,
        error=(result.stderr or result.stdout or "").strip() if result.returncode != 0 else None,
    )
    _echo_or_raise_launchd(payload, json_output)


@launchd_command.command("restart")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def launchd_restart_command(json_output):
    """Restart the loaded daemon LaunchAgent."""
    if not _launchd_supported():
        _echo_or_raise_launchd(
            _launchd_payload("restart", ok=False, error="launchd is only supported on macOS"),
            json_output,
        )
        return

    result = _launchctl(["kickstart", "-k", _launchd_service()])
    payload = _launchd_payload(
        "restart",
        ok=result.returncode == 0,
        error=(result.stderr or result.stdout or "").strip() if result.returncode != 0 else None,
    )
    _echo_or_raise_launchd(payload, json_output)


@launchd_command.command("uninstall")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def launchd_uninstall_command(json_output):
    """Unload and remove the daemon LaunchAgent plist."""
    if not _launchd_supported():
        _echo_or_raise_launchd(
            _launchd_payload("uninstall", ok=False, error="launchd is only supported on macOS"),
            json_output,
        )
        return

    _launchctl(["bootout", _launchd_service()])
    plist_path = _launchd_paths()["plist_path"]
    if plist_path.exists():
        plist_path.unlink()
    _echo_or_raise_launchd(_launchd_payload("uninstall", ok=True), json_output)


@launchd_command.command("status")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def launchd_status_command(json_output):
    """Show daemon LaunchAgent load state and plist/log paths."""
    launchd = _launchd_status()
    payload = {"ok": True, "launchd": launchd}
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return
    click.echo(f"supported: {launchd['supported']}")
    click.echo(f"label: {launchd['label']}")
    click.echo(f"loaded: {launchd['loaded']}")
    click.echo(f"plist: {launchd['plist_path']}")
    click.echo(f"plist_exists: {launchd['plist_exists']}")
    click.echo(f"state: {launchd['state_hint']}")


def build_daemon_health_report(stale_minutes: int | None = None, max_attempts: int | None = None) -> dict[str, object]:
    """Build a read-only daemon health report for CLI, briefing, and future alerts."""
    resolved_stale_minutes = stale_minutes
    if resolved_stale_minutes is None:
        resolved_stale_minutes = _int_from_env("NUDGE_DAEMON_STALE_MINUTES", DEFAULT_DAEMON_STALE_MINUTES)
    resolved_max_attempts = max_attempts
    if resolved_max_attempts is None:
        resolved_max_attempts = _int_from_env("NUDGE_DAEMON_MAX_ATTEMPTS", DEFAULT_DAEMON_MAX_ATTEMPTS)

    queue = get_daemon_runtime_status()
    launchd = _launchd_status()
    stale_running_items = list_stale_running_commands(
        stale_minutes=resolved_stale_minutes,
        max_attempts=resolved_max_attempts,
    )
    issues: list[dict[str, str]] = []

    if not launchd["supported"]:
        issues.append({
            "severity": "warn",
            "code": "LAUNCHD_UNSUPPORTED",
            "message": "当前平台不是 macOS，launchd 自启动不可用。",
        })
    else:
        if not launchd["plist_exists"]:
            issues.append({
                "severity": "warn",
                "code": "LAUNCHD_PLIST_MISSING",
                "message": "未安装 daemon LaunchAgent；运行 `nudge daemon launchd install`。",
            })
        if not launchd["loaded"]:
            issues.append({
                "severity": "warn",
                "code": "LAUNCHD_NOT_LOADED",
                "message": "daemon LaunchAgent 当前未加载；运行 `nudge daemon launchd start` 或 `install`。",
            })
    if stale_running_items:
        issues.append({
            "severity": "warn",
            "code": "STALE_RUNNING_COMMANDS",
            "message": "存在卡在 running 的旧命令；运行 `nudge daemon recover`。",
        })
    if int(queue.get("dead_letter", 0) or 0) > 0:
        issues.append({
            "severity": "fail",
            "code": "DEAD_LETTER_COMMANDS",
            "message": "存在 dead_letter 命令；确认不会重复写入后运行 `nudge daemon retry --request-id ...`。",
        })

    has_fail = any(issue["severity"] == "fail" for issue in issues)
    status = "fail" if has_fail else ("warn" if issues else "ok")
    alert_policy = [
        {"code": issue["code"], **DAEMON_ALERT_POLICY.get(issue["code"], {
            "touch": "briefing",
            "operator_action": "inspect",
            "escalation": "none",
        })}
        for issue in issues
    ]
    return {
        "ok": status == "ok",
        "status": status,
        "queue": queue,
        "launchd": launchd,
        "stale_running": {
            "stale_minutes": resolved_stale_minutes,
            "max_attempts": resolved_max_attempts,
            "count": len(stale_running_items),
            "items": stale_running_items,
        },
        "issues": issues,
        "alert_policy": alert_policy,
    }


def _daemon_health_notification_message(report: dict[str, object]) -> str:
    queue = report.get("queue") or {}
    stale_running = report.get("stale_running") or {}
    issue_codes = [str(issue.get("code")) for issue in report.get("issues") or []]
    lines = [
        "daemon 需要处理：" + ", ".join(issue_codes),
        (
            "queue "
            f"queued={queue.get('queued', 0)} "
            f"running={queue.get('running', 0)} "
            f"dead_letter={queue.get('dead_letter', 0)} "
            f"stale_running={stale_running.get('count', 0)}"
        ),
        "先运行：nudge daemon health --json",
    ]
    if "STALE_RUNNING_COMMANDS" in issue_codes:
        lines.append("恢复：nudge daemon recover")
    if "DEAD_LETTER_COMMANDS" in issue_codes:
        lines.append("死信：nudge daemon queue --status dead_letter --json")
    return "\n".join(lines)


def _send_daemon_health_notification(report: dict[str, object]) -> dict[str, object]:
    """Send a local notification for unhealthy daemon state, quietly skip healthy state."""
    if report.get("ok") and not report.get("issues"):
        return {"sent": False, "reason": "healthy"}

    message = _daemon_health_notification_message(report)
    ok, raw = notify(
        "Nudge daemon 告警",
        message[:240],
        subtitle=str(report.get("status") or "warn"),
    )
    return {
        "sent": bool(ok),
        "ok": bool(ok),
        "error": None if ok else raw,
    }


@daemon_command.command("health")
@click.option("--stale-minutes", default=None, type=click.IntRange(1, 10_080))
@click.option("--max-attempts", default=None, type=click.IntRange(1, 100))
@click.option("--notify", "send_notification", is_flag=True, help="Send a macOS notification when health is not ok")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def health_command(stale_minutes, max_attempts, send_notification, json_output):
    """Inspect daemon launchd state, queue depth, stale running rows, and dead letters."""
    payload = build_daemon_health_report(stale_minutes=stale_minutes, max_attempts=max_attempts)
    if send_notification:
        payload["notification"] = _send_daemon_health_notification(payload)
    status = payload["status"]
    queue = payload["queue"]
    launchd = payload["launchd"]
    stale_running = payload["stale_running"]

    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return

    click.echo(f"status: {status}")
    click.echo(f"launchd_loaded: {launchd['loaded']}")
    click.echo(
        "queue: "
        f"queued={queue.get('queued', 0)} running={queue.get('running', 0)} "
        f"failed={queue.get('failed', 0)} dead_letter={queue.get('dead_letter', 0)}"
    )
    click.echo(f"stale_running: {stale_running.get('count', 0)}")
    for issue in payload["issues"]:
        click.echo(f"{issue['severity'].upper()} {issue['code']}: {issue['message']}")


@daemon_command.group("app")
def app_command():
    """Install/open a macOS graphical daemon health helper app."""
    pass


def _emit_app_payload(payload: dict[str, object], json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
    else:
        action = payload.get("action") or "status"
        click.echo(f"{action}: {'ok' if payload.get('ok', True) else 'failed'}")
        click.echo(f"app: {payload.get('app_path')}")
        click.echo(f"exists: {payload.get('app_exists')}")
        click.echo(f"login_item: {payload.get('login_item_installed')}")
        if payload.get("error"):
            click.echo(str(payload["error"]))
    if payload.get("ok") is False:
        raise click.ClickException(str(payload.get("error") or "daemon app command failed"))


@app_command.command("install")
@click.option("--login-item", is_flag=True, help="Also add the control app as a macOS Login Item")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def app_install_command(login_item, json_output):
    """Compile the clickable macOS daemon health app."""
    _emit_app_payload(install_control_app(login_item=login_item), json_output)


@app_command.command("status")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def app_status_command(json_output):
    """Show control app path and Login Item state."""
    payload = {"ok": True, "action": "status", **control_app_status()}
    _emit_app_payload(payload, json_output)


@app_command.command("open")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def app_open_command(json_output):
    """Open the clickable daemon health app."""
    _emit_app_payload(open_control_app(), json_output)


@app_command.command("uninstall")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def app_uninstall_command(json_output):
    """Remove the clickable daemon health app and Login Item."""
    _emit_app_payload(uninstall_control_app(), json_output)


@daemon_command.command("run")
@click.option("--config", "-c", "config_path", default=None, type=click.Path(path_type=Path), help="Config file path")
@click.option("--once", "run_once", is_flag=True, default=False, help="Process current queue once and exit")
@click.option("--sleep-ms", default=None, type=click.IntRange(250, 60_000), help="Sleep when queue is empty (loop mode)")
@click.option("--max-empty-cycles", default=None, type=click.IntRange(1, 1_000_000), help="Auto exit after N empty loops")
@click.option(
    "--recover-stale-minutes",
    default=None,
    type=click.IntRange(0, 10_080),
    help="At startup, requeue running commands older than this many minutes; 0 disables",
)
@click.option(
    "--max-attempts",
    default=None,
    type=click.IntRange(1, 100),
    help="Move recovered stale commands to dead_letter after this many attempts",
)
@click.option("--verbose", is_flag=True, help="Print per-command trace")
def run_command(config_path, run_once, sleep_ms, max_empty_cycles, recover_stale_minutes, max_attempts, verbose):
    """Process queued commands in a daemon-style loop."""
    daemon_config = None
    if config_path is not None:
        daemon_config = load_config(str(config_path))
        _configure_agent_state(daemon_config)

    if sleep_ms is None:
        sleep_ms = int(os.environ.get("NUDGE_DAEMON_SLEEP_MS", "3000"))
    if sleep_ms < 250:
        sleep_ms = 250
    should_stop = {"value": False}

    def _stop(_signum, _frame):
        should_stop["value"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    empty_count = 0
    processed = 0
    loop_sleep = sleep_ms / 1000

    resolved_recover_stale_minutes = recover_stale_minutes
    if resolved_recover_stale_minutes is None:
        resolved_recover_stale_minutes = _int_from_env("NUDGE_DAEMON_STALE_MINUTES", DEFAULT_DAEMON_STALE_MINUTES)
    resolved_max_attempts = max_attempts
    if resolved_max_attempts is None:
        resolved_max_attempts = _int_from_env("NUDGE_DAEMON_MAX_ATTEMPTS", DEFAULT_DAEMON_MAX_ATTEMPTS)
    if resolved_recover_stale_minutes > 0:
        recovery = recover_stale_running_commands(
            stale_minutes=resolved_recover_stale_minutes,
            max_attempts=resolved_max_attempts,
        )
        if verbose and (recovery["requeued_count"] or recovery["dead_lettered_count"]):
            click.echo(
                "recovered stale commands: "
                f"requeued={recovery['requeued_count']} dead_lettered={recovery['dead_lettered_count']}"
            )

    while not should_stop["value"]:
        command = claim_next_queued_command()
        if command is None:
            empty_count += 1
            if run_once:
                break
            if max_empty_cycles is not None and empty_count >= max_empty_cycles:
                break
            time.sleep(loop_sleep)
            continue

        empty_count = 0
        queue_created_at = command.get("queue_created_at")
        started = time.perf_counter()
        started_at = _now_iso()
        request_id = command["request_id"]
        request_type = command["request_type"]
        payload = command["payload"]

        if verbose:
            click.echo(f"processing {request_id} ({request_type})")

        if not isinstance(payload, dict):
            status = "failed"
            response = {
                "ok": False,
                "request_id": request_id,
                "errors": [{"code": "PAYLOAD_INVALID", "message": "request payload must be object"}],
            }
            exit_code = 1
            error_text = "request payload must be object"
            processed_payload = response
        else:
            try:
                processed_payload, exit_code, error_text = _run_payload(
                    request_type=request_type,
                    payload=payload,
                    config=daemon_config,
                )
            except Exception as exc:  # noqa: BLE001 - daemon isolates individual command failures.
                processed_payload, exit_code, error_text = _exception_payload(
                    request_id=request_id,
                    source=payload.get("source"),
                    exc=exc,
                )
                if verbose:
                    click.echo(traceback.format_exc().rstrip(), err=True)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        queue_wait_ms = _ms_since(queue_created_at, fallback_ms=0)
        total_ms = queue_wait_ms + elapsed_ms
        status = "succeeded" if (exit_code == 0 and bool(processed_payload.get("ok"))) else "failed"

        run_id = log_daemon_run(
            request_id=request_id,
            command_id=request_id,
            request_type=request_type,
            status=status,
            started_at=started_at,
            finished_at=_now_iso(),
            queue_wait_ms=queue_wait_ms,
            processing_ms=elapsed_ms,
            total_ms=total_ms,
            payload_size=command.get("last_payload_size", 0),
            error_text=error_text or _coerce_error_text(processed_payload),
            output_json=processed_payload,
        )

        mark_queued_command_complete(
            request_id=request_id,
            status=status,
            command_id=run_id,
            exit_code=exit_code,
            error=error_text or _coerce_error_text(processed_payload),
            duration_ms=elapsed_ms,
        )

        processed += 1
        if verbose:
            click.echo(f"{request_id}: {status}")
        if run_once:
            break

    if not run_once and processed == 0 and should_stop["value"]:
        click.echo("daemon stopped.")
        return
    if verbose and processed:
        click.echo(f"processed: {processed}")
