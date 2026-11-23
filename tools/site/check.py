#!/usr/bin/env python3
"""生成済みサイトの検証。失敗があれば終了コード1。

- 各ページ: title / description / canonical / h1が1つ / タイトル重複なし
- 内部リンク切れなし、JSON-LDが読める、パンくずの表示とJSON-LDが一致
- 記事ページがトップ・カテゴリページ・sitemapから辿れる
- 記事本文に禁止表現（健康効果の断定など）がない
- 画像ファイルが存在し、alt が空でない
- 運営者の確認メモ（運営者本人が書く欄）は体験の表現だけを許し、健康効果の断定などは本文と同じく禁止
"""
import html
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("SITE_ROOT", Path(__file__).resolve().parents[2]))


OPERATOR_NOTE = re.compile(r'<aside class="operator-note".*?</aside>', re.S)


def load_config():
    return json.loads((ROOT / "tools/auto-publish/config.json").read_text(encoding="utf-8"))


def text_of(fragment):
    """タグを除いた本文。NFKC正規化し、ゼロ幅スペースなどの書式文字を除く（禁止表現のすり抜け対策）。"""
    t = unicodedata.normalize("NFKC", html.unescape(re.sub(r"<[^>]+>", " ", fragment)))
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", t).strip()


def main():
    errors = []
    pages = sorted(p for p in ROOT.rglob("*.html") if ".git" not in p.parts and "node_modules" not in p.parts
                   and not str(p.relative_to(ROOT)).startswith(("tools/", "content/", "docs/")))
    titles = {}
    cfg = load_config()
    banned = cfg["banned_phrases"]
    note_allowed = set(cfg.get("operator_note_allowed_phrases", []))
    for page in pages:
        rel = page.relative_to(ROOT).as_posix()
        src = page.read_text(encoding="utf-8")
        t = re.search(r"<title>(.*?)</title>", src, re.S)
        if not t:
            errors.append(f"{rel}: title がない")
        else:
            titles.setdefault(t.group(1), []).append(rel)
        for pat, name in ((r'<meta name="description" content="[^"]+"', "description"), (r'<link rel="canonical" href="https://', "canonical")):
            if not re.search(pat, src):
                errors.append(f"{rel}: {name} がない")
        if len(re.findall(r"<h1[\s>]", src)) != 1:
            errors.append(f"{rel}: h1 が1つではない")
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', src, re.S):
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError as ex:
                errors.append(f"{rel}: JSON-LD が壊れている（{ex}）")
                continue
            if data.get("@type") == "BreadcrumbList":
                dom = re.search(r'<nav class="breadcrumb"[^>]*><ol>(.*?)</ol>', src, re.S)
                dom_names = [text_of(x) for x in re.findall(r"<li>(.*?)</li>", dom.group(1), re.S)] if dom else []
                ld_names = [text_of(x["name"]) for x in data["itemListElement"]]  # 表示側と同じ正規化で比べる
                if dom_names != ld_names:
                    errors.append(f"{rel}: パンくずの表示とJSON-LDが不一致 {dom_names} != {ld_names}")
        if rel == "404.html":
            continue
        for tag in re.findall(r"<img\b[^>]*>", src):
            m_src, m_alt = re.search(r'\bsrc="([^"]*)"', tag), re.search(r'\balt="([^"]*)"', tag)
            img = m_src.group(1) if m_src else ""
            if not (m_alt and m_alt.group(1).strip()):
                errors.append(f"{rel}: 画像の alt がない {img}")
            if img and not img.startswith(("http://", "https://")) and not (page.parent / urlparse(img).path).resolve().exists():
                errors.append(f"{rel}: 画像がない {img}")
        for href in re.findall(r'href="([^"]+)"', src):
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target = (page.parent / urlparse(href).path).resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                errors.append(f"{rel}: リンク切れ {href}")
        if rel.startswith("column/"):
            article = re.search(r"<article.*?</article>", src, re.S).group(0)
            if any(unicodedata.category(ch) == "Cf" for ch in html.unescape(article)):
                errors.append(f"{rel}: 見えない文字（ゼロ幅スペースなど）が含まれる")
            body = text_of(OPERATOR_NOTE.sub(" ", article)).replace("必ずしも", "")
            note = text_of(" ".join(OPERATOR_NOTE.findall(article))).replace("必ずしも", "")
            for phrase in banned:
                if phrase in body or (phrase not in note_allowed and phrase in note):
                    errors.append(f"{rel}: 禁止表現「{phrase}」")
    for title, where in titles.items():
        if len(where) > 1:
            errors.append(f"タイトル重複「{title}」: {where}")

    index = (ROOT / "index.html").read_text(encoding="utf-8")
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    for d in sorted((ROOT / "column").glob("*/")) if (ROOT / "column").exists() else []:
        if f'href="column/{d.name}/"' not in index:
            errors.append(f"column/{d.name}/ がトップから辿れない")
        if f"column/{d.name}/</loc>" not in sitemap:
            errors.append(f"column/{d.name}/ が sitemap にない")
        src = ROOT / "content/articles" / f"{d.name}.json"
        if not src.exists():
            errors.append(f"column/{d.name}/ に対応する記事JSONがない")
            continue
        cat = json.loads(src.read_text(encoding="utf-8"))["article"].get("category")
        if cat:
            page = ROOT / "category" / cat / "index.html"
            if not page.exists() or f'href="../../column/{d.name}/"' not in page.read_text(encoding="utf-8"):
                errors.append(f"column/{d.name}/ がカテゴリページ category/{cat}/ から辿れない")
            if f"category/{cat}/</loc>" not in sitemap:
                errors.append(f"category/{cat}/ が sitemap にない")

    print(f"pages: {len(pages)}")
    if errors:
        print("ERRORS:")
        for x in errors:
            print("  " + x)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
