#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs"
GUI_UID="$(id -u)"

DEFAULT_MORNING_HOUR=7
DEFAULT_MORNING_MINUTE=0
DEFAULT_DAILY_SYNC_HOUR=7
DEFAULT_DAILY_SYNC_MINUTE=15
DEFAULT_EVENING_HOUR=21
DEFAULT_EVENING_MINUTE=30
DEFAULT_DAEMON_SLEEP_MS=3000
DEFAULT_DAEMON_STALE_MINUTES=30
DEFAULT_DAEMON_MAX_ATTEMPTS=3
DEFAULT_DAEMON_MAX_QUEUE_DEPTH=1000

MORNING_LABEL="com.nudge.morning"
DAILY_SYNC_LABEL="com.nudge.daily-sync"
EVENING_LABEL="com.nudge.evening"
DAEMON_LABEL="com.nudge.agent"

MORNING_PLIST="${LAUNCH_DIR}/${MORNING_LABEL}.plist"
DAILY_SYNC_PLIST="${LAUNCH_DIR}/${DAILY_SYNC_LABEL}.plist"
EVENING_PLIST="${LAUNCH_DIR}/${EVENING_LABEL}.plist"
DAEMON_PLIST="${LAUNCH_DIR}/${DAEMON_LABEL}.plist"

NUDGE_CMD="${ROOT}/bin/nudge"
USE_NOTIFY="${NUDGE_BRIEFING_NOTIFY:-1}"

COMMAND="${1:-install}"

NUDGE_CMD_PATH="$NUDGE_CMD"
if [[ ! -x "$NUDGE_CMD_PATH" ]]; then
  if ! command -v nudge >/dev/null 2>&1; then
    echo "未找到可执行的 nudge 命令。请先运行 scripts/install_cli.sh 或 scripts/bootstrap_mac.sh。"
    exit 1
  fi
  NUDGE_CMD_PATH="$(command -v nudge)"
fi

print_usage() {
  cat <<'USAGE'
Usage:
  scripts/bootstrap_launchd.sh [install|uninstall|status|help]

Commands:
  install    生成并加载 morning/daily-sync/evening + daemon（常驻）任务（默认）
  uninstall  卸载并移除四类 launchd 任务
  status    显示任务状态（已加载/未加载）
  help      显示本帮助

Optional env:
  NUDGE_MORNING_HOUR / NUDGE_MORNING_MINUTE
  NUDGE_DAILY_SYNC_HOUR / NUDGE_DAILY_SYNC_MINUTE
  NUDGE_EVENING_HOUR / NUDGE_EVENING_MINUTE
  NUDGE_DAEMON_SLEEP_MS
  NUDGE_DAEMON_STALE_MINUTES
  NUDGE_DAEMON_MAX_ATTEMPTS
  NUDGE_DAEMON_MAX_QUEUE_DEPTH
  NUDGE_BRIEFING_NOTIFY=1|0
USAGE
}

check_platform() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "该脚本仅针对 macOS 的 launchd 设计。当前不是 Darwin 平台。"
    exit 1
  fi
}

safe_mkdir() {
  mkdir -p "$LAUNCH_DIR" "$LOG_DIR"
}

render_daemon_plist() {
  local plist_path="$1"
  local label="$2"

  cat > "$plist_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${NUDGE_CMD_PATH}</string>
        <string>daemon</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${ROOT}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/${label}.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/${label}.err.log</string>
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
        <string>${NUDGE_DAEMON_SLEEP_MS:-$DEFAULT_DAEMON_SLEEP_MS}</string>
        <key>NUDGE_DAEMON_STALE_MINUTES</key>
        <string>${NUDGE_DAEMON_STALE_MINUTES:-$DEFAULT_DAEMON_STALE_MINUTES}</string>
        <key>NUDGE_DAEMON_MAX_ATTEMPTS</key>
        <string>${NUDGE_DAEMON_MAX_ATTEMPTS:-$DEFAULT_DAEMON_MAX_ATTEMPTS}</string>
        <key>NUDGE_DAEMON_MAX_QUEUE_DEPTH</key>
        <string>${NUDGE_DAEMON_MAX_QUEUE_DEPTH:-$DEFAULT_DAEMON_MAX_QUEUE_DEPTH}</string>
    </dict>
</dict>
</plist>
EOF
}

render_daily_sync_plist() {
  local plist_path="$1"
  local label="$2"
  local hour="$3"
  local minute="$4"

  cat > "$plist_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${NUDGE_CMD_PATH}</string>
        <string>daily</string>
        <string>sync</string>
        <string>--apply</string>
        <string>--json</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${ROOT}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${hour}</integer>
        <key>Minute</key>
        <integer>${minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/${label}.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/${label}.err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
}


render_plist() {
  local plist_path="$1"
  local label="$2"
  local briefing_type="$3"
  local hour="$4"
  local minute="$5"

  cat > "$plist_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${NUDGE_CMD_PATH}</string>
        <string>briefing</string>
        <string>${briefing_type}</string>
$(if [[ "$USE_NOTIFY" == "1" ]]; then
echo '        <string>--notify</string>'
fi)
    </array>
    <key>WorkingDirectory</key>
    <string>${ROOT}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${hour}</integer>
        <key>Minute</key>
        <integer>${minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/${label}.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/${label}.err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
}

load_or_unload_agent() {
  local plist_path="$1"
  local op="$2" # install / uninstall

  case "$op" in
    install)
      if launchctl bootstrap "gui/${GUI_UID}" "$plist_path" 2>/dev/null; then
        return 0
      fi
      # Fallback for older launchctl semantics
      launchctl unload -w "$plist_path" >/dev/null 2>&1 || true
      if launchctl load -w "$plist_path" >/dev/null 2>&1; then
        return 0
      fi
      echo "无法加载 launchd 任务：$plist_path"
      return 1
      ;;
    uninstall)
      if launchctl bootout "gui/${GUI_UID}" "$plist_path" 2>/dev/null; then
        return 0
      fi
      launchctl unload -w "$plist_path" >/dev/null 2>&1 || true
      ;;
  esac
}

