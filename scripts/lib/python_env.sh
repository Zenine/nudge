#!/usr/bin/env bash
# shellcheck shell=bash
#
# Nudge 共享的 Python 解释器解析逻辑。
# 由 bin/nudge 与 scripts/verify.sh 共同 source，保证两个入口口径一致。
#
# 解析优先级：
#   1. 显式设置的 NUDGE_PYTHON —— 直接采用，不做任何 .venv 检查。
#   2. 项目内 .venv/bin/python 可执行 —— 采用。
#   3. 完全没有 .venv 目录 —— 回落到系统 python3（贡献者自管环境的正常用法）。
#   4. 有 .venv 目录但解释器缺失/悬空/不可执行 —— 显式报错并返回非零，绝不静默回落。

# 跟随软链接链，输出最终目标路径（即使该目标不存在）。
nudge__resolve_symlink_chain() {
  local path="$1"
  local target
  local dir
  local depth=0

  while [[ -L "$path" ]] && (( depth < 20 )); do
    target="$(readlink "$path")"
    case "$target" in
      /*) path="$target" ;;
      *)
        dir="$(dirname "$path")"
        path="$dir/$target"
        ;;
    esac
    depth=$((depth + 1))
  done

  printf '%s\n' "$path"
}

# 打印 .venv 解释器损坏的诊断信息（写 stderr）。
nudge__report_broken_venv() {
  local venv_dir="$1"
  local venv_py="$2"
  local direct_target
  local final_target

  echo "❌ 检测到项目虚拟环境 ${venv_dir}，但其 Python 解释器不可用。" >&2
  echo "   解释器路径：${venv_py}" >&2

  if [[ -L "$venv_py" && ! -e "$venv_py" ]]; then
    direct_target="$(readlink "$venv_py")"
    final_target="$(nudge__resolve_symlink_chain "$venv_py")"
    echo "   原因：这是一个悬空软链接（symlink 指向的目标已不存在）。" >&2
    if [[ "$final_target" != "$venv_py" && "$final_target" != "$direct_target" ]]; then
      echo "   直接指向：${direct_target}" >&2
      echo "   最终指向：${final_target}（该路径不存在）" >&2
    else
      echo "   直接指向：${direct_target}（该路径不存在）" >&2
    fi
  elif [[ -e "$venv_py" && ! -x "$venv_py" ]]; then
    echo "   原因：文件存在但没有可执行权限。" >&2
  elif [[ ! -e "$venv_py" && ! -L "$venv_py" ]]; then
    echo "   原因：.venv 目录存在，但里面没有 bin/python。" >&2
  else
    echo "   原因：该路径无法作为可执行解释器使用。" >&2
  fi

  echo "   为什么不自动回落到系统 python3：系统解释器通常缺少本项目依赖，" >&2
  echo "   静默回落会让后续失败信息完全指向错误的原因，因此这里直接报错。" >&2
  echo "   修复方式（任选其一）：" >&2
  echo "     1) 重跑安装底座：scripts/bootstrap_mac.sh" >&2
  echo "     2) 重建虚拟环境：rm -rf '${venv_dir}' && python3 -m venv '${venv_dir}' && '${venv_dir}/bin/python' -m pip install -r requirements.txt" >&2
  echo "     3) 临时指定解释器：export NUDGE_PYTHON=/path/to/python3.12" >&2
}

# 解析并在 stdout 输出应使用的 Python 解释器路径。
# 用法：PYTHON_BIN="$(nudge_resolve_python "$ROOT")" || exit 1
nudge_resolve_python() {
  local root="$1"
  local venv_dir="$root/.venv"
  local venv_py="$venv_dir/bin/python"

  if [[ -n "${NUDGE_PYTHON:-}" ]]; then
    printf '%s\n' "$NUDGE_PYTHON"
    return 0
  fi

  if [[ -x "$venv_py" ]]; then
    printf '%s\n' "$venv_py"
    return 0
  fi

  if [[ -d "$venv_dir" ]]; then
    nudge__report_broken_venv "$venv_dir" "$venv_py"
    return 1
  fi

  printf '%s\n' "python3"
}
