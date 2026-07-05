# TestPyPI Release Rehearsal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不发布正式 PyPI、不打 tag、不推送 release 的前提下，完成 `nudge-ai-life-coach` 的 TestPyPI 预演，并把结果反馈到发布文档与 TODO/CHANGELOG。

**Architecture:** 采用“本地构建校验 → TestPyPI 上传 → 干净虚拟环境安装验证 → 文档状态更新”的发布闸门。仓库脚本只负责离线检查；需要凭证和外网的上传步骤由维护者手动执行，避免把 token、上传动作或账号信息写入仓库。

**Tech Stack:** Python 3.12+、`build`、`twine`、TestPyPI、pip/venv、现有 `scripts/verify.sh` 与 `scripts/check_package.sh`。

---

## 官方参考

- PyPA TestPyPI 指南：`twine upload --repository testpypi dist/*`，安装测试可用 `--index-url https://test.pypi.org/simple/`，依赖需要时加 `--extra-index-url https://pypi.org/simple/`。
- Twine 文档：推荐流程是 `python -m build`，上传 TestPyPI 验证，再上传正式 PyPI。

## 文件职责

- `docs/releasing.md`：发布 checklist 的权威文档。TestPyPI 预演完成后只更新状态与已验证命令，不写 token。
- `CHANGELOG.md`：如果 TestPyPI 预演通过，记录“TestPyPI rehearsal completed”；不能写成正式 PyPI 已发布。
- `TODO.md`：将“PyPI 发布准备”拆成“TestPyPI 已验证 / 正式 PyPI 未发布 / Homebrew 未发布”的准确状态。
- `pyproject.toml`：只在需要临时版本号时修改；正式提交前必须决定是否保留版本号变更。
- 不修改 `scripts/check_package.sh`，除非预演发现离线包检查漏项。

## 关键风险与策略

- TestPyPI 与正式 PyPI 的版本文件不可覆盖；如果 `0.5.1` 已在 TestPyPI 上传过且文件名冲突，使用临时预演版本，例如 `0.5.1.post1` 或 `0.5.1.devYYYYMMDD`，不要强行复用旧 artifact。
- TestPyPI 账号和正式 PyPI 账号/Token 是分开的；优先使用 TestPyPI token，用户名用 `__token__`，密码输入 token 值。不要把 token 放入命令行历史、文档或 git。
- TestPyPI 可能没有项目依赖包，所以安装验证使用 `--extra-index-url https://pypi.org/simple/` 允许依赖从正式 PyPI 下载。
- 预演只验证包装与安装链路，不代表正式发布完成；README 不能改成 `pipx install` 当前已可用。

---

### Task 1: 本地发布前快照与离线验证

**Files:**
- Read: `pyproject.toml`
- Read: `CHANGELOG.md`
- Read: `docs/releasing.md`
- No writes expected

- [ ] **Step 1: 确认工作区干净**

Run:

```bash
git status --short
git log -3 --oneline
```

Expected:

```text
# git status --short 无输出
1728bf0 chore: prepare package release checks
f3fa419 fix: validate health daily summaries
bb81f61 feat: improve schedule and reminder safety
```

如果工作区不干净，停止并先处理未提交改动。

- [ ] **Step 2: 确认版本与包名**

Run:

```bash
python - <<'PY'
from pathlib import Path
text = Path('pyproject.toml').read_text()
for key in ('name =', 'version =', 'license ='):
    print(next(line for line in text.splitlines() if line.strip().startswith(key)))
PY
```

Expected:

```text
name = "nudge-ai-life-coach"
version = "0.5.1"
license = "AGPL-3.0-only"
```

- [ ] **Step 3: 运行完整离线验证**

Run:

```bash
scripts/verify.sh
```

Expected:

```text
Nudge public verification passed
```

必须确认测试、compileall、CLI smoke、docs audit、packaging checks 全通过。

---

### Task 2: 准备上传工具与凭证，不落盘进仓库

**Files:**
- No repository writes

- [ ] **Step 1: 确认 `build` 与 `twine` 可用**

Run:

```bash
python - <<'PY'
import importlib.util
missing = [name for name in ('build', 'twine') if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit('missing modules: ' + ', '.join(missing))
print('build and twine available')
PY
```

Expected:

```text
build and twine available
```

如果缺模块，只在当前开发环境安装，不修改仓库依赖：

```bash
python -m pip install --upgrade build twine
```

- [ ] **Step 2: 确认 TestPyPI token 获取方式**

人工操作：

