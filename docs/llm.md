# LLM provider 选择指南

Nudge 是 local-first CLI：Apple 写入、SQLite 状态和配置默认留在本机。LLM 只是部分自然语言和复盘能力的可选后端；选择 provider 时，应先按隐私边界、是否需要离线、成本预算和响应速度决定，而不是只看模型榜单。

相关文档：配置字段见 [`docs/configuration.md`](configuration.md)，安全边界见 [`SECURITY.md`](../SECURITY.md)，公开示例见 [`examples/README.md`](../examples/README.md)。

## Nudge 什么时候使用 LLM

可能需要 LLM 的路径：

- 自然语言解析：例如把“明天下午三点项目同步”解析成结构化动作。
- check-in / review / adapt：例如从用户记录中提取复盘要点，或为下一阶段计划生成调整建议。
- 家庭或复杂上下文的兜底判断：当确定性规则无法判断时，配置可允许 LLM 辅助路由或解释。
- 旧兼容路径：例如显式启用的 legacy LLM planner。

不一定需要 LLM 的路径：

- `nudge docs audit` 和 `nudge docs audit --json` 是只读文档检查。
- 结构化 `agent apply --dry-run`、MCP `dry_run: true`、JSON/YAML 示例解析，输入已经是结构化动作时通常不需要 LLM。
- Skill 模板的 dry-run、schema 校验和许多纯逻辑测试可以在无 LLM key 的环境中运行。

建议默认先跑 dry-run。只有当命令需要从自由文本生成或调整计划时，才为该环境配置 LLM provider。

## Provider 怎么选

| Provider | 适合场景 | 隐私 | 成本 | 延迟 | 质量 | 离线/本地化 |
| --- | --- | --- | --- | --- | --- | --- |
| `qwen` / `dashscope` | 默认中文体验、成本敏感、需要 OpenAI-compatible 接口 | 文本会发送到云端 provider | 通常较低到中等，按用量计费 | 取决于网络和地区 | 中文与日程类任务表现较稳 | 不离线 |
| `openai` | 通用质量、工具生态和英文/多语言任务 | 文本会发送到云端 provider | 中等到较高，视模型而定 | 通常较稳 | 通用能力强，复杂解析可靠 | 不离线 |
| `anthropic` | 复杂复盘、长上下文、强推理任务 | 文本会发送到云端 provider | 中等到较高，视模型而定 | 取决于网络和地区 | 长文本理解和审阅类任务较强 | 不离线 |
| `deepseek` | 成本敏感、代码/推理类任务、OpenAI-compatible 接口 | 文本会发送到云端 provider | 通常较低到中等，按用量计费 | 取决于网络和地区 | 推理/代码类任务可作为性价比选项 | 不离线 |
| `ollama` / local | 最高隐私要求、离线演示、无云端 key 的试用 | 输入不离开本机（仍取决于本机环境） | 无按量 API 费，但占本机算力 | 本机模型小则快，大模型可能慢 | 取决于本机模型，复杂规划可能弱于强云端模型 | 支持离线、本地化最好 |

推荐口径：

- **优先隐私或离线**：选 `ollama`，接受质量和速度取决于本机模型与硬件。
- **中文默认和低成本**：选 `qwen` 或 `dashscope`。
- **通用高质量**：选 `openai`。
- **复杂复盘、长文本审阅**：可选 `anthropic` 作为 `strong` 层。
- **成本敏感但仍用云端**：可评估 `deepseek`。

无论选择哪种云端 provider，都不要把原始健康记录、家庭成员真实信息或不必要的个人上下文发送给模型。先用确定性规则、脱敏摘要和最小必要上下文。

## 模型分层：fast / default / strong

Nudge 的 `[llm.models]` 使用三层模型名，便于在同一个 provider 下按任务成本和质量切换：

- `fast`：低延迟、低成本任务。适合短文本分类、轻量解析、快速兜底判断。
- `default`：常规自然语言解析、计划草案、check-in 摘要。建议作为日常默认。
- `strong`：复杂复盘、长上下文 review/adapt、多约束计划。只在需要更强推理时使用，避免无谓增加成本和延迟。

三层可以指向同一个模型，也可以混用同 provider 的不同模型。若本机只配置一个本地模型，把三层都写成同一个模型名即可。

## 密钥配置安全

安全优先级：

1. **优先环境变量**：例如 `DASHSCOPE_API_KEY`、`QWEN_API_KEY`、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`DEEPSEEK_API_KEY`。
2. **其次私有 `secrets_path`**：适合本机不提交的 secrets 文件，例如 `~/.config/nudge/secrets.yaml`。
3. **避免 `[llm].api_key`**：只允许在本机私有 `config.toml` 中临时使用；公开仓库、issue、日志和示例中不得出现真实 key。

公开文档和示例只能使用占位符，例如 `YOUR_PROVIDER_API_KEY` 或 `<PROVIDER_API_KEY>`。不要提交真实 API key、OAuth token、个人健康数据、本机私有路径、机器专属配置或真实家庭成员资料。

## 公开安全的配置示例

### 云端 provider 示例

```toml
[llm]
provider = "qwen"
# 真实 key 放在环境变量 DASHSCOPE_API_KEY / QWEN_API_KEY，或放入私有 secrets_path。
# api_key = "YOUR_PROVIDER_API_KEY"
secrets_path = "~/.config/nudge/secrets.yaml"

[llm.models]
fast = "qwen-plus"
default = "qwen-plus"
strong = "qwen-plus"
```

切换到其它云端 provider 时，只改 provider 和模型名，并通过对应环境变量提供密钥：

```toml
[llm]
provider = "openai"
secrets_path = "~/.config/nudge/secrets.yaml"

[llm.models]
fast = "gpt-4o-mini"
default = "gpt-4o-mini"
strong = "gpt-4o"
```

### 本地 Ollama 示例

```toml
[llm]
provider = "ollama"

[llm.models]
fast = "llama3.1"
default = "llama3.1"
strong = "llama3.1"
```

使用本地模型前，请先在本机安装并启动 Ollama，并确认模型名与本机已拉取的模型一致。公开示例不要写机器专属路径或私有模型服务地址。

## 非 Mac 用户和无 LLM 用户怎么用

非 Mac 用户仍可评估 Nudge 的公开仓库内容：

- 阅读 [`docs/configuration.md`](configuration.md) 理解配置结构。
- 运行 `nudge docs audit --json` 做只读文档审计。
- 阅读并校验 [`examples/README.md`](../examples/README.md) 下的 JSON/YAML 示例。
- 运行不依赖 Apple 应用权限、不需要真实写入的部分测试或解析-only 流程。

无 LLM key 的用户也可以：

- 使用结构化 agent/MCP dry-run，直接传入 JSON 动作。
- 使用 Skill YAML 模板、schema 校验和文档审计。
- 使用 `ollama` 在本机模型可用时进行离线 dry-run。

需要注意：自然语言 LLM dry-run、review/adapt 中的 LLM 生成或复杂兜底判断，需要有效 provider 配置。没有 provider 时，应优先选择结构化输入、示例文件或纯文档/校验路径。