check_label() {
  local label="$1"
  if launchctl print "gui/${GUI_UID}/${label}" >/dev/null 2>&1; then
    echo "  ${label}: loaded"
  else
    echo "  ${label}: not loaded"
  fi
}

cleanup_plist() {
  local plist_path="$1"
  if [[ -f "$plist_path" ]]; then
    rm -f "$plist_path"
  fi
}

install_agents() {
  local morning_hour="${NUDGE_MORNING_HOUR:-$DEFAULT_MORNING_HOUR}"
  local morning_minute="${NUDGE_MORNING_MINUTE:-$DEFAULT_MORNING_MINUTE}"
  local daily_sync_hour="${NUDGE_DAILY_SYNC_HOUR:-$DEFAULT_DAILY_SYNC_HOUR}"
  local daily_sync_minute="${NUDGE_DAILY_SYNC_MINUTE:-$DEFAULT_DAILY_SYNC_MINUTE}"
  local evening_hour="${NUDGE_EVENING_HOUR:-$DEFAULT_EVENING_HOUR}"
  local evening_minute="${NUDGE_EVENING_MINUTE:-$DEFAULT_EVENING_MINUTE}"
  local daemon_sleep_ms="${NUDGE_DAEMON_SLEEP_MS:-$DEFAULT_DAEMON_SLEEP_MS}"
  local daemon_stale_minutes="${NUDGE_DAEMON_STALE_MINUTES:-$DEFAULT_DAEMON_STALE_MINUTES}"
  local daemon_max_attempts="${NUDGE_DAEMON_MAX_ATTEMPTS:-$DEFAULT_DAEMON_MAX_ATTEMPTS}"
  local daemon_max_queue_depth="${NUDGE_DAEMON_MAX_QUEUE_DEPTH:-$DEFAULT_DAEMON_MAX_QUEUE_DEPTH}"

  safe_mkdir

  render_plist "$MORNING_PLIST" "$MORNING_LABEL" "morning" "$morning_hour" "$morning_minute"
  render_daily_sync_plist "$DAILY_SYNC_PLIST" "$DAILY_SYNC_LABEL" "$daily_sync_hour" "$daily_sync_minute"
  render_plist "$EVENING_PLIST" "$EVENING_LABEL" "evening" "$evening_hour" "$evening_minute"
  render_daemon_plist "$DAEMON_PLIST" "$DAEMON_LABEL"

  load_or_unload_agent "$MORNING_PLIST" install
  load_or_unload_agent "$DAILY_SYNC_PLIST" install
  load_or_unload_agent "$EVENING_PLIST" install
  load_or_unload_agent "$DAEMON_PLIST" install

  echo "已安装并加载："
  check_label "$MORNING_LABEL"
  check_label "$DAILY_SYNC_LABEL"
  check_label "$EVENING_LABEL"
  check_label "$DAEMON_LABEL"
  echo
  echo "日志输出："
  echo "  ${LOG_DIR}/${MORNING_LABEL}.out.log"
  echo "  ${LOG_DIR}/${DAILY_SYNC_LABEL}.out.log"
  echo "  ${LOG_DIR}/${EVENING_LABEL}.out.log"
  echo "  ${LOG_DIR}/${MORNING_LABEL}.err.log"
  echo "  ${LOG_DIR}/${DAILY_SYNC_LABEL}.err.log"
  echo "  ${LOG_DIR}/${EVENING_LABEL}.err.log"
  echo "  ${LOG_DIR}/${DAEMON_LABEL}.out.log"
  echo "  ${LOG_DIR}/${DAEMON_LABEL}.err.log"
  echo
  echo "daemon 参数："
  echo "  sleep_ms=${daemon_sleep_ms}"
  echo "  stale_minutes=${daemon_stale_minutes}"
  echo "  max_attempts=${daemon_max_attempts}"
  echo "  max_queue_depth=${daemon_max_queue_depth}"
}

uninstall_agents() {
  load_or_unload_agent "$MORNING_PLIST" uninstall
  load_or_unload_agent "$DAILY_SYNC_PLIST" uninstall
  load_or_unload_agent "$EVENING_PLIST" uninstall
  load_or_unload_agent "$DAEMON_PLIST" uninstall
  cleanup_plist "$MORNING_PLIST"
  cleanup_plist "$DAILY_SYNC_PLIST"
  cleanup_plist "$EVENING_PLIST"
  cleanup_plist "$DAEMON_PLIST"
  echo "已卸载并移除 morning/daily-sync/evening/daemon 任务。"
}

show_status() {
  echo "Launchd 状态检查："
  check_label "$MORNING_LABEL"
  check_label "$DAILY_SYNC_LABEL"
  check_label "$EVENING_LABEL"
  check_label "$DAEMON_LABEL"
}

case "$COMMAND" in
  install|uninstall|status|help|-h|--help)
    ;;
  *)
    echo "未知命令：$COMMAND"
    print_usage
    exit 1
    ;;
esac

check_platform

case "$COMMAND" in
  help|-h|--help)
    print_usage
    ;;
  install)
    install_agents
    ;;
  uninstall)
    uninstall_agents
    ;;
  status)
    show_status
    ;;
esac
