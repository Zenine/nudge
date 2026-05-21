from pathlib import Path
import tomllib

from nudge.config import (
    DEFAULT_CALENDAR_NAME,
    DEFAULT_CLOCK_SHORTCUT_NAME,
    DEFAULT_LLM_CONFIG,
    DEFAULT_NOTES_FOLDER,
    DEFAULT_REMINDER_LIST,
)


ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_creates_config_from_example_before_state_edits():
    script = (ROOT / "scripts" / "bootstrap_mac.sh").read_text(encoding="utf-8")

    assert "cp config.example.toml config.toml" in script
    assert script.index("cp config.example.toml config.toml") < script.index("configure_state_dir")


def test_config_example_matches_runtime_defaults():
    config = tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))

    assert config["general"]["default_calendar"] == DEFAULT_CALENDAR_NAME
    assert config["general"]["default_reminder_list"] == DEFAULT_REMINDER_LIST
    assert config["general"]["default_notes_folder"] == DEFAULT_NOTES_FOLDER
    assert config["llm"]["provider"] == DEFAULT_LLM_CONFIG["provider"]
    assert config["llm"]["models"] == DEFAULT_LLM_CONFIG["models"]
    assert config["apple"]["clock"]["shortcut_name"] == DEFAULT_CLOCK_SHORTCUT_NAME


def test_verify_runs_pytest_and_compile_checks():
    script = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")

    assert "python3 -m pytest tests/ -q" in script
    assert "python3 -m compileall -q nudge" in script


def test_readme_quick_start_matches_public_export_directory():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "git clone https://github.com/Zenine/nudge.git nudge-public" in readme
    assert "cd nudge-public" in readme


def test_default_readme_is_english_and_links_chinese_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    required_sections = [
        "## Installation",
        "## Configuration",
        "## Diagnostics and Repair",
        "## Common Commands",
        "## Agent and MCP",
        "## Daemon Queue",
        "## Documentation",
        "## Development and Verification",
    ]
    for section in required_sections:
        assert section in readme

    required_commands = [
        "scripts/bootstrap_mac.sh",
        "nudge doctor",
        "nudge do --dry-run",
        "nudge agent apply",
        "nudge mcp serve",
        "scripts/verify.sh",
    ]
    for command in required_commands:
        assert command in readme

    assert "[Chinese documentation](README.zh-CN.md)" in readme
    assert ".github/assets/readme-hero.png" in readme
    assert "docs/assets/nudge-architecture-imagegen.png" in readme
    assert "## Reader Paths" in readme
    assert "## What It Does" in readme
    assert "[Docs Index](docs/README.md)" in readme
    assert "[CLI](docs/CLI.md)" in readme
    assert "[Architecture](docs/ARCHITECTURE.md)" in readme


def test_chinese_readme_covers_installation_repair_usage_and_verification():
    readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    required_sections = [
        "## 安装",
        "## 配置",
        "## 诊断与修复",
        "## 常用命令",
        "## Agent 与 MCP",
        "## Daemon 队列",
        "## 文档",
        "## 开发与验证",
    ]
    for section in required_sections:
        assert section in readme

    assert "[English](README.md)" in readme
    assert ".github/assets/readme-hero.png" in readme
    assert "docs/assets/nudge-architecture-imagegen.png" in readme
    assert "## 读者入口" in readme
    assert "## 它做什么" in readme
    assert "[文档索引](docs/README.md)" in readme
    assert "[CLI](docs/CLI.md)" in readme
    assert "[Architecture](docs/ARCHITECTURE.md)" in readme


def test_public_docs_are_linked_and_scrubbed():
    docs = [
        "README.md",
        "CLI.md",
        "ARCHITECTURE.md",
        "DESIGN.md",
        "MCP_SECURITY.md",
        "DAEMON_RUNBOOK.md",
        "APPLE_ADAPTER_SURVEY.md",
        "MODULE_MAP.md",
        "SKILL_SPEC.md",
        "PROMPT_PLAYBOOK.md",
    ]

    for name in docs:
        assert (ROOT / "docs" / name).exists()

    combined = "\n".join(
        (ROOT / "docs" / name).read_text(encoding="utf-8")
        for name in docs
    )
    blocked = [
        "百度同步盘",
        "niaite-email",
        "/Users/zeninexu",
        "docs/personal",
    ]
    for text in blocked:
        assert text not in combined


def test_readme_visual_assets_exist():
    required_assets = [
        ROOT / ".github" / "assets" / "readme-hero.png",
        ROOT / "docs" / "assets" / "nudge-architecture-imagegen.png",
        ROOT / "docs" / "assets" / "nudge-architecture.png",
    ]

    for path in required_assets:
        assert path.exists()
        assert path.stat().st_size > 100_000


def test_readme_documents_all_supported_llm_providers_without_machine_specific_paths():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    for provider in [
        "Qwen/DashScope",
        "OpenAI",
        "Anthropic",
        "DeepSeek",
        "Ollama",
    ]:
        assert provider in readme
        assert provider in chinese_readme

    assert "~/.config/nudge/secrets.yaml" in readme
    assert "~/.config/nudge/secrets.yaml" in chinese_readme
    assert "百度同步盘" not in readme
    assert "百度同步盘" not in chinese_readme


def test_readmes_document_permissions_and_runtime_logs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    for text in (readme, chinese_readme):
        assert "nudge-runtime.jsonl" in text
        assert "Full Calendar Access" in text
        assert "Automation" in text
