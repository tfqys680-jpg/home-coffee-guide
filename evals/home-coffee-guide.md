# はじめてのおうちコーヒー 完成までのハーネス 合格条件

決めた人: Masayuki / 日付: 2026-11-23

## 依頼者の回答（2026-11-23）

- 範囲: 記事の品質ゲート、残りのSEO改善、最初の記事の公開まで
- 完成の判断: 機械チェックが全部通る／競合と並べて遜色ない／Googleに載る／放置で回り続ける
- 過去に「作れたけどダメだった」点: 内容が薄く、どの記事も似通う

## トリガープロンプト（競合比較スキル `.claude/skills/coffee-competitor-check`）

- 発火すべき: 「公開した記事を検索上位と比べて」「hand-drip-basic-steps の記事、競合と比べて足りないところある？」
- 発火すべきでない: 「CSSの色を変えて」「README を直して」

## 合格条件

### A. 機械チェックが全部通る

- [ ] A1 `bash tools/verify.sh` が通る（生成HTMLが最新・サイト検証・全テスト） — 判定: script
- [ ] A2 公開中の全記事が品質ゲートに合格する（`python3 tools/quality/article_quality.py --all`） — 判定: script
- [ ] A3 Claude SEO の page_checks（トップ・カテゴリ・記事）で Critical/High/Medium が 0、og:image あり — 判定: script

### B. 競合と並べて遜色ない

- [ ] B1 記事ごとの競合比較（主キーワードの検索上位3件）で、上位記事の多くが扱う論点を記事がすべて扱っている — 判定: 競合比較レポート `docs/competitor/<slug>.md`
- [ ] B2 上位記事にない要素（出典付きの早見表・比較表、症状別の直し方など）が1つ以上ある — 判定: 同レポート
- [ ] B3 依頼者が上位記事と並べて読み、見劣りしないと判断する — 判定: 人（要確認）

### C. Google に載る

- [ ] C1 Search Console の所有権確認とサイトマップ送信が済んでいる — 判定: 依頼者
- [ ] C2 公開記事が sitemap.xml に載り、トップとカテゴリページの両方からリンクされ、公開物（deploy.yml が集めるファイル）にリンク先がすべてある — 判定: check.py・check_public.py
- [ ] C3 公開から14日以内に、Search Console の URL 検査で「URL は Google に登録されています」になる — 判定: 依頼者または Chrome（要確認）

### D. 放置で回り続ける

- [ ] D1 自動記事が週2回動き、合格した記事は自動で公開、不合格・途中停止・キュー切れは Issue で知らせる — 判定: pipeline・ship.sh のテスト＋実運用
- [ ] D2 品質ゲートに落ちた原稿は、指摘を渡して自動で1回推敲し直してから判定する — 判定: pipeline テスト
- [ ] D3 キューが空になったら自動でテーマを補充する — 判定: pipeline テスト `test_empty_queue_is_refilled_and_published_at_production_length`

### E. 薄く・似通わない（過去の失敗への対策）

- [ ] E1 同じ文の繰り返しがなく、決まり文句（「いかがでしたか」「様々な」「ぜひ」など）が基準以下 — 判定: 品質ゲート
- [ ] E2 既存記事との本文の類似度と、H2見出しの重複が基準以下 — 判定: 品質ゲート
- [ ] E3 記事の形式（手順・比較・トラブル解決・基礎知識）ごとに必須のブロック（手順なら番号付きの手順、比較なら比較表など）があり、全記事に早見表か比較表が1つ以上ある — 判定: 品質ゲート
- [ ] E4 主キーワードがタイトルの前半・説明文・冒頭に入り、補助キーワードが見出しか本文に入っている — 判定: 品質ゲート
- [ ] E5 単位つきの数値には出典番号が付いている — 判定: 品質ゲート
- [ ] E6 品質ゲートが「薄く似通う」見本の原稿を落とし、良い見本の原稿を通す — 判定: tools/quality/tests

### F. 滞在時間が短く、商品ページへ移らない状態を起こさない（2026-11-27 追加）

依頼者の回答（2026-11-27）: 「画像は増えたけれど、これでは駄目だ」となるのは、滞在時間が短く、アフィリエイトリンクへ移動しないこと。動画・図解・アイキャッチで引き込まれるサイトにし、ルールとして追加する。「架空の体験を書かない」は維持する（体験談を作ると、読者・景品表示法・ASP規約・Google の評価のいずれにも反するため）。

- [ ] F1 全記事に、記事の visual から作ったアイキャッチ（1200x675）・SNS共有用の画像（1200x630）・無音の図解動画（12〜60秒、文字版つき）・ページ内の図解がある — 判定: 品質ゲート（visual の必須化）・check.py（ファイル・大きさ・重さ・visual との一致）
- [ ] F2 図解と動画に描く事実は出典で確かめたものだけ（項目ごとに cite）。アイキャッチの見出しに単位つきの数値を入れない — 判定: 品質ゲート・Claude の審査
- [ ] F3 全記事に、記事の選び方の条件で Amazon・楽天を検索するリンクが記事中と記事末にある。商品名・順位・「おすすめ」・使った感想は書かない。アフィリエイトIDがあるときは PR 表記と rel="sponsored" を付ける — 判定: 品質ゲート・check.py・build テスト
- [ ] F4 トップ・カテゴリ・記事末の「次に読む」がサムネイル付きで、記事から次の記事へ移れる — 判定: check.py
- [ ] F5 自動記事でも F1〜F4 が満たされる（パイプラインが画像・動画を作り、ない原稿は保留） — 判定: pipeline テスト
- [ ] F6 依頼者がスマホで記事を開き、最初の画面と図解・動画・商品の探し方で「読み進めたくなる」と判断する — 判定: 人（要確認）
- [ ] F7 公開後30日の GA4 で、記事ページの平均エンゲージメント時間と、記事ページの閲覧に対する affiliate_click の割合を見る。目標値は依頼者が決める（叩き台: 60秒以上・3%以上） — 判定: 依頼者（要確認。GA4 の測定IDとアフィリエイトIDの登録が前提）

