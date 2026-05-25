"""macOS graphical helper app for daemon health and logs."""

from __future__ import annotations

import platform
import shlex
import subprocess
from pathlib import Path


APP_NAME = "Nudge Daemon Health"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _nudge_cmd() -> Path:
    wrapper = _repo_root() / "bin" / "nudge"
    return wrapper if wrapper.exists() else Path("nudge")


def _paths() -> dict[str, Path]:
    home = Path.home()
    return {
        "app_path": home / "Applications" / f"{APP_NAME}.app",
        "script_path": home / ".nudge" / f"{APP_NAME}.applescript",
        "out_log_path": home / "Library" / "Logs" / "com.nudge.agent.out.log",
        "err_log_path": home / "Library" / "Logs" / "com.nudge.agent.err.log",
    }


def _supported() -> bool:
    return platform.system() == "Darwin"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _system_profile_cmd() -> str:
    return (
        'printf "系统：macOS %s / %s / %s" '
        '"$(sw_vers -productVersion 2>/dev/null || echo unknown)" '
        '"$(sysctl -n hw.model 2>/dev/null || echo unknown)" '
        '"$(uname -m 2>/dev/null || echo unknown)"'
    )


def render_control_app_script() -> str:
    """Return AppleScript source for the clickable daemon control app."""
    paths = _paths()
    nudge_cmd = shlex.quote(str(_nudge_cmd()))
    out_log = shlex.quote(str(paths["out_log_path"]))
    err_log = shlex.quote(str(paths["err_log_path"]))
    restart_cmd = f"{nudge_cmd} daemon launchd restart"
    health_cmd = f"{nudge_cmd} daemon health"
    open_logs_cmd = f"touch {out_log} {err_log}; open -R {err_log}"
    system_profile_cmd = _system_profile_cmd()

    return f"""set systemProfile to do shell script "{_escape_applescript(system_profile_cmd)}"
set healthText to do shell script "{_escape_applescript(health_cmd)}"
set dialogText to systemProfile & return & return & healthText
set buttonChoice to button returned of (display dialog dialogText buttons {{"打开日志", "重启 daemon", "关闭"}} default button "关闭" with title "Nudge Daemon Health")
if buttonChoice is "打开日志" then
    do shell script "{_escape_applescript(open_logs_cmd)}"
else if buttonChoice is "重启 daemon" then
    set restartText to do shell script "{_escape_applescript(restart_cmd)}"
    display dialog restartText buttons {{"好"}} default button "好" with title "Nudge Daemon Health"
end if
"""


def _login_item_script(action: str, app_path: Path | None = None) -> str:
    if action == "exists":
        return f'tell application "System Events" to get exists login item "{APP_NAME}"'
    if action == "add" and app_path is not None:
        return (
            'tell application "System Events"\n'
            f'    if exists login item "{APP_NAME}" then delete login item "{APP_NAME}"\n'
            f'    make login item at end with properties {{path:"{_escape_applescript(str(app_path))}", hidden:false, name:"{APP_NAME}"}}\n'
            "end tell"
        )
    if action == "remove":
        return (
            'tell application "System Events"\n'
            f'    if exists login item "{APP_NAME}" then delete login item "{APP_NAME}"\n'
            "end tell"
        )
    raise ValueError(f"unsupported login item action: {action}")


def _login_item_installed() -> bool:
    if not _supported():
        return False
    result = _run(["osascript", "-e", _login_item_script("exists")])
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def control_app_status() -> dict[str, object]:
    paths = _paths()
    return {
        "supported": _supported(),
        "app_name": APP_NAME,
        "app_path": str(paths["app_path"]),
        "script_path": str(paths["script_path"]),
        "app_exists": paths["app_path"].exists(),
        "login_item_installed": _login_item_installed(),
        "out_log_path": str(paths["out_log_path"]),
        "err_log_path": str(paths["err_log_path"]),
    }


def install_control_app(*, login_item: bool = False) -> dict[str, object]:
    if not _supported():
        return {"ok": False, "action": "install", "error": "macOS only", **control_app_status()}

    paths = _paths()
    paths["app_path"].parent.mkdir(parents=True, exist_ok=True)
    paths["script_path"].parent.mkdir(parents=True, exist_ok=True)
    paths["script_path"].write_text(render_control_app_script(), encoding="utf-8")

    result = _run(["osacompile", "-o", str(paths["app_path"]), str(paths["script_path"])])
    if result.returncode != 0:
        return {
            "ok": False,
            "action": "install",
            "error": (result.stderr or result.stdout or "").strip(),
            **control_app_status(),
        }

    login_result = None
    if login_item:
        login_result = _run(["osascript", "-e", _login_item_script("add", paths["app_path"])])

    return {
        "ok": login_result is None or login_result.returncode == 0,
        "action": "install",
        "login_item_requested": login_item,
        "error": None if login_result is None or login_result.returncode == 0 else (login_result.stderr or login_result.stdout or "").strip(),
        **control_app_status(),
    }


def open_control_app() -> dict[str, object]:
    paths = _paths()
    if not paths["app_path"].exists():
        return {"ok": False, "action": "open", "error": "control app is not installed", **control_app_status()}
    result = _run(["open", str(paths["app_path"])])
    return {
        "ok": result.returncode == 0,
        "action": "open",
        "error": None if result.returncode == 0 else (result.stderr or result.stdout or "").strip(),
        **control_app_status(),
    }


def uninstall_control_app() -> dict[str, object]:
    paths = _paths()
    if _supported():
        _run(["osascript", "-e", _login_item_script("remove")])
    if paths["app_path"].exists():
        if paths["app_path"].is_dir():
            import shutil

            shutil.rmtree(paths["app_path"])
        else:
            paths["app_path"].unlink()
    if paths["script_path"].exists():
        paths["script_path"].unlink()
    return {"ok": True, "action": "uninstall", **control_app_status()}
