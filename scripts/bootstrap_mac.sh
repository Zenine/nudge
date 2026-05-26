#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLE_SILICON_PYTHON="/opt/homebrew/bin/python3"
PY_BIN="${NUDGE_BOOTSTRAP_PYTHON:-}"
VENV_DIR="$ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"

log() {
  echo "=> $*"
}

warn() {
  echo "⚠️  $*"
}

fatal() {
  echo "❌ $*"
  exit 1
}

python_arch() {
  local candidate="$1"
  "$candidate" - <<'PY'
import platform
print(platform.machine())
PY
}

python_version_ok() {
  local candidate="$1"
  "$candidate" - <<'PY'
import sys
print(1 if sys.version_info >= (3, 12) else 0)
PY
}

select_python() {
  local system_arch
  local candidates=()
  local candidate
  local python_arch

  system_arch="$(uname -m)"

  if [[ "$(uname -s)" == "Darwin" && "$system_arch" == "arm64" ]]; then
    candidates+=("$APPLE_SILICON_PYTHON")
  fi

  if command -v python3 >/dev/null 2>&1; then
    candidates+=("$(command -v python3)")
  fi

  for candidate in "${candidates[@]}"; do
    [[ -x "$candidate" ]] || continue

    if [[ "$(python_version_ok "$candidate")" != "1" ]]; then
      continue
    fi

    python_arch="$(python_arch "$candidate")"
    if [[ "$system_arch" == "arm64" && "$python_arch" != "arm64" && "$python_arch" != "arm64e" ]]; then
      warn "跳过 Rosetta Python：$candidate (${python_arch})"
      continue
    fi

    echo "$candidate"
    return 0
  done

  return 1
}

ensure_native_virtualenv() {
  local system_arch
  local venv_arch
  local backup_dir

  [[ -x "$VENV_PY" ]] || return 0

  system_arch="$(uname -m)"
  venv_arch="$(python_arch "$VENV_PY")"

  if [[ "$system_arch" == "arm64" && "$venv_arch" != "arm64" && "$venv_arch" != "arm64e" ]]; then
    backup_dir="${VENV_DIR}.rosetta-backup-$(date +%Y%m%d%H%M%S)"
    warn "现有 .venv 使用的是 ${venv_arch}，将备份到 ${backup_dir} 并重建为 Apple Silicon 环境。"
    mv "$VENV_DIR" "$backup_dir"
  fi
}

log "Nudge 一键安装（Mac）开始"

if [[ "$(uname -s)" != "Darwin" ]]; then
  warn "此脚本为 macOS 优化；如果你在其他系统运行，请按 README 的通用命令安装。"
fi

if [[ -z "$PY_BIN" ]]; then
  if ! PY_BIN="$(select_python)"; then
    fatal "未检测到可用的原生 Python 3.12+。请先安装 Apple Silicon 版 Python（推荐：/opt/homebrew/bin/brew install python），然后重试。"
  fi
fi

if ! command -v "${PY_BIN}" >/dev/null 2>&1 && [[ ! -x "$PY_BIN" ]]; then
  fatal "未检测到 python3。请先在 Mac 上安装 Python 3.12+（推荐：brew install python 或 python.org 安装器），然后重试。"
fi

PY_ARCH="$(python_arch "$PY_BIN")"
if [[ "$(uname -m)" == "arm64" && "$PY_ARCH" != "arm64" && "$PY_ARCH" != "arm64e" ]]; then
  fatal "当前选择的 Python 是 ${PY_ARCH}，会通过 Rosetta 运行。请改用 Apple Silicon 版 Python，或设置 NUDGE_BOOTSTRAP_PYTHON=/opt/homebrew/bin/python3。"
fi

if [[ "$(python_version_ok "$PY_BIN")" != "1" ]]; then
  warn "当前 python3 版本可能低于 3.12（建议 3.12+）。你仍可继续，但项目可能出现兼容性问题。"
fi

cd "${ROOT}"

log "步骤1：创建项目内 Python 隔离环境"
ensure_native_virtualenv
if [[ ! -x "$VENV_PY" ]]; then
  "${PY_BIN}" -m venv "$VENV_DIR"
