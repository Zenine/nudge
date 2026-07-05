"""Actionable error classification and rendering for CLI users."""

import json
from dataclasses import dataclass

from nudge.config import DEFAULT_CLOCK_SHORTCUT_NAME, DEFAULT_SECRETS_PATH
from nudge.runtime_log import log_error_report


@dataclass(frozen=True)
class ErrorReport:
    """Structured user-facing error with concrete next steps."""

    code: str
    title: str
    detail: str
    next_steps: tuple[str, ...]
    raw_error: str = ""

    def render(self, indent: str = "") -> str:
        """Render as concise Chinese text for terminal output."""
        log_error_report("error.render", self)
        lines = [
            f"ERROR [{self.code}]: {self.title}",
            f"发生了什么：{self.detail}",
            "下一步：",
        ]
        lines.extend(f"{idx}. {step}" for idx, step in enumerate(self.next_steps, 1))
        if self.raw_error:
            lines.append(f"原始错误：{self.raw_error}")
        return "\n".join(f"{indent}{line}" for line in lines)


def classify_apple_error(
    service: str,
    target_kind: str,
    target_name: str,
    raw_error: str,
) -> ErrorReport:
    """Classify AppleScript/EventKit errors into actionable buckets."""
    raw = str(raw_error or "").strip()
    lower = raw.lower()

    if _looks_like_permission_error(lower):
        return ErrorReport(
            code="APPLE_PERMISSION_DENIED",
            title=f"{service} 权限不足",
            detail=f"Nudge 当前进程不能访问 {service}，所以没有写入 {target_kind} `{target_name}`。",
            next_steps=_permission_steps(service),
            raw_error=raw,
        )

    if _looks_like_timeout_error(lower):
        return ErrorReport(
            code="APPLE_TIMEOUT",
            title=f"{service} 操作超时",
            detail=f"Nudge 等待 {service} 响应超时，目标是 {target_kind} `{target_name}`。",
            next_steps=(
                f"打开 {service}.app，确认没有权限弹窗或 iCloud 同步卡住。",
                "运行 `nudge doctor` 查看当前权限和数据读取状态。",
                "不要直接反复重试；如果已有部分写入成功，整条重试可能造成重复创建。",
            ),
            raw_error=raw,
        )

    if _looks_like_missing_target_error(lower):
        return ErrorReport(
            code="APPLE_TARGET_NOT_FOUND",
            title=f"目标 {target_kind} 不存在：{target_name}",
            detail=f"{service} 中找不到配置的 {target_kind} `{target_name}`，所以无法写入。",
            next_steps=(
                "运行 `nudge doctor` 查看当前可见的 Calendar / Reminders 列表。",
                f"检查 `config.toml` 中的 {target_kind} 名称是否和 Apple 应用里完全一致。",
                f"如果刚刚新建了 {target_kind}，先打开 {service}.app 等待 iCloud 同步完成。",
            ),
            raw_error=raw,
        )

    return ErrorReport(
        code="APPLE_WRITE_FAILED",
        title=f"{service} 写入失败",
        detail=f"Nudge 未能写入 {target_kind} `{target_name}`。",
        next_steps=(
            "运行 `nudge doctor` 做只读诊断。",
            "先用 `nudge --dry-run \"...\"` 复现解析结果，再只重试失败项。",
            "如果仍失败，把原始错误和输入一起记录到 TODO/issue。",
        ),
        raw_error=raw,
    )


