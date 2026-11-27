# 挽き目記事の公開前確認

確認日: 2026年11月27日（日本時間）

ユーザーのマージ・公開依頼（問題がなければ）に基づき、保留原稿の修正版をClaudeで実審査した。

- 修正版（`docs/proposals/coffee-grind-20261127/`）の実審査: [run 45952100839](https://github.com/tfqys680-jpg/home-coffee-guide/actions/runs/45952100839) — 2回ともREVISE。指摘は比較形式の「注意点」H2の欠落、事実と提案の混在2か所、「〜を提案します」の繰り返し、Hot Over Iceの「少し細かく」のニュアンス。出典の事実誤りはなし。
- 再提出（初回審査が直した版 `resubmission-article.json`）の実審査: [run 45952887423](https://github.com/tfqys680-jpg/home-coffee-guide/actions/runs/45952887423) — 1回目でPASS、YMYL: 低、原稿の変更なし。
- 出典取得: 5/5（全日本コーヒー協会、Blue Bottle フレンチプレス・ドリップ・Hot Over Ice、UCC）。取得本文は審査とは別に、各主張と照合した。
- 品質ゲート本体・閾値・PASS条件・審査プロンプト・審査回数上限は変更していない。前回までの指摘（元の18件＋初回審査の指摘）は再審査に渡した。
- 公開原稿は再提出の審査でPASSしたarticleと一致（relatedのみ既存方式でラッパーへ移動）。補助キーワードはキュー（`docs/auto-queue.csv`）の値を使用。
- 既存の公開処理と同様に `docs/last-rejected.json` の最新保留表示は解消し、旧記録は `rejected-20261127.json` に保存した。
- 審査専用の一時ワークフローとスクリプトは最終差分から除いた。
