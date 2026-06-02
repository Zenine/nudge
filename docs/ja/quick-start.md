<!--
  Translation status:
  Source file : docs/quick-start.md
  Source commit: 8a9b525
  Translated  : 2026-06-02
  Status      : up-to-date
-->

# Quick Start

Nudge は、構造化された計画や自然言語の計画を Apple Calendar、Reminders、Notes、Clock のアクションに変換する local-first な macOS CLI runtime です。

## 3 ステップ

### 1. プロジェクトを取得する

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
```

### 2. インストールして環境を確認する

```bash
scripts/bootstrap_mac.sh
nudge doctor
```

`scripts/bootstrap_mac.sh` はプロジェクト内に `.venv` を作成するため、Python virtual environment を手動で管理する必要はありません。

### 3. 先に dry-run し、その後実行する

```bash
nudge --dry-run "Project sync tomorrow at 3pm"
nudge "Project sync tomorrow at 3pm"
```

Dry-run は解析された action を表示します。結果が正しいことを確認してから、`--dry-run` なしで実行してください。

## Private Overlay を使う

Nudge の推奨境界は「公開 runtime、私的な状態」です。個人計画、ローカル設定、SQLite 状態、API key、Health export、マシン固有パスは private overlay に置きます。

```bash
export NUDGE_CONFIG=/path/to/private/config.toml
export NUDGE_STATE_DIR=/path/to/private/state

bin/nudge doctor
bin/nudge mcp serve
```

一回だけ config を指定することもできます。

```bash
bin/nudge --config /path/to/private/config.toml doctor
```

## あなたがやるべき 3 つのこと

1. `nudge doctor` で Apple 権限と設定を確認する。
2. 実際に書き込む前に必ず `--dry-run` を使う。
3. コード変更を commit する前に `scripts/verify.sh` を実行する。

## 中断後の再開

AI 助手にこのリポジトリを保守させている場合は、次のように再開します。

```text
请读 checkpoint.md，继续上次未完成的工作。
```

## 詳細

- [README](https://github.com/Zenine/nudge#readme)
- [FAQ](./faq.md)
- [GitHub](https://github.com/Zenine/nudge)
