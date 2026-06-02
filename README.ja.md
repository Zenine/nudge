<!--
  Translation status:
  Source file : README.md
  Source commit: 0cb38bb
  Translated  : 2026-06-02
  Status      : up-to-date
-->

> **语言 / Language**: [简体中文](README.md) · [English](README.en.md) · **日本語** · [繁體中文](README.zh-TW.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Zenine/nudge?style=flat-square&color=gold)](https://github.com/Zenine/nudge/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/Zenine/nudge?style=flat-square)](https://github.com/Zenine/nudge/commits/main)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](https://github.com/Zenine/nudge/pulls)
[![Docs](https://img.shields.io/badge/Docs-online-22d3ee?style=flat-square&logo=vitepress&logoColor=white)](https://zenine.github.io/nudge/)
[![Powered by Meridian](https://img.shields.io/badge/Powered%20by-Meridian-8b5cf6?style=flat-square)](https://github.com/lordmos/meridian)

<div align="center">
  <img src=".github/assets/hero.svg" alt="Nudge" width="120" />
</div>

# Nudge

Nudge は、構造化された計画や自然言語の計画を Apple Calendar、Reminders、Notes、Clock のアクションに変換する local-first な macOS CLI ランタイムです。

この公開リポジトリには、再利用可能な runtime、CLI、Apple アダプター、daemon、MCP wrapper、インストールスクリプトだけが含まれます。個人の計画、ローカル設定、私的な状態、API key、Health export、ユーザー固有の文書は private overlay に置いてください。

## Quick Start

> 完全なドキュメント → [オンラインで読む](https://zenine.github.io/nudge/ja/quick-start)

**Step 1** — プロジェクトを取得します。

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
```

**Step 2** — インストールしてローカル環境を確認します。

```bash
scripts/bootstrap_mac.sh
nudge doctor
```

**Step 3** — 先に dry-run し、その後 Apple アプリへ書き込みます。

```bash
nudge --dry-run "Project sync tomorrow at 3pm"
nudge "Project sync tomorrow at 3pm"
```

`scripts/bootstrap_mac.sh` はプロジェクト内に `.venv` を作成します。利用者が Python virtual environment を手動で管理する必要はありません。

## Features

- Calendar、Reminders、Notes、任意の Clock shortcut に対応する local-first macOS CLI。
- Dry-run first: `nudge --dry-run "..."` で書き込み前に解析結果を確認できます。
- Private overlay により、個人設定と SQLite 状態を公開リポジトリの外に保てます。
- MCP wrapper: `nudge mcp serve` は agent に安定した接続口を提供します。
- Daily sync は Reminders の完了状態、HealthExport データ、文書メンテナンス信号を照合します。
- Review loop は一週間の活動を安全な調整提案に変換します。
- `scripts/verify.sh` はテスト、compile check、CLI smoke check、読み取り専用の文書監査を実行します。

## Recommended Flow

1. `nudge doctor` で設定、LLM key、Apple 権限を確認します。
2. `nudge --dry-run "..."` で Apple へ書き込む前に解析結果を確認します。
3. `nudge "..."` で確認済みの Calendar / Reminders / Notes / Clock アクションを書き込みます。
4. `nudge log ...` で実際に起きたことを記録します。
5. `nudge daily sync --json` で Reminders、HealthExport、文書監査信号を照合します。
6. `nudge review weekly --adapt --dry-run` で週次レビューと調整提案を生成します。
7. `scripts/bootstrap_launchd.sh` で morning brief、daily sync、evening brief、daemon を自動化できます。

## Using a Private Overlay

Nudge は公開 runtime を使いながら、別ディレクトリから私的な設定と SQLite 状態を読み取れます。個人計画、database file、API key path、Health export、マシン固有設定は private overlay に保持してください。

```bash
export NUDGE_CONFIG=/path/to/private/config.toml
export NUDGE_STATE_DIR=/path/to/private/state

bin/nudge doctor
bin/nudge mcp serve
bin/nudge agent status --file /path/to/status.json
```

一回だけ private config を指定することもできます。

```bash
bin/nudge --config /path/to/private/config.toml doctor
bin/nudge --config /path/to/private/config.toml --dry-run "Project sync tomorrow at 3pm"
```

`NUDGE_CONFIG` が private config file を指す場合、相対的な `[state].dir` はその config file のディレクトリを基準に解決されます。明示的な `--config /path/to/config.toml` は `NUDGE_CONFIG` より優先されます。

## Maintenance

```bash
nudge docs audit
nudge docs audit --json
scripts/bootstrap_launchd.sh status
```

`nudge docs audit` は読み取り専用です。`nudge daily sync --apply --json` は、文書エラーや warning に対応が必要な場合にローカル maintenance action を作成できますが、文書を移動、削除、書き換えません。

## Testing and Verification

変更を commit する前にリポジトリ検証スクリプトを実行してください。

```bash
scripts/verify.sh
```

開発中の重点チェックには次を使えます。

```bash
python3 -m pytest tests/ -q
bin/nudge docs audit --json
```

## Private Data

次の内容は公開リポジトリの外に置いてください。

- `config.toml`
- local SQLite state
- API keys and OAuth tokens
- personal plans and health documents
- Apple Health exports
- app-specific local database snapshots

Secrets には環境変数、または `config.toml [llm].secrets_path` を優先してください。Secrets、token、database、個人マシンの絶対パスを公開リポジトリへ commit しないでください。

## License

Nudge は [AGPL-3.0-only](LICENSE) ライセンスです。

---

<sub>Built with [Meridian](https://github.com/lordmos/meridian) · open-source ops toolkit for Agent projects</sub>
