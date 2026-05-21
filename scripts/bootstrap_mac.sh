#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="python3"
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

log "Nudge 一键安装（Mac）开始"

if [[ "$(uname -s)" != "Darwin" ]]; then
  warn "此脚本为 macOS 优化；如果你在其他系统运行，请按 README 的通用命令安装。"
fi

if ! command -v "${PY_BIN}" >/dev/null 2>&1; then
  fatal "未检测到 python3。请先在 Mac 上安装 Python 3.12+（推荐：brew install python 或 python.org 安装器），然后重试。"
fi

PY_OK="$(
  ${PY_BIN} - <<'PY'
import sys
print(1 if sys.version_info >= (3, 12) else 0)
PY
)"

if [[ "${PY_OK}" != "1" ]]; then
  warn "当前 python3 版本可能低于 3.12（建议 3.12+）。你仍可继续，但项目可能出现兼容性问题。"
fi

cd "${ROOT}"

log "步骤1：创建项目内 Python 隔离环境"
if [[ ! -x "$VENV_PY" ]]; then
  "${PY_BIN}" -m venv "$VENV_DIR"
fi
"$VENV_PY" -m ensurepip --upgrade

log "步骤1.5：安装 Python 依赖到项目 .venv"
"$VENV_PY" -m pip install -r requirements.txt

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