1. 登录 `https://test.pypi.org/`。
2. 在 Account settings 创建 API token。
3. 如果项目在 TestPyPI 尚不存在，首次上传通常需要 account-wide token；项目创建后再改用 project-scoped token。
4. 不把 token 写入仓库、issue、PR、shell 脚本或聊天日志。

- [ ] **Step 3: 选择凭证传递方式**

推荐交互输入，避免 token 进入 shell history：

```bash
python -m twine upload --repository testpypi dist/*
# username: __token__
# password: 粘贴 TestPyPI API token；终端不会显示字符
```

如必须使用环境变量，只在当前 shell 设置，命令结束后立即清理：

```bash
export TWINE_USERNAME=__token__
read -rsp 'TestPyPI token: ' TWINE_PASSWORD; echo
python -m twine upload --repository testpypi dist/*
unset TWINE_USERNAME TWINE_PASSWORD
```

---

### Task 3: 构建并检查待上传 artifacts

**Files:**
- Generated ignored paths: `dist/`, `build/`, `*.egg-info/`
- No tracked writes expected

- [ ] **Step 1: 重新构建 artifacts**

Run:

```bash
scripts/check_package.sh
```

Expected:

```text
Successfully built nudge_ai_life_coach-0.5.1.tar.gz and nudge_ai_life_coach-0.5.1-py3-none-any.whl
Package contents look public-safe
```

- [ ] **Step 2: 用 twine 检查 metadata**

Run:

```bash
python -m twine check dist/*
```

Expected:

```text
Checking dist/nudge_ai_life_coach-0.5.1-py3-none-any.whl: PASSED
Checking dist/nudge_ai_life_coach-0.5.1.tar.gz: PASSED
```

如果失败，停止，修复 metadata 后回到 Task 1。

- [ ] **Step 3: 确认 artifacts 数量**

Run:

```bash
python - <<'PY'
from pathlib import Path
artifacts = sorted(p.name for p in Path('dist').iterdir())
print('\n'.join(artifacts))
assert artifacts == [
    'nudge_ai_life_coach-0.5.1-py3-none-any.whl',
    'nudge_ai_life_coach-0.5.1.tar.gz',
]
PY
```

Expected: 只列出这两个文件且断言通过。

---

### Task 4: 上传到 TestPyPI

**Files:**
- No repository writes

- [ ] **Step 1: 执行 TestPyPI 上传**

Run:

```bash
python -m twine upload --repository testpypi dist/*
```

Expected:

```text
Uploading distributions to https://test.pypi.org/legacy/
Uploading nudge_ai_life_coach-0.5.1-py3-none-any.whl
Uploading nudge_ai_life_coach-0.5.1.tar.gz
View at:
https://test.pypi.org/project/nudge-ai-life-coach/0.5.1/
```

如果返回文件已存在：

1. 停止，不删除 TestPyPI 文件。
2. 决定是否 bump 临时预演版本。
3. 若 bump，修改 `pyproject.toml` 到 `0.5.1.post1` 或 `0.5.1.devYYYYMMDD`，同步 `CHANGELOG.md` 说明这是 TestPyPI-only rehearsal，然后回到 Task 1。

- [ ] **Step 2: 等待 TestPyPI 索引可见**

人工打开：

```text
https://test.pypi.org/project/nudge-ai-life-coach/
```

Expected: 页面显示上传的版本、wheel、sdist。若短时间不可见，等待 1-2 分钟再刷新。

---

### Task 5: 干净环境安装验证

**Files:**
- Temporary path only: `/tmp/nudge-testpypi-venv`
- No repository writes

- [ ] **Step 1: 创建干净虚拟环境**

Run:

```bash
rm -rf /tmp/nudge-testpypi-venv
python -m venv /tmp/nudge-testpypi-venv
/tmp/nudge-testpypi-venv/bin/python -m pip install --upgrade pip
```

Expected: pip 升级成功。

- [ ] **Step 2: 从 TestPyPI 安装 Nudge，依赖从正式 PyPI 补齐**

Run:

```bash
/tmp/nudge-testpypi-venv/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  nudge-ai-life-coach==0.5.1
```

Expected: 安装 `nudge-ai-life-coach==0.5.1` 成功，并安装 `click`、`PyYAML`、`openai`、`anthropic`、`defusedxml` 等依赖。

- [ ] **Step 3: 运行安装后 smoke tests**

Run:

```bash
/tmp/nudge-testpypi-venv/bin/nudge --help
/tmp/nudge-testpypi-venv/bin/nudge doctor --help
/tmp/nudge-testpypi-venv/bin/nudge docs audit --json
/tmp/nudge-testpypi-venv/bin/nudge skills list
```

