# Claude Code — はじめてのおうちコーヒー

作業前に `README.md` を読む。

- 回答は日本語で返す（作業報告、質問、GitHub の通知への返信、PR・コミットの本文も日本語）。

- 記事の正は `content/articles/*.json`。HTMLを直接編集せず、JSONを直して `python3 tools/site/build.py` で生成する。
- 変更後は `bash tools/verify.sh` を実行し、通ったものだけをコミットする。失敗や未実施を成功と報告しない。
- 架空の体験・試飲・テスト、健康効果の断定、特定商品の推奨（順位・「おすすめ」・使った感想）を書かない。数値は出典で裏付けられるものだけ書き、出典番号を付ける。
- 商品は記事JSONの `products` に「記事の条件に合う商品の例」として載せる。仕様はメーカー公式ページで確かめたことだけを `facts` に書き、`source`（公式ページ）と `checked`（確認日）を付ける。価格は書かない。自動記事では `products` を入れない（人かClaudeが公式ページを確かめて追加する）。
- 全記事に `visual`（アイキャッチ・図解・図解動画の元）と `shopping`（記事の選び方の条件で Amazon・楽天を検索するリンク）を入れる。ない記事は品質ゲートで落ちる。図解の項目は出典の事実だけで、`cite` に出典番号を入れる。shopping に商品名・順位・「おすすめ」・使った感想を書かない。
- 記事の `visual` やタイトル・カテゴリを変えたら `python3 tools/media/make_media.py <slug>`（または `--stale`）で画像と動画を作り直す。古いままだと `tools/site/check.py` が落ちる。
- 記事JSONの `operator`（運営者の確認メモ・写真）と `site.json` の `operator_profile` は、運営者本人が書いた文章だけを入れる。Claude が代わりに作文しない。
- `main` への変更はブランチ＋PRで行う（自動パイプラインのマージも PR 経由）。
- 完成の合格条件は `evals/home-coffee-guide.md`。記事の品質ゲートは `tools/quality/article_quality.py`（verify.sh で全記事に実行）。競合との比較は `.claude/skills/coffee-competitor-check`。
