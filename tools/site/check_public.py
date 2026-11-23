#!/usr/bin/env python3
"""公開用に集めたフォルダ（collect_public.sh の出力）だけで、サイト内のリンク先がすべて存在するかを確かめる。

check.py はリポジトリ内の生成物を見るので、公開時のコピー漏れ（例: category/ を集めていない）は見つけられない。
使い方: python3 tools/site/check_public.py <公開用フォルダ>
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("SITE_ROOT", Path(__file__).resolve().parents[2]))


def exists(base, rel):
    p = (base / rel).resolve() if rel else base.resolve()
    return (p / "index.html").exists() if p.is_dir() else p.exists()


def main():
    pub = Path(sys.argv[1]).resolve()
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    base_url = site["base_url"]
    base_path = urlparse(base_url).path
    errors = []
    pages = sorted(pub.rglob("*.html"))
    for page in pages:
        rel = page.relative_to(pub).as_posix()
        src = page.read_text(encoding="utf-8")
        urls = re.findall(r'(?:href|src)="([^"]+)"', src)
        urls += [u for u in re.findall(r'content="([^"]+)"', src) if u.startswith(base_url)]  # og:image など
        for url in urls:
            if url.startswith(base_url):
                target = urlparse(url).path[len(base_path):]
                if not exists(pub, target):
                    errors.append(f"{rel}: 公開物にない {url}")
            elif url.startswith(base_path) and url != base_path:
                if not exists(pub, urlparse(url).path[len(base_path):]):
                    errors.append(f"{rel}: 公開物にない {url}")
            elif not url.startswith(("http://", "https://", "#", "mailto:", "/")):
                path = urlparse(url).path
                if path and not exists(page.parent, path):
                    errors.append(f"{rel}: 公開物にない {url}")
    for loc in re.findall(r"<loc>([^<]+)</loc>", (pub / "sitemap.xml").read_text(encoding="utf-8")):
        if not exists(pub, loc[len(base_url):]):
            errors.append(f"sitemap.xml: 公開物にない {loc}")
    print(f"public pages: {len(pages)}")
    if errors:
        print("ERRORS:")
        for x in sorted(set(errors)):
            print("  " + x)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
