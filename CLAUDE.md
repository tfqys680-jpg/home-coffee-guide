# Claude Code — はじめてのおうちコーヒー

作業前に `README.md` を読む。

- 記事の正は `content/articles/*.json`。HTMLを直接編集せず、JSONを直して `python3 tools/site/build.py` で生成する。
- 変更後は `bash tools/verify.sh` を実行し、通ったものだけをコミットする。失敗や未実施を成功と報告しない。
- 架空の体験・試飲・テスト、健康効果の断定、特定商品の推奨を書かない。数値は出典で裏付けられるものだけ書き、出典番号を付ける。
- `main` への変更はブランチ＋PRで行う（自動パイプラインのマージも PR 経由）。
