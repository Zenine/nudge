<!--
  Glossary status:
  Project     : Nudge
  Maintained  : 2026-06-02
  Scope       : 本项目所有 README / docs / AI 工具上下文文件
-->

# 术语表 / Glossary — Nudge

> **翻译铁律**：翻译前先查此表。译者不得私自替换已收录术语；表外术语首次出现时必须加入表中后再翻译，并通报其他语言译者同步。

维护语言：简体中文（源） · English · 日本語 · 繁體中文

---

## A. 品牌与产品名（Brand & Product Names）

| 简体中文（源） | English | 日本語 | 繁體中文 | 说明 / Notes |
|--------------|---------|--------|---------|-------------|
| Nudge | Nudge | Nudge | Nudge | 项目名，全语言保持原样 |
| Meridian | Meridian | Meridian | Meridian | 运营工具包品牌名，保持原样 |
| Apple Calendar | Apple Calendar | Apple Calendar | Apple Calendar | Apple 应用名，保持英文 |
| Apple Reminders | Apple Reminders | Apple Reminders | Apple Reminders | Apple 应用名，保持英文 |
| Apple Notes | Apple Notes | Apple Notes | Apple Notes | Apple 应用名，保持英文 |
| Apple Clock | Apple Clock | Apple Clock | Apple Clock | Apple 应用名，保持英文 |

## B. 技术术语（Technical Terms）

| 简体中文（源） | English | 日本語 | 繁體中文 | 说明 / Notes |
|--------------|---------|--------|---------|-------------|
| local-first | local-first | local-first | local-first | 项目定位词，保持英文 |
| CLI | CLI | CLI | CLI | 命令行工具 |
| runtime | runtime | runtime | runtime | Nudge 公开运行时 |
| private overlay | private overlay | private overlay | private overlay | 私有配置和状态层，保持英文 |
| daemon | daemon | daemon | daemon | 后台进程，保持英文 |
| MCP wrapper | MCP wrapper | MCP wrapper | MCP wrapper | Model Context Protocol 包装层 |
| dry-run | dry-run | dry-run | dry-run | 写入前预览模式 |
| SQLite state | SQLite state | SQLite 状態 | SQLite 狀態 | 本地状态数据库 |
| HealthExport | HealthExport | HealthExport | HealthExport | Apple Health 导出文件 |
| 文档审计 | documentation audit | 文書監査 | 文件審計 | `nudge docs audit` |
| 验证脚本 | verification script | 検証スクリプト | 驗證腳本 | `scripts/verify.sh` |
| 智能体 | agent | agent | agent | 本项目使用英文小写 |

## C. UI 标签 / 章节标题（UI Labels & Section Headings）

| 简体中文（源） | English | 日本語 | 繁體中文 |
|--------------|---------|--------|---------|
| Quick Start | Quick Start | Quick Start | Quick Start |
| Features | Features | Features | Features |
| Recommended Flow | Recommended Flow | Recommended Flow | Recommended Flow |
| Using a Private Overlay | Using a Private Overlay | Using a Private Overlay | Using a Private Overlay |
| Maintenance | Maintenance | Maintenance | Maintenance |
| Testing and Verification | Testing and Verification | Testing and Verification | Testing and Verification |
| Private Data | Private Data | Private Data | Private Data |
| License | License | License | License |
| FAQ | FAQ | FAQ | FAQ |
| 中断后恢复 | Resume After Interruption | 中断後の再開 | 中斷後恢復 |
| 你只需要做三件事 | You Only Need To Do Three Things | あなたがやるべき 3 つのこと | 你只需要做三件事 |
| 三步上手 | Three Steps | 3 ステップ | 三步上手 |
| 使用 private overlay | Use a Private Overlay | Private Overlay を使う | 使用 Private Overlay |
| 深入了解 | Learn More | 詳細 | 深入了解 |
| 适合这些场景 | Best-fit scenarios | 向いている場面 | 適合這些場景 |
| 一句话理解 | One-sentence model | 一文でいうと | 一句話理解 |

## D. 惯用短语 / 营销文案（Idiomatic Phrases）

| 简体中文（源） | English | 日本語 | 繁體中文 | 说明 |
|--------------|---------|--------|---------|------|
| 先 dry-run，再写入 | Dry-run first, then write | 先に dry-run し、その後書き込む | 先 dry-run，再寫入 | Nudge 核心安全用法 |
| 公开 runtime，私有状态 | public runtime, private state | 公開 runtime、私的な状態 | 公開 runtime，私有狀態 | public/private 边界 |
| 本机优先 | local-first | local-first | local-first | 保持英文术语 |
| 提醒自动化 | reminder automation | reminder automation | reminder automation | 用于 SEO/GEO |

## E. 繁简转换特别注意（ZH-TW specific）

| 简中 | 繁中（台湾）| 繁中（香港） | 建议采用 |
|------|-----------|------------|---------|
| 软件 | 軟體 | 軟件 | 軟體 |
| 文件（document） | 文件 | 檔案 | 依上下文区分 |
| 文件（file） | 檔案 | 檔案 | 檔案 |
| 默认 | 預設 | 默認 | 預設 |
| 信息 | 資訊 | 信息 | 資訊 |
| 数据 | 資料 | 數據 | 資料 |
| 用户 | 使用者 | 用戶 | 使用者 |
| 项目 | 專案 | 項目 | 專案 |
| 仓库 | 儲存庫 | 倉庫 | 儲存庫 |
| 创建 | 建立 | 建立 | 建立 |

## 使用规则

1. 翻译前先查表；已收录译法不得随意替换。
2. 新术语首次出现时先加入表格，再继续翻译。
3. 品牌名、Apple 应用名和命令名保持原样。
4. README、docs 和 AI 工具上下文文件的 H1/H2 必须与 C 节同步。
5. 繁体中文最后对照 E 节人工校对。
