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
