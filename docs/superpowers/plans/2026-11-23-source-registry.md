# 出典リスト＋自動調査 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 記事を書く前に取得確認済みの出典を2件以上そろえ、その本文を ChatGPT に渡して書かせる。そろわないテーマは「出典不足」にして次へ回す。

**Architecture:** `tools/auto-publish/sources.py` に出典の取得確認・出典リスト・自動調査をまとめ、`pipeline.py` の `run()` は「テーマを選ぶ→出典をそろえる→書く」の順に変える。出典リストは `docs/sources.json`。

**Tech Stack:** Python 3 標準ライブラリのみ。テストは unittest（`tools/auto-publish/tests/test_pipeline.py`）。

**Spec:** `docs/superpowers/specs/2026-11-23-source-registry-design.md`

## Global Constraints

- 外部ライブラリなし（Python標準ライブラリのみ）。
- 品質ゲート（tools/quality）と審査の基準は変えない。
- 確認済み出典の最低数は `config.json` の `min_verified_sources`（2）。
- 1回の実行で試すテーマは最大3件（`config.json` の `max_topics_per_run`）。
- 自動調査は `web_search_20250305`、`allowed_domains` = `config.json` の `source_domains`、`max_uses` = 5。
- キューの新しい状態は「出典不足(YYYY-MM-DD)」。
- 出典リストの項目: `title`・`url`・`note`・`found_by`（`manual` | `auto`）。
- `bash tools/verify.sh` が通ること。

## Review Focus

- 出典リストのURLが本番で取得失敗（ボット拒否など）→ 自動調査に回り、テーマごと止まらない（Task 2 のテスト）。
- 自動調査の応答にJSONがない・候補が0件 → 例外で落ちず「出典不足」になる（Task 2 のテスト）。
- 自動調査が同じURLを重複して返す、出典リストと同じURLを返す → 重複して数えない（Task 2 のテスト）。
- ChatGPT が一覧にないURLを sources に入れる → 保留（Task 3 のテスト）。
- 3テーマとも出典不足 → 記事を書かず blocked、キューの変更は残る（Task 3 のテスト）。

---

### Task 1: 出典の取得確認を直す（転送・本文抽出）

**Files:**
- Create: `tools/auto-publish/sources.py`
- Modify: `tools/auto-publish/pipeline.py`（`html_to_text`・`fetch_source` を sources.py へ移し、import して使う）
- Test: `tools/auto-publish/tests/test_pipeline.py`（`SourceFetchTest` を追加）

**Interfaces:**
- Produces: `same_page(requested: str, final: str) -> bool`、`extract_text(raw_html: str) -> str`、`fetch_source(url: str) -> tuple[bool, str]`（MOCK時は今と同じく sources.json の表を引く）

- [ ] Step 1: テスト `test_same_page`: `same_page("https://www.ncausa.org/About-Coffee/How-to-Brew-Coffee", "https://www.aboutcoffee.org/brewing/")` は False、`same_page("http://example.org/a", "https://www.example.org/a/")` は True。`test_extract_prefers_main`: `<nav>メニュー…</nav><main>本文 93℃</main>` から「本文 93℃」を含み「メニュー」を含まない。
- [ ] Step 2: 実行して失敗を確認 `python3 tools/auto-publish/tests/test_pipeline.py SourceFetchTest`
- [ ] Step 3: 実装。`fetch_source` は `r.geturl()` と元URLを `same_page` で比べ、違えば `(False, "転送先が別ページ: <final>")`。
- [ ] Step 4: テストが通ることを確認。

### Task 2: 出典リストと自動調査

**Files:**
- Modify: `tools/auto-publish/sources.py`、`tools/auto-publish/config.json`、`tools/auto-publish/prompts.py`（`RESEARCH_SYSTEM`・`RESEARCH_USER`）
- Test: `tools/auto-publish/tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1 の `fetch_source`
- Produces: `gather_sources(task: dict, cfg: dict, ask_search) -> list[dict]`（各要素 `{"title","url","note","excerpt"}`、確認済みのみ、URL重複なし）。`load_registry() -> dict`、`save_registry(reg: dict)`。pipeline 側に `ask_claude_search(system, user, domains, max_uses) -> dict`（MOCK時は `research_N.json`）。

- [ ] Step 1: テスト（pipeline 通しテスト内）: 出典リストにあるテーマは自動調査を呼ばない（research_1.json がなくても成功）。出典リストにないテーマは research_1.json の候補を使い、`docs/sources.json` に `found_by: auto` で書き戻す。候補が取得できない・JSONがない場合は「出典不足(日付)」。重複URLは1件と数える。
- [ ] Step 2: 失敗を確認。
- [ ] Step 3: 実装。出典リスト→不足なら自動調査→取得確認。自動調査の応答はテキスト部分のJSON（`{"sources":[...]}`）を使い、なければ `web_search_tool_result` のURLを候補にする。`stop_reason == "pause_turn"` は最大2回まで続きを要求する。
- [ ] Step 4: テストが通ることを確認。

### Task 3: 書く前に出典を渡す流れにする

**Files:**
- Modify: `tools/auto-publish/pipeline.py`（`run()`）、`tools/auto-publish/prompts.py`（`WRITER_SYSTEM`・`WRITER_USER` に出典一覧と抜粋）
- Test: `tools/auto-publish/tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 2 の `gather_sources`
- Produces: `run()` の結果に変更なし（status: created | blocked | skipped | error）。

- [ ] Step 1: テスト: 1件目のテーマが出典不足なら2件目で記事ができ、1件目は「出典不足(日付)」。3件とも不足なら blocked で記事なし。原稿の sources に一覧にないURLがあれば blocked（理由に「確認済み一覧にない出典」）。ChatGPT への依頼に出典の抜粋が入る（MOCK時に依頼文を `AUTO_PUBLISH_MOCK` の `requests.log` に書き、テストで確かめる）。
- [ ] Step 2: 失敗を確認。
- [ ] Step 3: 実装。既存テストのセットアップで `docs/sources.json` に SLUGS の出典（fx.SRC）を登録する。
- [ ] Step 4: `python3 tools/auto-publish/tests/test_pipeline.py` が全部通る。

### Task 4: 10テーマの出典登録・キュー・README

**Files:**
- Create: `docs/sources.json`
- Modify: `docs/auto-queue.csv`（hand-drip-basic-steps を「待機」に）、`README.md`

- [ ] Step 1: 各テーマの出典を Web取得で中身を確かめて登録（2〜4件、数値か定義が載っているもの）。
- [ ] Step 2: `python3 -c` で sources.json の全テーマが2件以上・URLが https であることを確認。
- [ ] Step 3: README の「自動記事の流れ」「運用」を更新。
- [ ] Step 4: `bash tools/verify.sh` が通る。ブランチ `feat/source-registry` にコミットし、PRを出す。