def classify_llm_error(raw_error: str) -> ErrorReport:
    """Classify LLM failures into actionable buckets."""
    raw = str(raw_error or "").strip()
    lower = raw.lower()
    if "invalid json" in lower or "json" in lower:
        return ErrorReport(
            code="LLM_INVALID_JSON",
            title="LLM 返回了无效 JSON",
            detail="模型返回内容不是 Nudge action JSON，无法安全写入 Calendar / Reminders。",
            next_steps=(
                "重新运行一次；如果仍失败，收窄输入或切换更强模型。",
                "检查 `docs/PROMPT_PLAYBOOK.md` 中 parse action 的输出契约。",
                "脚本调用时先用 `nudge --dry-run \"...\"` 复现，确认不会产生真实写入。",
            ),
            raw_error=raw,
        )

    if "api key" in lower:
        return ErrorReport(
            code="LLM_API_KEY_ERROR",
            title="LLM API key 不可用",
            detail="当前 provider 的 API key 缺失或无效，Nudge 无法解析自然语言。",
            next_steps=(
                "运行 `nudge doctor` 检查 provider、模型和密钥状态。",
                f"确认密钥在环境变量、config.toml [llm].secrets_path 或 `{DEFAULT_SECRETS_PATH}` 中。",
                "不要把 API key 写入仓库。",
            ),
            raw_error=raw,
        )

    return ErrorReport(
        code="LLM_FAILED",
        title="LLM 调用失败",
        detail="Nudge 无法完成自然语言解析，因此没有写入 Apple 应用。",
        next_steps=(
            "运行 `nudge doctor` 检查 LLM 配置。",
            "检查网络和 provider 状态。",
            "脚本调用时保留 stderr，方便后续定位。",
        ),
        raw_error=raw,
    )


def classify_clock_error(raw_error: str, shortcut_name: str = DEFAULT_CLOCK_SHORTCUT_NAME) -> ErrorReport:
    """Classify macOS Shortcuts/Clock bridge errors."""
    raw = str(raw_error or "").strip()
    lower = raw.lower()

    if "not found" in lower or "could not find" in lower or "couldn’t find" in lower:
        return ErrorReport(
            code="CLOCK_SHORTCUT_MISSING",
            title=f"Clock Shortcut 不存在：{shortcut_name}",
            detail="Nudge 需要通过 macOS Shortcuts 调用 Clock 的 Create Alarm 动作，但本机没有找到约定的 Shortcut。",
            next_steps=(
                f"在 Shortcuts.app 新建名为 `{shortcut_name}` 的快捷指令。",
                "让快捷指令读取输入 JSON 中的 `time` 和 `label`，并调用 Clock → Create Alarm。",
                f"创建后运行 `shortcuts run \"{shortcut_name}\" --input-path <payload.json>` 验证。",
                "再运行 `nudge doctor`，确认 Clock 检查不再 WARN。",
            ),
            raw_error=raw,
        )

    if "timed out" in lower or "timeout" in lower:
        return ErrorReport(
            code="CLOCK_SHORTCUT_TIMEOUT",
            title="Clock Shortcut 执行超时",
            detail="Nudge 等待 Shortcuts 创建 Clock alarm 超时。",
            next_steps=(
                "打开 Shortcuts.app，确认没有权限弹窗或需要手动确认的动作。",
                f"手动运行 `shortcuts run \"{shortcut_name}\"` 排查快捷指令是否卡住。",
                "重新运行 `nudge doctor` 查看 Clock bridge 状态。",
            ),
            raw_error=raw,
        )

    return ErrorReport(
        code="CLOCK_SHORTCUT_FAILED",
        title="Clock alarm 写入失败",
        detail="Nudge 调用了 macOS Shortcuts，但未能成功创建 Clock alarm。",
        next_steps=(
            "运行 `nudge doctor` 查看 Clock bridge 状态。",
            f"手动运行 `shortcuts run \"{shortcut_name}\" --input-path <payload.json>` 验证快捷指令。",
            "若仍失败，先用 Reminders 或 Calendar alert 替代硬闹钟。",
        ),
        raw_error=raw,
    )


def apple_backend_error_report(raw_error: str) -> ErrorReport:
    """Build an actionable error for unsupported Apple adapter config."""
    raw = str(raw_error or "").strip()
    return ErrorReport(
        code="APPLE_BACKEND_UNSUPPORTED",
        title="Apple backend 当前未实现",
        detail=f"config.toml 选择了当前版本还没有接入的 Apple backend：{raw}",
        next_steps=(
            "短期保持默认 runtime：Calendar/Reminders/Notes 使用 `native`，Clock 使用 `shortcuts`。",
            "把 config.toml 中 `[apple.calendar] backend = \"native\"`、`[apple.reminders] backend = \"native\"`、`[apple.notes] backend = \"native\"`、`[apple.clock] backend = \"shortcuts\"`。",
            "外部 ical/rem/ekctl/MCP backend 需要先经过 adapter contract、dry-run 和真实写入 smoke 后再启用。",
        ),
        raw_error=raw,
    )