Expected:

- `nudge --help` 输出命令列表。
- `nudge doctor --help` 输出 doctor 命令帮助。
- `nudge docs audit --json` 返回 JSON，且不要求 Apple 权限。
- `nudge skills list` 能列出内置 skills，证明 YAML 包数据可用。

- [ ] **Step 4: 验证 Swift 包数据存在**

Run:

```bash
/tmp/nudge-testpypi-venv/bin/python - <<'PY'
from importlib.resources import files
required = [
    files('nudge.apple') / 'eventkit_calendar_events.swift',
    files('nudge.apple') / 'eventkit_reminders_due_today.swift',
    files('nudge.apple') / 'eventkit_reminders_mutate.swift',
    files('nudge.skills') / 'builtins' / 'strength-basics-12w.yaml',
]
for path in required:
    print(path, path.is_file())
    assert path.is_file(), path
PY
```

Expected: 四行均以 `True` 结束。

- [ ] **Step 5: 清理临时环境**

Run:

```bash
rm -rf /tmp/nudge-testpypi-venv
```

Expected: 命令成功。

---

### Task 6: 记录预演结果，但不标记正式发布

**Files:**
- Modify: `docs/releasing.md`
- Modify: `CHANGELOG.md`
- Modify: `TODO.md`

- [ ] **Step 1: 更新 `docs/releasing.md` 的 TestPyPI 状态**

在 “Optional TestPyPI rehearsal” 小节下追加一段：

```markdown
### Last TestPyPI rehearsal

- Date: 2026-07-05
- Version: `0.5.1`
- Result: passed
- Verified commands:
  - `scripts/verify.sh`
  - `python -m twine check dist/*`
  - `python -m twine upload --repository testpypi dist/*`
  - clean-venv install from TestPyPI with PyPI dependency fallback
  - installed CLI smoke checks: `nudge --help`, `nudge doctor --help`, `nudge docs audit --json`, `nudge skills list`
- Notes: This was a TestPyPI rehearsal only; the package is still not published to production PyPI.
```

如果使用了临时版本，把 `Version` 改成实际上传版本，并注明正式版本仍未发布。

- [ ] **Step 2: 更新 `CHANGELOG.md`**

在 `0.5.1` 的 Notes 下追加：

```markdown
- TestPyPI rehearsal completed for packaging/install validation; production PyPI/Homebrew release is still pending.
```

不要写“已发布到 PyPI”。

- [ ] **Step 3: 更新 `TODO.md`**

把分发项状态改为：

```markdown
  - 状态:2026-07-05 已完成 PyPI 发布准备与 TestPyPI 预演;正式 PyPI/Homebrew 发布仍未完成。
```

如果 TestPyPI 失败，则改为：

```markdown
  - 状态:2026-07-05 已完成 PyPI 发布准备;TestPyPI 预演失败/未完成,正式 PyPI/Homebrew 发布仍未完成。阻塞: <一句话写明原因>。
```

- [ ] **Step 4: 运行文档与完整验证**

Run:

```bash
nudge docs audit --json
scripts/verify.sh
```

Expected:

```text
Nudge public verification passed
```

- [ ] **Step 5: 提交 TestPyPI 预演记录**

Run:

```bash
git add docs/releasing.md CHANGELOG.md TODO.md
git commit -m "docs: record TestPyPI release rehearsal"
```

Expected: pre-commit 再次运行 `scripts/verify.sh` 并通过。

---

### Task 7: 决策是否进入正式 PyPI 发布

**Files:**
- No writes until用户明确确认正式发布

- [ ] **Step 1: 汇报预演结果**

向用户汇报：

```text
TestPyPI 预演结果：通过/失败
上传版本：<version>
安装验证：通过/失败
包数据验证：通过/失败
正式 PyPI：尚未发布
Homebrew：尚未发布
```

- [ ] **Step 2: 请求正式发布确认**

只有用户明确确认“发布正式 PyPI”后，才能运行：

```bash
python -m twine upload dist/*
```

未确认前不得上传正式 PyPI、不得打 tag、不得创建 GitHub Release、不得更新 README 为正式 `pipx install` 路径。

---

## Self-review

- Spec coverage: 覆盖本地验证、凭证边界、构建、TestPyPI 上传、干净环境安装、包数据验证、文档记录、正式发布确认。
- Placeholder scan: 无 TBD/TODO/“稍后实现”；每一步都有具体命令与期望结果。
- Safety: 明确禁止提交 token、禁止正式 PyPI/Homebrew/tag/release，TestPyPI 上传为唯一外部写操作且需要人工凭证。