## 判定記録

2026-11-23。別文脈のエージェント2つで確認した（1つ目: 品質ゲートのすり抜けを11種試す red-team、2つ目: 証拠だけを見て判定する評価者）。「修正後」は評価者の指摘を直してテストを足したもの。

| 条件 | ○/× | 証拠 | 修正内容 |
|---|---|---|---|
| A1 | ○ | `bash tools/verify.sh` 終了コード0（記事0本の時点） | — |
| A2 | 保留 | 公開記事がまだ0本 | 最初の記事の公開後に `article_quality.py --all` |
| A3 | 保留（見本では○） | 見本サイトのトップ・カテゴリ・記事・運営者情報で page_checks 0件 | 公開後に実URLで測る |
| B1 | 保留 | 公開記事がない。パイプラインの点検は Claude の知識による自己点検 | 公開後に `coffee-competitor-check`（実際の検索結果と比較） |
| B2 | 保留 | 同上 | 同上 |
| B3 | 保留 | 人の判断 | 依頼者が上位記事と並べて読む |
| C1 | 保留 | 確認タグは公開済み（PR #2） | 依頼者が Search Console で確認・サイトマップ送信 |
| C2 | ○（修正後） | `test_published_files_include_every_linked_page` | deploy.yml が category/ を公開していなかった → `collect_public.sh` と `check_public.py` を追加し verify.sh で確認 |
| C3 | 保留 | 公開と14日の経過がまだ | URL 検査 |
| D1 | 保留 | コード・Issue 通知はテスト済み（`ShipNotificationTest`）。11/17・11/20 の定期実行は publish ジョブが skipped | APIキーと `AUTO_PUBLISH_ENABLED` の登録（依頼者）。途中停止・キュー切れも Issue で通知するよう修正 |
| D2 | ○ | `test_quality_failure_is_fixed_in_one_more_round` / `..._after_fix_round_is_held` | — |
| D3 | ○（修正後） | `test_empty_queue_is_refilled_and_published_at_production_length` | 補充のテストがなかった → 追加 |
| E1 | ○ | `ThinSample`、red-team 6 | — |
| E2 | ○（修正後） | red-team 1・7・7b、`test_near_identical_headings_are_counted` | ほぼ同じH2も数える、類似度の上限0.30、同じ文・言い換え・数値の使い回しを判定 |
| E3 | ○（修正後） | `FormatRules`、`test_basics_format_needs_a_definition`、red-team 3a・3b | 中身のない表・空の手順を不可、基礎知識に定義を必須に |
| E4 | ○（修正後） | `test_description_needs_main_keyword` | 説明文もタイトルと同じ基準に |
| E5 | ○（修正後） | `test_numbers_in_checklist_need_citations` ほか | チェックリスト・見出し・説明文・比率・回数・全角数字も対象に |
| E6 | ○（修正後） | red-team 11種すべて不合格、`test_long_good_article_passes_with_production_limits` | 本番の文字数の良い見本を追加し、誤って落とさないことを確認 |

採用しなかった案: H2の「意図」（とは・選び方・手入れなど）で骨組みの一致を判定する案。単語リスト頼みで誤判定が出やすく、同じ攻撃は事実の裏付け・表の中身の判定で落ちるため。

### 2026-11-27（F の追加）

| 条件 | ○/× | 証拠 | 修正内容 |
|---|---|---|---|
| F1 | ○ | `check.py`（全4記事）、`test_media_and_shop_are_required_on_article_pages` | 画像・動画の生成器 `tools/media/make_media.py` を追加 |
| F2 | ○ | `VisualAndShoppingRules`（品質ゲートのテスト） | 図解の項目ごとに cite を必須にし、数値の出典を検査 |
| F3 | ○ | `test_shop_links_become_affiliate_links_with_disclosure`、`test_shopping_must_not_recommend_or_invent_numbers` | 検索リンク方式。IDが空のうちは通常の検索リンク（収益なし） |
| F4 | ○ | `check.py`（サムネイル・次に読む） | トップの記事一覧をヒーロー直下へ移動 |
| F5 | ○ | `test_two_articles_published_and_linked`（画像・動画の生成まで）、`test_article_without_visual_or_shopping_is_held` | ci.yml・auto-publish.yml に ffmpeg・日本語フォント・Pillow を追加 |
| F6 | 保留 | スマホ（390px）とPCのスクリーンショットで目視確認済み | 依頼者の判断待ち |
| F7 | 保留 | GA4 の `affiliate_click`・`video_start`・`video_complete` イベントを実装 | 測定ID（site.json の ga_id）とアフィリエイトID（site.json の affiliate）の登録待ち |

