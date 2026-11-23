"""出典の取得確認・出典リスト（docs/sources.json）・自動調査。

記事を書く前に、取得して中身を確かめた出典をそろえるための部品（pipeline.py から使う）。
外部ライブラリ不要（Python標準ライブラリのみ）。
"""
import html
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

MOCK = os.environ.get("AUTO_PUBLISH_MOCK")
EXCERPT_CHARS = 12000


def _key(url):
    p = urllib.parse.urlsplit(str(url).strip())
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host, (p.path.rstrip("/") or "/"), p.query


def same_page(requested, final):
    """転送後のURLが元と同じページか（http/https、www の有無、末尾の / の違いは同じとみなす）。"""
    return _key(requested) == _key(final)


def _strip(raw):
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def extract_text(raw):
    """HTMLから本文を抜き出す。<main> か <article> があればその中を優先する（メニューで抜粋の枠を使い切らないため）。"""
    raw = re.sub(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    for tag in ("main", "article"):
        parts = re.findall(rf"(?is)<{tag}\b[^>]*>(.*?)</{tag}>", raw)
        text = " ".join(_strip(p) for p in parts).strip()
        if len(text) >= 200 or (text and len(_strip(raw)) < 200):
            return text
    raw = re.sub(r"(?is)<(nav|header|footer|aside)\b[^>]*>.*?</\1>", " ", raw)
    return _strip(raw)


def fetch_source(url):
    """出典URLを取得し (ok, 本文抜粋 または 失敗理由) を返す。"""
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
            if not same_page(url, r.geturl()):
                return False, f"転送先が別ページ: {r.geturl()}"
            if "pdf" in r.headers.get("Content-Type", "").lower():
                return False, "PDFは自動照合できないため除外"
            body = r.read(1_500_000)
            text = extract_text(body.decode(r.headers.get_content_charset() or "utf-8", errors="replace"))
            if len(text) < 200:
                return False, "本文が取得できない"
            return True, text[:EXCERPT_CHARS]
    except Exception as ex:  # noqa: BLE001
        return False, f"取得失敗: {ex}"[:200]


# ---------------------------------------------------------------- 出典リストと自動調査

REGISTRY = "docs/sources.json"


def _root():
    return Path(os.environ.get("SITE_ROOT", Path(__file__).resolve().parents[2]))


def load_registry():
    p = _root() / REGISTRY
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_registry(reg):
    (_root() / REGISTRY).write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def gather_sources(task, cfg, ask_search, research_prompt):
    """テーマの出典をそろえる。出典リスト → 足りなければ自動調査（ask_search）。

    戻り値: (確認済みの出典 [{"title","url","note","excerpt"}], 経過のメモ [str])。
    自動調査で確認できた出典は出典リストに found_by="auto" で書き戻す。
    """
    slug = task["slug"]
    need = cfg["min_verified_sources"]
    limit = cfg.get("max_sources_per_article", 5)
    reg = load_registry()
    verified, notes, seen = [], [], set()

    def try_add(entry, origin):
        url = str(entry.get("url", "")).strip()
        if not url or _key(url) in seen or len(verified) >= limit:
            return False
        seen.add(_key(url))
        ok, text = fetch_source(url)
        if not ok:
            notes.append(f"出典を確認できない（{origin}）: {url} {text}")
            return False
        verified.append({"title": entry.get("title", ""), "url": url, "note": entry.get("note", ""), "excerpt": text})
        return True

    for entry in reg.get(slug, []):
        try_add(entry, "出典リスト")
    from_list = len(verified)
    if len(verified) < need:
        try:
            found = ask_search(research_prompt(task)).get("sources") or []
        except Exception as ex:  # noqa: BLE001  調査の失敗はテーマの出典不足として扱う
            found = []
            notes.append(f"自動調査に失敗: {ex}"[:300])
        added = [e for e in found if isinstance(e, dict) and try_add(e, "自動調査")]
        if added:
            reg.setdefault(slug, []).extend(
                {"title": e.get("title", ""), "url": e["url"].strip(), "note": e.get("note", ""), "found_by": "auto"} for e in added)
            save_registry(reg)
    notes.insert(0, f"出典: 出典リストで{from_list}件・自動調査で{len(verified) - from_list}件を確認（{need}件以上必要）")
    return verified, notes
