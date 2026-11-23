# はじめてのおうちコーヒー

家でコーヒーを淹れ始めた人向けの実用ガイド。記事は ChatGPT（下書き）× Claude（審査・推敲）の自動パイプラインで作成し、検証を通れば自動で公開する。

公開URL: https://tfqys680-jpg.github.io/home-coffee-guide/

## 構成

| 場所 | 内容 |
| --- | --- |
| `site.json` | サイト名・URL・説明などの設定（独自ドメインに移るときは `base_url` を変更） |
| `content/articles/*.json` | 記事の中身（ここが正。HTMLはここから生成） |
| `tools/site/build.py` | 記事JSONからトップ・記事・sitemap などを生成 |
| `tools/site/check.py` | 生成後のサイトの検証（リンク切れ・重複タイトル・構造化データ・禁止表現） |
| `tools/auto-publish/` | 自動記事パイプライン（プロンプト・設定・テスト） |
| `images/articles/<slug>/` | 運営者の確認メモに載せる写真（運営者が撮ったもの） |
| `docs/auto-queue.csv` | 記事テーマのキュー（状態「待機」が対象） |
| `docs/run-log.md` | 自動実行のログ |
| `.github/workflows/` | CI、Pages への公開、自動記事（火・金 06:17 JST） |

## 自動記事の流れ

1. `docs/auto-queue.csv` から「待機」のテーマを1件選ぶ。空なら ChatGPT が提案し、Claude が選別して補充する。
2. ChatGPT が記事原稿（JSON）を作る。
3. 原稿の出典URLを実際に取得し、本文を Claude に渡して照合・推敲する（最大2回）。
4. 機械検証（禁止表現、出典2件以上、構成、文字数、関連記事の実在）。
5. 記事JSONを保存してサイトを再生成し、PRを作成。`tools/verify.sh` が通り、YMYL区分が「低」「中」なら自動マージして Pages に公開する。

自動公開しないもの:

- Claude の審査が PASS でない、または機械検証に落ちた記事 → 公開せずキューを「保留」にし、Issue で通知
- YMYL「高」（妊娠・持病・服薬など医療判断に踏み込む内容）→ PRを開いたまま Issue で確認依頼。マージするまで次の自動実行は止まる
- 検証の失敗 → マージせず Issue で通知

記事には生成AIで作成したこと、人による試飲・テストをしていないことを明記する。特定商品の推奨、試した体験、健康効果の断定は書かない。アフィリエイトリンクは自動では入れない。

## 初期設定（運営者が行う）

リポジトリの Settings → Secrets and variables → Actions に登録する。

| 種類 | 名前 | 値 |
| --- | --- | --- |
| Secret | `OPENAI_API_KEY` | OpenAI の API キー |
| Secret | `ANTHROPIC_API_KEY` | Anthropic の API キー |
| Variable | `OPENAI_MODEL` | 使う ChatGPT のモデル名 |
| Variable | `ANTHROPIC_MODEL` | 使う Claude のモデル名 |
| Variable | `AUTO_PUBLISH_ENABLED` | `true`（これ以外で停止） |

Settings → Actions → General → Workflow permissions で「Read and write permissions」と「Allow GitHub Actions to create and approve pull requests」を有効にする。Settings → Pages の Source は「GitHub Actions」。

## 運用

- 手動で1本作る: Actions → auto-publish → Run workflow
- 停止: Variable `AUTO_PUBLISH_ENABLED` を `false`
- テーマの追加・並べ替え・除外: `docs/auto-queue.csv` を編集
- 記事の修正: `content/articles/<slug>.json` を直して `python3 tools/site/build.py` を実行し、PRで反映
- Search Console: プロパティは「URLプレフィックス」で `https://tfqys680-jpg.github.io/home-coffee-guide/` を登録し、確認方法「HTMLタグ」の `content="..."` の値を `site.json` の `gsc_verification` に入れて build → PR。所有権の確認後に `sitemap.xml` を送信する
- 運営者の紹介: `site.json` の `operator_profile` に段落を配列で入れると、運営者情報ページに「運営者について」が出る（空なら出ない）

### 運営者の確認メモ・写真

運営者本人が実際に淹れて確かめたことは、記事JSONの `operator` にだけ書く。生成AIの本文には体験の表現を入れない方針は変わらない。AIが代わりに書いたり、運営者が試していない内容を書いたりしない。

```json
"operator": {
  "checked": "2026-12-01",
  "notes": ["粉12g・湯180mlで淹れ、2投目を細く注ぐと落ちる速さが安定した。"],
  "photos": [{"src": "images/articles/<slug>/drip.jpg", "alt": "ドリッパーに湯を注いでいるところ", "width": 1200, "height": 800, "caption": "自宅で淹れたときの様子"}]
}
```

- 記事に「運営者の確認メモ」の枠が出て、AIの注記は「確認メモ以外の本文は人が試していない」に変わる
- `checked` が最終更新日・構造化データ・sitemap の更新日に反映され、写真は構造化データの `image` に入る
- `tools/site/check.py` は写真ファイルの有無と alt を確認する。メモの中では体験の表現（「私が」「実際に飲んで」など）を許すが、健康効果の断定などは本文と同じく禁止
- 写真は横1200px程度のJPEGに縮めてから置く（`width`/`height` は実際の大きさ）
- 記事の取り下げ: 該当の記事JSONを削除して build を実行（ページも消える）
- 保留になった原稿: `docs/last-rejected.json`

## ローカルでの確認

```
bash tools/verify.sh
```