fi
"$VENV_PY" -m ensurepip --upgrade

log "步骤1.5：安装 Python 依赖到项目 .venv"
"$VENV_PY" -m pip install -r requirements.txt

log "步骤1.6：初始化 config.toml"
if [[ ! -f config.toml ]]; then
  cp config.example.toml config.toml
  echo "已从 config.example.toml 创建 config.toml"
else
  echo "config.toml 已存在，保留现有配置"
fi

log "步骤2：安装 Nudge 命令"
"${ROOT}/scripts/install_cli.sh"

configure_state_dir() {
  local default_dir=".nudge"
  local suggested_sync_dir="$HOME/.local/share/nudge"
  local chosen_dir
  local use_default

  if [ -t 0 ]; then
    read -r -p "是否把本地数据库保存在安装底座默认目录 ${ROOT}/${default_dir}？[Y/n] " use_default
  else
    use_default="y"
  fi

  if [[ "${use_default,,}" == "n" || "${use_default,,}" == "no" ]]; then
    if [ -t 0 ]; then
      read -r -p "请输入本地状态目录（回车使用 ${suggested_sync_dir}）： " chosen_dir
    else
      chosen_dir="${suggested_sync_dir}"
    fi
    chosen_dir="${chosen_dir:-$suggested_sync_dir}"
  else
    chosen_dir="${default_dir}"
  fi

  STATE_DIR_VALUE="$chosen_dir" "$VENV_PY" - <<'PY'
import os
from pathlib import Path

config_path = Path("config.toml")
value = os.environ["STATE_DIR_VALUE"]
line = f'dir = "{value}"'

text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
lines = text.splitlines()
out = []
in_state = False
seen_state = False
state_dir_written = False

for original in lines:
    stripped = original.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        if in_state and not state_dir_written:
            out.append(line)
            state_dir_written = True
        in_state = stripped == "[state]"
        seen_state = seen_state or in_state
        out.append(original)
        continue
    if in_state and (stripped.startswith("dir =") or stripped.startswith("directory =")):
        if not state_dir_written:
            out.append(line)
            state_dir_written = True
        continue
    out.append(original)

if in_state and not state_dir_written:
    out.append(line)
    state_dir_written = True

if not seen_state:
    if out and out[-1].strip():
        out.append("")
    out.extend(["[state]", line])

config_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY

  echo "Nudge 本地状态目录已写入 config.toml: ${chosen_dir}"
}

log "步骤2.5：配置本地状态目录"
configure_state_dir

log "步骤3：基础可用性自检"
NUDGE_CMD="nudge"
if ! command -v nudge >/dev/null 2>&1; then
  warn "当前 shell 未能直接找到 nudge（可能 PATH 未刷新）"
  warn "请执行：export PATH=\"$HOME/.local/bin:\$PATH\""
  warn "然后再执行：nudge --help"
  NUDGE_CMD="${ROOT}/bin/nudge"
else
  NUDGE_CMD="nudge"
fi
"$NUDGE_CMD" --help >/dev/null
echo "nudge 命令入口可用：${NUDGE_CMD} --help 已通过"

if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
  printf '\n环境变量提示：你还没设置 DASHSCOPE_API_KEY。先用一条命令：\n'
  printf '  export DASHSCOPE_API_KEY=\"<你的 key>\"\n'
else
  printf '\n已检测到 DASHSCOPE_API_KEY（环境已就绪）。\n'
fi

if [ -t 0 ]; then
  read -r -p "是否现在跑一次 nudge doctor（检查 Apple 权限并输出修复指引）？[y/N] " run_doctor
else
  run_doctor="n"
fi

if [[ "${run_doctor,,}" == "y" || "${run_doctor,,}" == "yes" ]]; then
  log "步骤4：运行诊断"
  "$NUDGE_CMD" doctor
else
  log "已跳过 nudge doctor；你可稍后执行 nudge doctor 继续初始化"
fi

log "一键安装完成"
echo "接下来可直接尝试：nudge --dry-run \"明天早上8点开会\""
