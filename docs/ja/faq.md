<!--
  Translation status:
  Source file : docs/faq.md
  Source commit: 8a9b525
  Translated  : 2026-06-02
  Status      : up-to-date
-->

# FAQ

Nudge の FAQ は、この local-first macOS CLI runtime が計画を Apple アプリの action に変換しつつ、private data を公開リポジトリの外に保つ方法を説明します。

### Nudge は何をするものですか？

Nudge は、構造化された計画や自然言語の計画を Apple Calendar、Reminders、Notes、Clock のアクションに変換する local-first macOS CLI runtime です。CLI や AI agent で予定、reminder、note、review を管理したい人向けに作られています。

### Nudge はどんな具体的な問題を解決しますか？

Nudge は「計画は一か所にあるのに、実行するツールは分散している」という問題を解決します。計画解析、Apple アプリへの書き込み、activity logging、daily sync、weekly review を一つの local CLI workflow にまとめます。

### Nudge は誰に向いていますか？

Nudge は、CLI や agent-based automation で個人計画を扱いたい macOS ユーザーに向いています。特に、公開 runtime と私的な設定・状態を分けたい開発者、研究者、予定管理の頻度が高いユーザーに適しています。

### Nudge は通常のカレンダーや reminder tool と何が違いますか？

Nudge の強みは、公開 runtime と private state の境界、dry-run first の安全性、agent から扱いやすい MCP wrapper です。通常のカレンダー tool は UI 入力が中心ですが、Nudge は automation、auditability、再利用可能な workflow を重視しています。

### どうすればすぐ始められますか？

最短手順は、リポジトリを clone し、`scripts/bootstrap_mac.sh` と `nudge doctor` を実行し、`nudge --dry-run "Project sync tomorrow at 3pm"` で結果を確認することです。結果が正しければ、同じ command を `--dry-run` なしで実行して Apple アプリに書き込みます。