def family_routing_invalid_report(action_summary: str, routing_metadata: dict | None = None) -> ErrorReport:
    """Build an actionable error when family-group routing cannot pick a safe target."""
    metadata = routing_metadata if isinstance(routing_metadata, dict) else {}
    summary = str(action_summary or "<unknown>").strip() or "<unknown>"
    reason = str(metadata.get("reason") or "家庭组路由没有解析出有效成员。")
    invalid = metadata.get("invalid_assignees")
    invalid_text = f"；无效 assignees={invalid}" if invalid else ""
    return ErrorReport(
        code="FAMILY_ROUTING_INVALID",
        title="家庭组路由无效，已阻止写入",
        detail=(
            f"action `{summary}` 保留了家庭组原始目标，但路由结果不可执行："
            f"{reason}{invalid_text}。为避免写到错误 Calendar / Reminder list，Nudge 没有调用 Apple 写入。"
        ),
        next_steps=(
            "检查 `config.toml` 中 `[family.routing]` 的 default / rules.assignees，确保只引用已配置的家庭成员 key 或 `all`。",
            "先用 `nudge do --dry-run --json \"...\"` 查看 `routing` 结果。",
            "修正路由后只重试该失败项，避免重复创建其他已成功 action。",
        ),
        raw_error=json.dumps(metadata, ensure_ascii=False, default=str),
    )


def agent_request_error_report(raw_error: str) -> ErrorReport:
    """Build an actionable error for invalid agent relay requests."""
    raw = str(raw_error or "").strip()
    return ErrorReport(
        code="AGENT_REQUEST_INVALID",
        title="Agent request 结构无效",
        detail=f"其他 agent 提交的结构化 Apple action request 无法安全执行：{raw}",
        next_steps=(
            "确认请求是 JSON object，且包含非空 `actions` 列表。",
            "当前支持 `calendar_event.create`、`reminder.create`、`alarm.create`、`note.create`。",
            "先用 `nudge agent apply --dry-run --json` 验证，再执行真实写入。",
        ),
        raw_error=raw,
    )


def agent_batch_too_large_report(limit: int, received: int) -> ErrorReport:
    """Build an actionable error for oversized agent relay batches."""
    return ErrorReport(
        code="AGENT_BATCH_TOO_LARGE",
        title="Agent action batch 过大",
        detail=f"本次请求包含 {received} 个 action，单次最多 {limit} 个；Nudge 没有写入 Apple 应用。",
        next_steps=(
            f"把 actions 拆成每批最多 {limit} 个。",
            "每批都先 dry-run，确认无误后再带 dry_run_token 写入。",
            "不要在失败后整批盲目重试，避免重复写入已成功的 action。",
        ),
        raw_error=f"received={received}; limit={limit}",
    )


def agent_status_request_error_report(raw_error: str) -> ErrorReport:
    """Build an actionable error for status回写请求。"""
    raw = str(raw_error or "").strip()
    return ErrorReport(
        code="AGENT_STATUS_INVALID",
        title="Agent status 请求结构无效",
        detail=f"本地 action 状态回写请求不合法：{raw}",
        next_steps=(
            "确认请求是 JSON object，包含非空 `action_id` 和合法 `status`。",
            "`status` 只能是 done / skipped / partial / deferred / blocked。",
            "reason 需为 too_hard、no_time、conflict、low_energy、forgot、unclear、not_important、waiting_on_other 之一；",
            "next_action 需为 keep、reduce、split、reschedule、cancel 之一。",
            "先 dry-run 验证后再入库写状态。",
        ),
        raw_error=raw,
    )


