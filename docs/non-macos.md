# 非 macOS / dry-run / parse-only 评估指南

Nudge 的核心目标是把自然语言或结构化计划转换成 Apple Calendar、Reminders、Notes 和 Clock 动作。因此需要先明确边界：**真实写入 Apple Calendar / Reminders / Notes / Clock 是 macOS 专属能力**，并且依赖本机 Apple 应用、自动化/访问权限和用户确认的配置。Linux、Windows、容器或 CI 环境可以评估纯逻辑与解析链路，但不能完成真实 Apple 写入。

本文面向非 Mac 用户、Linux CI、贡献者和只想先安全试用的人，说明哪些路径可以评估，哪些命令会因为平台或 Apple 权限不可用而失败。完整命令参考见 [`docs/commands.md`](commands.md)，架构与数据流见 [`docs/architecture.md`](architecture.md)，公开示例见 [`examples/README.md`](../examples/README.md)。

## 可在非 Mac 上评估的内容

非 macOS 环境适合验证“输入是否能被 Nudge 理解”和“结构化契约是否符合预期”，包括：

- **文档审计**：`bin/nudge docs audit --json` 是只读命令，不写 Apple、不写 SQLite，适合在任意平台检查公开文档链接和陈旧度。
- **纯 Python 测试**：`python -m pytest tests/ -q` 或项目统一入口 `scripts/verify.sh` 可验证大部分解析、状态、契约和安全边界；其中 Apple 真实权限相关路径通常通过离线测试或 help smoke test 覆盖。
- **JSON/YAML 示例解析**：`examples/agent/*.json`、`examples/mcp/*.jsonl`、`examples/skills/*.yaml` 使用占位符，可在本地解析检查，确认结构化输入格式。
- **Skills validate / dry-run**：`nudge skills validate ...` 与 `nudge skills dry-run ...` 用于检查 Skill spec 和预览候选动作；dry-run 不写 Apple。
- **agent/MCP dry-run JSON 契约**：`nudge agent apply --dry-run --json --file ...` 以及 MCP `apply_apple_actions` 的 `dry_run: true` 可验证结构化 action、`request_id` 和 dry-run 响应格式。
- **配置 LLM 后的自然语言 dry-run**：如果已经配置可用 LLM provider，可以运行 `nudge do --dry-run --json "..."` 或 `nudge --dry-run "..."` 检查自然语言解析结果；但非 Mac 上仍不能执行真实 Apple 写入。

## 通用 shell 评估流程

以下示例使用通用 POSIX shell，适合 Linux、CI 或临时开发环境。命令只使用公开仓库路径和占位符，不需要真实 API key。

### 1. 安装依赖

建议使用 Python 3.12+。如果不想修改系统 Python，可使用虚拟环境：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果系统命令只有 `python3`，请先确认版本满足项目要求：

```bash
python3 - <<'PY'
import sys
print(sys.version)
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
```

### 2. 运行文档审计

```bash
bin/nudge docs audit --json
```

该命令应只输出审计 JSON，不会写 Apple，也不会修改仓库文件。它适合作为非 Mac 的第一条 smoke test。

### 3. 运行项目验证入口

```bash
scripts/verify.sh
```

`verify.sh` 会运行测试、Python 编译检查、CLI help smoke checks 和文档审计。它不会主动创建 Apple Calendar/Reminders/Notes/Clock 项；若未来测试覆盖扩展到平台相关检查，请以命令输出为准。

### 4. 解析公开 JSON / YAML 示例

JSON 示例可直接用标准库检查：

```bash
python -m json.tool examples/agent/apply-request.json >/dev/null
```

JSONL 示例可逐行解析：

```bash
python - <<'PY'
import json
from pathlib import Path
for line_no, line in enumerate(Path('examples/mcp/apply_apple_actions.jsonl').read_text().splitlines(), 1):
    if line.strip():
        json.loads(line)
print('JSONL OK')
PY
```

Skill YAML 模板可用 PyYAML 解析：

```bash
python - <<'PY'
from pathlib import Path
import yaml
for path in Path('examples/skills').glob('*.yaml'):
    yaml.safe_load(path.read_text())
    print(f'YAML OK: {path}')
PY
```

如果想进一步验证 Skill spec，可运行：

```bash
bin/nudge skills validate examples/skills/custom-skill-template.yaml
bin/nudge skills dry-run examples/skills/custom-skill-template.yaml \
  --context examples/skills/context.example.json --weeks 1
```

## 安全地只看输出

非 Mac 或首次评估时，请坚持“只预览、不写入”：

- CLI 自然语言路径使用 `--dry-run`，例如 `bin/nudge do --dry-run --json "明天下午 3 点项目同步"`。
- 需要确认开关的命令保持默认预览，不传 `--apply`；例如 `review weekly --adapt --dry-run`，不要改成 `--apply`。
- agent/MCP 请求中显式设置 `dry_run: true`，并先使用 `nudge agent apply --dry-run --json --file ...`。
- 不要在公开示例、临时请求或命令历史里传真实 token、API key、OAuth 凭证、个人健康数据、真实日历内容或机器专属配置。
- 示例里的 `<LOCAL_AUTH_TOKEN>`、`request-...-demo-...`、`Personal`、`Tasks` 都是占位符；请不要把自己的真实私密值提交到仓库。

## 可能在非 Mac 或无权限环境失败的命令

以下命令本身是项目能力的一部分，但在 Linux、Windows、容器、CI 或未授权的 macOS 上可能失败，原因通常是 Apple App 不存在、读取权限缺失、自动化权限未授权或平台桥接不可用：

- `nudge doctor` 的 Apple checks：Calendar、Reminders、Mail、Notes、Clock、Shortcuts 或自动化权限检查可能报告失败或不可用。
- 真实 `nudge do ...` / `nudge agent apply ...` / MCP `apply_apple_actions`：不带 dry-run、带真实 `request_id` 且实际执行时，会尝试写 Apple Calendar/Reminders/Notes/Clock。
- `nudge reminders sync-completed --apply` 和 `nudge reminders backfill-ids --apply`：需要读取或更新 Apple Reminders。
- `nudge schedule ...`：需要读取 Apple Calendar 才能找空档。
- `nudge briefing morning` / `nudge briefing evening`：可能读取 Calendar、Reminders、Mail 等本机 Apple 数据源；`--notify` 还可能依赖 macOS 通知能力。
- `nudge daily sync` 中的 Reminders 同步路径：读取 Reminders 需要对应权限；如果只想做文档审计或 Health 文件解析，应明确使用不会触发 Apple 读取的选项或仅运行 docs audit。
- `nudge daemon launchd ...`、launchd bootstrap 脚本和本机通知相关能力：这些是 macOS 用户级自动化入口，非 Mac 不适用。

如果只是评估解析能力，请优先选择上文的 docs audit、pytest、示例解析、skills validate/dry-run、agent/MCP dry-run 和自然语言 `--dry-run`。

## 与示例和架构文档的关系

- [`examples/README.md`](../examples/README.md) 说明公开示例的安全边界、占位符和建议上手顺序。
- [`docs/commands.md`](commands.md) 按命令列出 Apple 写入、本地 SQLite 写入和 macOS/Apple 权限要求。
- [`docs/architecture.md`](architecture.md) 解释自然语言、agent/MCP、Skills、Health/daily/review 如何经过 JSON 契约、Apple adapters 和 SQLite 状态层。

建议阅读顺序：先运行 `docs audit` 和示例解析确认环境，再读命令参考判断某条命令是否会写 Apple，最后参考架构文档理解 dry-run 与真实写入在数据流中的分界。
