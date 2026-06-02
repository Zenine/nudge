---
layout: home
titleTemplate: ':title'
hero:
  name: "Nudge"
  text: "計画を、その日に本当に起きる行動へ"
  tagline: "Nudge は自然言語の計画を予定、reminder、note、review に落とし込みます。先に preview し、その後書き込むので、アイデアが chat の中で止まりません。"
  image:
    src: /hero.svg
    alt: Nudge
  actions:
    - theme: brand
      text: Quick Start
      link: /ja/quick-start
    - theme: alt
      text: GitHub
      link: https://github.com/Zenine/nudge
features:
  - icon:
      src: /icons/target.svg
    title: アイデアから予定へ
    details: "「明日の 15 時に project sync」のような文を、Calendar と Reminders の具体的な action に変換します。"
  - icon:
      src: /icons/check-circle.svg
    title: 書き込み前に確認
    details: "実際の action は先に dry-run し、時刻、タイトル、リスト、対象 Apple app を確認してから書き込みます。"
  - icon:
      src: /icons/refresh.svg
    title: 毎日ズレを整える
    details: "Reminders の完了状態、HealthExport signals、文書メンテナンスを local state として同期します。"
  - icon:
      src: /icons/bot.svg
    title: agent のためのローカル実行口
    details: "AI assistant は MCP 経由で Nudge を呼び出し、schedule、reminder、review、status query を扱えます。"
  - icon:
      src: /icons/lightbulb.svg
    title: 実行記録から調整
    details: "weekly review は実際の activity を安全な調整提案に変換します。きれいな summary を作るだけではありません。"
  - icon:
      src: /icons/lock.svg
    title: 公開 tool、私的な生活
    details: "再利用可能な runtime は公開し、計画、secrets、SQLite 状態、health data は private overlay に置きます。"
---
<!--
  Translation status:
  Source file : docs/index.md
  Source commit: 9d535b3
  Translated  : 2026-06-02
  Status      : up-to-date
-->

## 向いている場面

- 計画は chat や note に書くが、calendar や reminder まで届かない。
- AI assistant に schedule を手伝わせたいが、Apple Reminders へ無確認で書き込ませたくない。
- 毎日、何が完了し、何がずれ、何を調整すべきかを local record として残したい。
- 公開 automation runtime を保守しつつ、個人データ、secrets、health records は private に分離したい。

## 一文でいうと

Nudge は単なる todo-list UI ではありません。計画を解析し、確認のために表示し、Apple apps に書き込み、その後の sync と review で継続的に補正する local execution pipeline です。