def agent_auth_required_report() -> ErrorReport:
    """Build an error for optional local auth failures on mutating agent calls."""
    return ErrorReport(
        code="AGENT_AUTH_REQUIRED",
        title="本地认证失败",
        detail="该 Nudge 写入入口启用了本地 token 认证，但请求没有提供有效的 `auth_token`。",
        next_steps=(
            "确认调用方是可信本地进程，不要把 agent/MCP 写入入口暴露给不可信客户端。",
            "从调用环境的 token 环境变量读取值，并放入请求 JSON 的 `auth_token` 字段。",
            "不要把 token 写入仓库、日志、shell history 或公开 issue。",
        ),
        raw_error="local auth failed",
    )


def agent_auth_misconfigured_report() -> ErrorReport:
    """Build an error when local auth is enabled but no expected token is available."""
    return ErrorReport(
        code="AGENT_AUTH_MISCONFIGURED",
        title="本地认证配置不完整",
        detail="配置启用了本地 token 认证，但运行环境没有提供可用的 token 环境变量。",
        next_steps=(
            "设置配置里的 token_env 对应环境变量后重试。",
            "如果只是单机自用且接受 local trust 模型，可在 config.toml 中关闭 `[security.local_auth].enabled`。",
            "不要把真实 token 写进 config.example.toml 或公开仓库。",
        ),
        raw_error="local auth token env missing",
    )


def agent_action_not_found_report(action_id: str) -> ErrorReport:
    """Build an actionable error when action id cannot be found in state DB."""
    value = str(action_id or "").strip() or "<empty>"
    return ErrorReport(
        code="AGENT_ACTION_NOT_FOUND",
        title="本地 action 不存在",
        detail=f"SQLite action 表里找不到 id={value}，无法回写该状态。",
        next_steps=(
            "先确认 action_id 是否来自 `nudge do / agent apply / log` 返回。",
            "必要时用 `nudge review weekly` 或 `nudge dogfood weekly` 定位最新 action id。",
            "不要把已删除/历史无效 id 继续回传。",
        ),
        raw_error=f"action_id={value}",
    )


def cli_input_error_report(raw_error: str) -> ErrorReport:
    """Build an actionable error for local CLI input/config preflight failures."""
    raw = str(raw_error or "").strip()
    return ErrorReport(
        code="CLI_INPUT_ERROR",
        title="CLI 输入或配置读取失败",
        detail=f"Nudge 无法读取本次命令需要的输入或配置：{raw}",
        next_steps=(
            "确认 `--file` / `--config` 路径存在，且当前用户有读取权限。",
            "脚本调用时使用绝对路径，避免工作目录不同导致相对路径失效。",
            "如果是配置问题，先运行 `nudge doctor --config <path>` 检查。",
        ),
        raw_error=raw,
    )


def agent_confirmation_required_report() -> ErrorReport:
    """Build an error for requests that require a dry-run confirmation token."""
    return ErrorReport(
        code="AGENT_CONFIRMATION_REQUIRED",
        title="缺少 dry_run_token 确认",
        detail="该 agent request 要求先 dry-run 预览并携带返回的 dry_run_token，Nudge 因此没有写入 Apple 应用。",
        next_steps=(
            "先用同一份 request 设置 `dry_run=true` 和 `require_confirmation=true` 调用一次。",
            "把返回的 `dry_run_token` 原样带入真实写入请求，并设置 `dry_run=false`。",
            "真实写入前不要修改 actions；如需修改，重新 dry-run 获取新 token。",
        ),
        raw_error="dry_run_token missing",
    )


def agent_confirmation_invalid_report() -> ErrorReport:
    """Build an error for dry-run confirmation token mismatch."""
    return ErrorReport(
        code="AGENT_CONFIRMATION_INVALID",
        title="dry_run_token 与当前 request 不匹配",
        detail="当前真实写入请求和此前 dry-run 预览的 request 摘要不一致，Nudge 因此没有写入 Apple 应用。",
        next_steps=(
            "确认 request_id、source、actions、target、时间和内容没有在 dry-run 后被修改。",
            "如果确实需要修改，请重新执行 dry-run 并使用新的 `dry_run_token`。",
            "不要复用旧 token 写入不同内容，避免 agent 绕过人工确认。",
        ),
        raw_error="dry_run_token mismatch",
    )


