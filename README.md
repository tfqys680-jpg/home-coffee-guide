# はじめてのおうちコーヒー

家でコーヒーを淹れ始めた人向けの実用ガイド。記事は ChatGPT（下書き）× Claude（審査・推敲）の自動パイプラインで作成し、検証を通れば自動で公開する。

公開URL: https://tfqys680-jpg.github.io/home-coffee-guide/

## 構成

| 場所 | 内容 |
| --- | --- |
| `site.json` | サイト名・URL・説明・カテゴリなどの設定（独自ドメインに移るときは `base_url` を変更） |
| `content/articles/*.json` | 記事の中身（ここが正。HTMLはここから生成） |
| `tools/site/build.py` | 記事JSONからトップ・記事・sitemap などを生成 |
| `tools/site/check.py` | 生成後のサイトの検証（リンク切れ・重複タイトル・構造化データ・禁止表現） |
| `tools/auto-publish/` | 自動記事パイプライン（プロンプト・設定・テスト） |
| `tools/quality/` | 記事の品質ゲート（`article_quality.py`）と、その見本原稿・テスト |
| `evals/home-coffee-guide.md` | 「完成」の合格条件と判定記録 |
| `.claude/skills/coffee-competitor-check/` | 公開記事を検索上位3件と比べる Claude Code 用スキル（結果は `docs/competitor/`） |
| `images/ogp.png` `images/logo.png` | SNS共有用の画像とロゴ（`python3 tools/site/make_images.py` で作り直せる） |
| `images/articles/<slug>/` | 運営者の確認メモに載せる写真（運営者が撮ったもの） |
| `docs/auto-queue.csv` | 記事テーマのキュー（状態「待機」が対象） |
| `docs/sources.json` | テーマ（slug）ごとの出典リスト。記事を書く前にここのURLを取得して中身を確かめる（`found_by`: manual＝人が登録、auto＝自動調査で見つけたもの） |
| `docs/run-log.md` | 自動実行のログ |
| `.github/workflows/` | CI、Pages への公開、自動記事（火・金 06:17 JST） |
| `tools/site/collect_public.sh` `check_public.py` | 公開するファイルを集める（deploy.yml が使う）／集めたものだけでリンク切れがないかの確認 |

## 自動記事の流れ

1. `docs/auto-queue.csv` から「待機」のテーマを1件選ぶ。空なら ChatGPT が提案し、Claude が選別して補充する。
2. 書く前に出典をそろえる。`docs/sources.json` のURLを実際に取得して中身を確かめ、2件に足りなければ Claude が Web検索（`config.json` の `source_domains` の公的機関・業界団体に限定）で候補を探し、取得確認できたものだけを使う。それでも2件そろわないテーマは「出典不足」にして次の「待機」テーマへ（1回の実行で最大3テーマ）。別のページへ転送されたURL・PDF・本文が取れないページは使わない。
3. ChatGPT に確認済み出典の本文抜粋を渡して記事原稿（JSON）を作らせる（出典は一覧のURLだけ。抜粋にない数値は書かない）。原稿と出典本文を Claude に渡して照合・推敲する（最大2回）。あわせて Claude が、検索上位の記事が扱う論点を5〜8個挙げて記事が扱っているかを点検し、上位にない独自の要素を確かめる。
4. 品質ゲート（`tools/quality/article_quality.py`）で判定する。不合格なら指摘を Claude に渡して1回だけ推敲し直し、もう一度判定する。
5. 機械検証（禁止表現、出典2件以上、確認済み一覧にない出典がないこと、構成、文字数、関連記事・本文リンクの実在）。
6. 記事JSONを保存してサイトを再生成し、PRを作成。`tools/verify.sh` が通り、YMYL区分が「低」「中」なら自動マージして Pages に公開する。

自動公開しないもの:

- Claude の審査が PASS でない、品質ゲート・競合の点検・機械検証に落ちた記事 → 公開せずキューを「保留」にし、Issue で通知
- YMYL「高」（妊娠・持病・服薬など医療判断に踏み込む内容）→ PRを開いたまま Issue で確認依頼。マージするまで次の自動実行は止まる
- 検証の失敗 → マージせず Issue で通知
- キューが空で補充もできなかったとき、push・PR作成・マージなどで途中で止まったとき → Issue で通知

記事には生成AIで作成したこと、人による試飲・テストをしていないことを明記する。特定商品の推奨、試した体験、健康効果の断定は書かない。アフィリエイトリンクは自動では入れない。

## 記事の品質ゲート

過去の失敗「内容が薄く、どの記事も似通う」を機械的に落とす。AIの判断は使わず、同じ原稿なら毎回同じ結果になる。判定の前に NFKC 正規化し、ゼロ幅スペースなどの見えない文字は不合格にする。

- 形式（`format`）を「手順・比較・トラブル解決・基礎知識」から選び、形式ごとの必須ブロックを入れる（手順＝8字以上の手順を4つ以上、比較＝3列以上の比較表、トラブル解決＝「原因」の列がある表、基礎知識＝冒頭に1文の定義）。全記事に、中身のある3行以上の早見表か比較表を1つ以上入れる（空欄・ダッシュ・「人による」だけの表は不可）
- 主キーワードをタイトル前半・説明文・冒頭に、補助キーワードを本文に入れる。詰め込みすぎ（1,000字あたり30回超など）も不合格
- 出典で裏付けた記述が4か所以上・出典2種以上。数値も出典も具体的な手順もないH2は半数まで
- 単位つきの数値と比率（g・ml・℃・分・回・1:15 など）には出典番号 [n] を付ける。チェックリストも同じ。タイトル・説明文・見出しに書く数値は、本文で出典を付けたものに限る
- 同じ文の繰り返しなし。決まり文句（「いかがでしたか」「様々な」「ぜひ」など）は1,000字あたり2回まで、あいまいな言い回し（「人によって」「少しずつ」など）は3回まで
- 既存記事との本文の類似度（文字3-gram）0.30未満。同じ文の使い回しは2文まで、言い換えに近い文は2割未満、数値の組み合わせの重なりは0.5未満、同じかほぼ同じH2は1つまで
- 150字未満の薄いH2を2つ以上作らない。公開済み記事は文字数・H2の数・FAQの数も確かめる

`python3 tools/quality/article_quality.py --all` で公開中の全記事を判定できる（verify.sh でも実行）。

記事JSONには `format` と `category`（`site.json` の `categories` の slug）を入れる。カテゴリに記事が1本以上あると `category/<slug>/` のページができ、パンくずは「ホーム › カテゴリ › 記事」になる。本文で別の記事に触れるときは `[[slug|リンク文]]` と書くとリンクになる。

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
- テーマの追加・並べ替え・除外: `docs/auto-queue.csv` を編集。新しいテーマには `docs/sources.json` に同じ slug で出典（数値や定義が本文に載っているページ）を2件以上入れておくと確実（なければ自動調査に回る）
- 「出典不足」のテーマ: `docs/sources.json` に出典を足し、キューの状態を「待機」に戻すと次の実行で再挑戦する
- 自動調査の検索先: `tools/auto-publish/config.json` の `source_domains` を編集
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
