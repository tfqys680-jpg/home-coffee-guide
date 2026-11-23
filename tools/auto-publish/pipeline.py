#!/usr/bin/env python3
"""ChatGPT（執筆）× Claude（審査・推敲）の自動記事パイプライン（コーヒーサイト版）。

1. docs/auto-queue.csv から次のテーマを選ぶ（空なら両AIでテーマを補充）
2. ChatGPT が記事原稿をJSONで作成
3. 出典URLを実際に取得し、本文を Claude に渡して照合・推敲（最大 max_review_rounds 回）
4. 機械検証（禁止表現・構成・出典数・関連記事）
5. content/articles/<slug>.json を保存し、tools/site/build.py でサイトを再生成
6. 結果を --result のJSONに書く（GitHub Actions がPR作成・自動マージを判断）

外部ライブラリ不要（Python標準ライブラリのみ）。
環境変数: OPENAI_API_KEY, OPENAI_MODEL, ANTHROPIC_API_KEY, ANTHROPIC_MODEL
テスト用: AUTO_PUBLISH_MOCK=<フィクスチャのディレクトリ>、AUTO_PUBLISH_DATE=YYYY-MM-DD、SITE_ROOT=<サイトの複製>
"""
import argparse
import csv
import datetime as dt
import html
import io
import json
import os
import re
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "site"))
sys.path.insert(0, str(HERE.parent / "quality"))
import prompts  # noqa: E402

ROOT = Path(os.environ.get("SITE_ROOT", HERE.parents[1]))
os.environ.setdefault("SITE_ROOT", str(ROOT))
import build  # noqa: E402
import article_quality  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
MOCK = os.environ.get("AUTO_PUBLISH_MOCK")
_mock_calls = {"openai": 0, "claude": 0}
YMYL_ORDER = {"低": 0, "中": 1, "高": 2}


class PipelineError(Exception):
    pass


# ---------------------------------------------------------------- utilities

def today() -> dt.date:
    forced = os.environ.get("AUTO_PUBLISH_DATE")
    return dt.date.fromisoformat(forced) if forced else dt.datetime.now(JST).date()