def agent_text_plan_confirmation_required_report() -> ErrorReport:
    """Build an error for plan-driven requests missing text-plan confirmation."""
    return ErrorReport(
        code="AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED",
        title="缺少文本计划确认",
        detail=(
            "这是计划驱动的 Apple 写入请求，但 request 没有声明已完成并确认文本计划；"
            "Nudge 因此没有执行 dry-run，也没有写入 Apple 应用。"
        ),
        next_steps=(
            "先把计划写成用户可读文本，确认日期、标题、目标 Calendar/List/Notes folder 与动作数量。",
            "获得人工确认后，在同一 request 中设置 `plan_driven=true`、`text_plan_confirmed=true`，并填写 `text_plan_ref`。",
            "随后再执行 dry-run；真实写入仍需携带匹配的 `dry_run_token`。",
        ),
        raw_error="plan_driven request missing text_plan_confirmed/text_plan_ref",
    )


def format_llm_error(raw_error: str) -> str:
    """Format LLM failures as actionable CLI text."""
    return classify_llm_error(raw_error).render()


def llm_schema_error_report(message: str) -> ErrorReport:
    """Build valid-JSON-but-invalid-action-schema failure details."""
    return ErrorReport(
        code="LLM_ACTION_SCHEMA_INVALID",
        title="LLM JSON 结构不符合 action schema",
        detail=f"模型返回了 JSON，但字段不满足 Nudge action 契约：{message}",
        next_steps=(
            "不要执行真实写入；先用 `nudge --dry-run \"...\"` 复现。",
            "检查 Prompt Playbook 中 calendar_event / reminder / alarm 的必填字段。",
            "如果同类输入反复失败，收窄提示词或切换更强模型。",
        ),
        raw_error=message,
    )


def format_llm_schema_error(message: str) -> str:
    """Format valid-JSON-but-invalid-action-schema failures."""
    return llm_schema_error_report(message).render()


def _looks_like_permission_error(lower_error: str) -> bool:
    return any(
        marker in lower_error
        for marker in (
            "-1743",
            "not authorized",
            "not permitted",
            "permission",
            "access denied",
            "full access denied",
        )
    )


def _looks_like_timeout_error(lower_error: str) -> bool:
    return "timed out" in lower_error or "timeout" in lower_error


def _looks_like_missing_target_error(lower_error: str) -> bool:
    return any(
        marker in lower_error
        for marker in (
            "can't get",
            "can’t get",
            "cannot get",
            "not found",
            "doesn't exist",
            "does not exist",
            "missing configured",
        )
    )


def _permission_steps(service: str) -> tuple[str, ...]:
    if service == "Calendar":
        return (
            "打开 Calendar.app，让 macOS 完成首次授权弹窗。",
            "到 系统设置 → 隐私与安全性 → 日历，允许当前终端/IDE/Python 访问 Calendar；读取需要 Full Access。",
            "重新运行 `nudge doctor`，确认 Calendar 为 PASS。",
        )
    if service == "Reminders":
        return (
            "打开 Reminders.app，让 macOS 完成首次授权弹窗。",
            "到 系统设置 → 隐私与安全性 → 提醒事项，允许当前终端/IDE/Python 访问 Reminders。",
            "重新运行 `nudge doctor`，确认 Reminders 为 PASS 或明确 WARN。",
        )
    if service == "Notes":
        return (
            "打开 Notes.app，让 macOS 完成首次授权弹窗。",
            "到 系统设置 → 隐私与安全性 → 自动化，允许当前终端/IDE/Python 控制 Notes。",
            "重新运行 `nudge doctor`，确认 Notes 为 PASS 或明确 WARN。",
        )
    return (
        f"打开 {service}.app，让 macOS 完成首次授权弹窗。",
        "到 系统设置 → 隐私与安全性 检查对应权限。",
        "重新运行 `nudge doctor`。",
    )
