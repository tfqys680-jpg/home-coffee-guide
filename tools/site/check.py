#!/usr/bin/env python3
"""生成済みサイトの検証。失敗があれば終了コード1。

- 各ページ: title / description / canonical / h1が1つ / タイトル重複なし
- 内部リンク切れなし、JSON-LDが読める、パンくずの表示とJSON-LDが一致
- 記事ページがトップとsitemapから辿れる
- 記事本文に禁止表現（健康効果の断定など）がない
"""
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("SITE_ROOT", Path(__file__).resolve().parents[2]))


def banned_phrases():
    cfg = json.loads((ROOT / "tools/auto-publish/config.json").read_text(encoding="utf-8"))
    return cfg["banned_phrases"]


def text_of(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def main():
    errors = []
    pages = sorted(p for p in ROOT.rglob("*.html") if ".git" not in p.parts and "node_modules" not in p.parts
                   and not str(p.relative_to(ROOT)).startswith(("tools/", "content/", "docs/")))
    titles = {}
    banned = banned_phrases()
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
                ld_names = [x["name"] for x in data["itemListElement"]]
                if dom_names != ld_names:
                    errors.append(f"{rel}: パンくずの表示とJSON-LDが不一致 {dom_names} != {ld_names}")
        if rel == "404.html":
            continue
        for href in re.findall(r'href="([^"]+)"', src):
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target = (page.parent / urlparse(href).path).resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                errors.append(f"{rel}: リンク切れ {href}")
        if rel.startswith("column/"):
            body = text_of(re.search(r"<article.*?</article>", src, re.S).group(0)).replace("必ずしも", "")
            for phrase in banned:
                if phrase in body:
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
        if not (ROOT / "content/articles" / f"{d.name}.json").exists():
            errors.append(f"column/{d.name}/ に対応する記事JSONがない")

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