def read_csv(rel):
    with open(ROOT / rel, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def write_csv(rel, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    (ROOT / rel).write_text(buf.getvalue(), encoding="utf-8")


def parse_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise PipelineError("AIの応答にJSONが見つかりません")
    return json.loads(text[start:end + 1])


def http_post(url, headers, payload, timeout=900):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as ex:
        raise PipelineError(f"API error {ex.code}: {ex.read().decode()[:500]}") from ex


def require_env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        raise PipelineError(f"環境変数 {name} が未設定です（GitHubのSecrets/Variablesを確認）")
    return v


def mock_response(kind):
    _mock_calls[kind] += 1
    path = Path(MOCK) / f"{kind}_{_mock_calls[kind]}.json"
    if not path.exists():
        raise PipelineError(f"mock fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def ask_openai(system, user):
    if MOCK:
        return mock_response("openai")
    data = http_post(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {require_env('OPENAI_API_KEY')}", "Content-Type": "application/json"},
        {"model": require_env("OPENAI_MODEL"), "response_format": {"type": "json_object"},
         "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
    )
    return parse_json(data["choices"][0]["message"]["content"])


def ask_claude(system, user):
    if MOCK:
        return mock_response("claude")
    data = http_post(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": require_env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"},
        {"model": require_env("ANTHROPIC_MODEL"), "max_tokens": 32000, "system": system,
         "messages": [{"role": "user", "content": user}]},
    )
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return parse_json(text)


def html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def fetch_source(url):
    """出典URLを取得し (ok, 本文抜粋) を返す。"""
    if MOCK:
        table = json.loads((Path(MOCK) / "sources.json").read_text(encoding="utf-8"))
        return (url in table, table.get(url, "取得失敗（mock）"))
    if not str(url).startswith("https://"):
        return False, "https以外のURL"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (home-coffee-guide source check)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                return False, f"HTTP {r.status}"
            if "pdf" in r.headers.get("Content-Type", "").lower():
                return False, "PDFは自動照合できないため除外"
            body = r.read(1_500_000)
            text = html_to_text(body.decode(r.headers.get_content_charset() or "utf-8", errors="replace"))
            if len(text) < 200:
                return False, "本文が取得できない"
            return True, text[:12000]
    except Exception as ex:  # noqa: BLE001
        return False, f"取得失敗: {ex}"[:200]


# ---------------------------------------------------------------- queue & existing

def existing_articles():
    return build.load_articles()


def existing_text(queue_rows=()):
    lines = [f"- {a['article']['title']}（slug: {a['slug']}／主キーワード: {a.get('main_kw', '')}）" for a in existing_articles()]
    lines += [f"- キュー済み: {r[1]}（{r[2]}）" for r in queue_rows]
    return "\n".join(lines) or "（まだありません）"


def refill_queue(cfg):
    header, rows = read_csv(cfg["queue_file"])
    proposed = ask_openai(prompts.TOPIC_SYSTEM, prompts.TOPIC_USER.format(today=today().isoformat(), existing=existing_text(rows)))
    reviewed = ask_claude(prompts.TOPIC_REVIEW_SYSTEM, json.dumps(proposed, ensure_ascii=False))
    known = {r[0] for r in rows} | {a["slug"] for a in existing_articles()}
    added = 0
    for t in reviewed.get("topics", []):
        slug = re.sub(r"[^a-z0-9-]", "", str(t.get("slug", "")).lower())
        if not slug or slug in known:
            continue
        rows.append([slug, t.get("テーマ", ""), t.get("主キーワード", ""), t.get("補助キーワード", ""),
                     t.get("想定読者", ""), t.get("YMYL区分", "中"), "待機", "自動提案: " + str(t.get("備考", ""))])
        known.add(slug)
        added += 1
    write_csv(cfg["queue_file"], header, rows)
    return added


def pick_task(cfg, refill=True):
    header, rows = read_csv(cfg["queue_file"])
    for r in rows:
        if r[6] == "待機":
            return dict(zip(header, r))
    if refill and refill_queue(cfg):
        return pick_task(cfg, refill=False)
    return None


def set_queue_status(cfg, slug, status):
    header, rows = read_csv(cfg["queue_file"])
    for r in rows:
        if r[0] == slug:
            r[6] = status
    write_csv(cfg["queue_file"], header, rows)


# ---------------------------------------------------------------- validation

def all_text(article):
    parts = [article.get(k, "") for k in ("title", "description", "conclusion", "lead", "next_step", "breadcrumb")]
    parts += list(article.get("can_do", [])) + list(article.get("checklist", []))
    for s in article.get("sections", []):
        parts.append(s.get("heading", ""))
        for b in s.get("blocks", []):
            parts += [b.get("text", ""), b.get("label", "")] + list(b.get("items", [])) + list(b.get("lines", [])) + list(b.get("headers", []))
            for row in b.get("rows", []):
                parts += list(row)
    for f in article.get("faq", []):
        parts += [f.get("q", ""), f.get("a", "")]
    return "\n".join(str(p) for p in parts)


def validate(article, cfg, existing_slugs):
    errs = []
    for key in ("title", "breadcrumb", "description", "conclusion", "lead", "next_step"):
        if not str(article.get(key, "")).strip():
            errs.append(f"{key} が空")
    if not 16 <= len(article.get("title", "")) <= 45:
        errs.append(f"title の文字数が範囲外（{len(article.get('title', ''))}字）")
    if not 60 <= len(article.get("description", "")) <= 140:
        errs.append(f"description の文字数が範囲外（{len(article.get('description', ''))}字）")
    if not 4 <= len(article.get("sections", [])) <= 9:
        errs.append("H2の数が4〜9の範囲外")
    if not 3 <= len(article.get("faq", [])) <= 6:
        errs.append("FAQの数が3〜6の範囲外")
    if not 4 <= len(article.get("checklist", [])) <= 12:
        errs.append("チェックリストの数が範囲外")
    if len(article.get("can_do", [])) < 2:
        errs.append("「わかること」が2項目未満")
    sources = article.get("sources", [])
    if len(sources) < cfg["min_verified_sources"]:
        errs.append(f"確認済み出典が{len(sources)}件（{cfg['min_verified_sources']}件以上必要）")
    text = all_text(article)
    if re.search(r"<[a-zA-Z/][^>]*>", text):
        errs.append("本文にHTMLタグが含まれる")
    for n in {int(x) for x in re.findall(r"\[(\d+)\]", text)}:
        if not 1 <= n <= len(sources):
            errs.append(f"存在しない出典番号 [{n}]")
    if article_quality.has_invisible(article):
        errs.append("見えない文字（ゼロ幅スペースなど）が含まれる")
    checked = article_quality.clean(text).replace("必ずしも", "")
    for phrase in cfg["banned_phrases"]:
        if phrase in checked:
            errs.append(f"禁止表現: {phrase}")
    for slug in article.get("related", []):
        if slug not in existing_slugs:
            errs.append(f"存在しない関連記事: {slug}")
    for slug in re.findall(r"\[\[([^|\]]+)\|", text):
        if slug not in existing_slugs:
            errs.append(f"本文のリンク先の記事がない: {slug}")
    if any(build.plain(a["article"]["title"]) == build.plain(article.get("title", "")) for a in existing_articles()):
        errs.append("既存記事とタイトルが重複")
    body_len = sum(len(x) for x in text.split("\n"))
    if body_len < cfg["min_body_chars"]:
        errs.append(f"本文が短すぎる（{body_len}字）")
    return errs


def categories():
    return [c["slug"] for c in build.load_site().get("categories", [])]


def categories_text():
    return "\n".join(f"- {c['slug']}: {c['name']}（{c.get('description', '')}）" for c in build.load_site().get("categories", []))


def existing_headings(existing):
    lines = [f"- {a['article']['title']}: " + " / ".join(build.plain(s["heading"]) for s in a["article"].get("sections", []))
             for a in existing]
    return "\n".join(lines) or "（まだありません）"


def coverage_errors(review):
    """審査（Claude）が返す競合カバーの自己点検を確かめる。"""
    errs = []
    cov = review.get("coverage") or []
    if len(cov) < 5:
        errs.append(f"検索上位の記事が扱う論点の確認が{len(cov)}件（5件以上必要）")
    missing = [c.get("point", "") for c in cov if not c.get("covered") and not str(c.get("note", "")).strip()]
    if missing:
        errs.append(f"検索上位の記事が扱う論点を扱っていない: {'・'.join(missing[:3])}")
    if sum(1 for c in cov if not c.get("covered")) > 2:
        errs.append("検索上位の記事が扱う論点のうち、扱っていないものが3つ以上ある")
    if not str(review.get("unique_value", "")).strip():
        errs.append("上位記事にない、この記事ならではの要素がない")
    return errs


def quality_check(article, task, existing):
    return article_quality.evaluate(article, task["主キーワード"], task["補助キーワード"],
                                    [a["article"] for a in existing], categories())


def append_run_log(date, lines):
    p = ROOT / "docs/run-log.md"
    text = p.read_text(encoding="utf-8").rstrip("\n") if p.exists() else "# 自動記事パイプライン 実行ログ"
    p.write_text(text + f"\n\n## {date.isoformat()}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- main

def run():
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    date = today()
    task = pick_task(cfg)
    if not task:
        return {"status": "skipped", "reason": "キューが空で、新しいテーマも採用されませんでした"}
    slug = task["slug"]
    existing = existing_articles()
    existing_slugs = {a["slug"] for a in existing}
    if slug in existing_slugs or any(a.get("main_kw") == task["主キーワード"] for a in existing):
        set_queue_status(cfg, slug, "重複のため除外")
        return {"status": "blocked", "slug": slug, "reason": "既存記事とslugまたは主キーワードが重複", "auto_merge": True}

    related_list = "\n".join(f"- {a['slug']}: {a['article']['title']}" for a in existing) or "（まだありません）"
    existing_desc = existing_text()
    writer_system = prompts.WRITER_SYSTEM.replace("__RELATED__", related_list).replace("__CATEGORIES__", categories_text())
    article = ask_openai(writer_system, prompts.WRITER_USER.format(
        theme=task["テーマ"], main_kw=task["主キーワード"], sub_kw=task["補助キーワード"],
        reader=task["想定読者"], notes=task["備考"], existing=existing_desc, existing_headings=existing_headings(existing)))

    fetched, issues, verdict, ymyl, review = {}, [], "BLOCK", task["YMYL区分"], {}

    def source_report():
        for s in article.get("sources", []):
            if s.get("url") and s["url"] not in fetched:
                fetched[s["url"]] = fetch_source(s["url"])
        return "\n\n".join(
            f"### [{i}] {s.get('title')} {s.get('url')}\nverified={fetched.get(s.get('url'), (False, ''))[0]}\n"
            f"{fetched.get(s.get('url'), (False, '未取得'))[1]}" for i, s in enumerate(article.get("sources", []), 1))

    def apply_review(r):
        nonlocal article, verdict, ymyl, review
        review = r
        m = re.search(r"PASS|REVISE|BLOCK", str(r.get("verdict", "")).upper())
        verdict = m.group(0) if m else "BLOCK"
        issues.extend(str(x) for x in r.get("issues", []))
        article = r.get("article") or article
        ymyl = max([str(r.get("ymyl", "中")), task["YMYL区分"], ymyl], key=lambda x: YMYL_ORDER.get(x, 1))

    for _ in range(cfg["max_review_rounds"]):
        apply_review(ask_claude(prompts.REVIEWER_SYSTEM, prompts.REVIEWER_USER.format(
            theme=task["テーマ"], main_kw=task["主キーワード"], existing=existing_desc,
            article=json.dumps(article, ensure_ascii=False, indent=1), sources=source_report())))
        if verdict != "REVISE":
            break

    # 品質ゲート（決定論）。落ちたら指摘を渡して推敲し直す（max_quality_rounds 回まで）
    quality = quality_check(article, task, existing)
    for _ in range(cfg.get("max_quality_rounds", 1)):
        problems = quality["errors"] + coverage_errors(review)
        if verdict != "PASS" or not problems:
            break
        apply_review(ask_claude(prompts.REVIEWER_SYSTEM, prompts.QUALITY_FIX_USER.format(
            theme=task["テーマ"], main_kw=task["主キーワード"], sub_kw=task["補助キーワード"], existing=existing_desc,
            errors="\n".join(f"- {x}" for x in problems), article=json.dumps(article, ensure_ascii=False, indent=1),
            sources=source_report())))
        quality = quality_check(article, task, existing)

    errs = validate(article, cfg, existing_slugs)
    errs += [f"品質ゲート: {x}" for x in quality["errors"]]
    errs += [f"競合との比較: {x}" for x in coverage_errors(review)]
    unverified = [s.get("url") for s in article.get("sources", []) if not fetched.get(s.get("url"), (False,))[0]]
    if unverified:
        errs.append(f"取得確認できない出典が残っている: {unverified}")
    if verdict != "PASS":
        errs.append(f"Claudeの審査結果が {verdict}")

    log = [f"テーマ: {task['テーマ']}（column/{slug}/）", f"Claude審査: {verdict}／YMYL: {ymyl}",
           f"出典の取得確認: {sum(1 for v in fetched.values() if v[0])}/{len(fetched)}件"]
    log += [f"審査指摘: {x}" for x in issues[:20]]
    log.append("品質ゲート: " + ("合格" if quality["pass"] else "不合格") + f"（{json.dumps(quality['metrics'], ensure_ascii=False)}）")
    log += [f"品質ゲートの注意: {x}" for x in quality["warnings"]]
    log += [f"競合の論点: {c.get('point')}（{'扱った' if c.get('covered') else '扱わない: ' + str(c.get('note', ''))}）"
            for c in review.get("coverage", [])]
    if review.get("unique_value"):
        log.append(f"独自の要素: {review['unique_value']}")

    if errs:
        set_queue_status(cfg, slug, f"保留({date.isoformat()})")
        log += [f"不合格: {x}" for x in errs] + ["結果: 公開せず保留"]
        append_run_log(date, log)
        (ROOT / "docs/last-rejected.json").write_text(json.dumps(
            {"slug": slug, "errors": errs, "issues": issues, "article": article}, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"status": "blocked", "slug": slug, "reason": "; ".join(errs), "issues": issues, "auto_merge": True}

    auto_merge = cfg["auto_merge"] and ymyl in cfg["auto_merge_ymyl_levels"]
    related = [r for r in article.pop("related", []) if r in existing_slugs]
    item = {"slug": slug, "date": date.isoformat(), "updated": date.isoformat(), "ymyl": ymyl, "main_kw": task["主キーワード"],
            "sub_kw": task["補助キーワード"], "related": related,
            "pipeline": {"writer": "ChatGPT", "reviewer": "Claude", "verdict": verdict, "issues": issues,
                         "coverage": review.get("coverage", []), "unique_value": review.get("unique_value", ""),
                         "quality": quality["metrics"]},
            "article": article}
    (ROOT / "content/articles").mkdir(parents=True, exist_ok=True)
    (ROOT / "content/articles" / f"{slug}.json").write_text(json.dumps(item, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # 既存記事からも新記事へリンクを張る（関連として選ばれた記事の related に追加）
    for r in related:
        p = ROOT / "content/articles" / f"{r}.json"
        other = json.loads(p.read_text(encoding="utf-8"))
        if slug not in other.get("related", []):
            other.setdefault("related", []).append(slug)
            p.write_text(json.dumps(other, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    build.build()
    set_queue_status(cfg, slug, f"公開({date.isoformat()})" if auto_merge else f"PR確認待ち({date.isoformat()})")
    log.append("結果: " + ("検証通過後に自動マージ・公開" if auto_merge else "YMYL高のためPRで確認待ち"))
    append_run_log(date, log)
    (ROOT / "docs/last-rejected.json").unlink(missing_ok=True)
    site = build.load_site()
    return {"status": "created", "slug": slug, "title": article["title"], "ymyl": ymyl, "auto_merge": auto_merge,
            "issues": issues, "url": f"{site['base_url']}column/{slug}/"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", default="/tmp/auto-publish-result.json")
    args = ap.parse_args()
    try:
        result = run()
    except PipelineError as ex:
        result = {"status": "error", "reason": str(ex)}
    except Exception as ex:  # noqa: BLE001  想定外の失敗も結果ファイルに残して通知する
        result = {"status": "error", "reason": f"{type(ex).__name__}: {ex}", "trace": traceback.format_exc()[-2000:]}
    Path(args.result).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
