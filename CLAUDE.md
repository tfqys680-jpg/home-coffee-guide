# Claude Code — はじめてのおうちコーヒー

作業前に `README.md` を読む。

- 記事の正は `content/articles/*.json`。HTMLを直接編集せず、JSONを直して `python3 tools/site/build.py` で生成する。
- 変更後は `bash tools/verify.sh` を実行し、通ったものだけをコミットする。失敗や未実施を成功と報告しない。
- 架空の体験・試飲・テスト、健康効果の断定、特定商品の推奨を書かない。数値は出典で裏付けられるものだけ書き、出典番号を付ける。
- 記事JSONの `operator`（運営者の確認メモ・写真）と `site.json` の `operator_profile` は、運営者本人が書いた文章だけを入れる。Claude が代わりに作文しない。
- `main` への変更はブランチ＋PRで行う（自動パイプラインのマージも PR 経由）。
- 完成の合格条件は `evals/home-coffee-guide.md`。記事の品質ゲートは `tools/quality/article_quality.py`（verify.sh で全記事に実行）。競合との比較は `.claude/skills/coffee-competitor-check`。
