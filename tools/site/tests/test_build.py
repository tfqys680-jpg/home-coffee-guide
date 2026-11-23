#!/usr/bin/env python3
"""サイト生成と検証のテスト（Search Console 確認タグ、運営者プロフィール、運営者の確認メモ・写真）。

サイトを一時ディレクトリへ複製して build.py と check.py を実行する。リポジトリ本体は変更しない。
実行: python3 tools/site/tests/test_build.py
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SLUG = "zz-test-human-check"


def sample_article():
    spec = importlib.util.spec_from_file_location("tp", REPO / "tools/auto-publish/tests/test_pipeline.py")
    tp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tp)
    return tp.sample_article(1)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="coffee-build-test-"))
        self.site = self.tmp / "site"
        shutil.copytree(REPO, self.site, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self.env = dict(os.environ, SITE_ROOT=str(self.site), PYTHONDONTWRITEBYTECODE="1")
        # 本番の site.json に値が入っていても、既定の挙動を試せるよう空に戻す
        self.set_site(gsc_verification="", operator_profile=[])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def set_site(self, **kv):
        p = self.site / "site.json"
        site = json.loads(p.read_text(encoding="utf-8"))
        site.update(kv)
        p.write_text(json.dumps(site, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def add_article(self, operator=None, article=None):
        item = {"slug": SLUG, "date": "2026-11-20", "updated": "2026-11-20", "ymyl": "低", "main_kw": "試験",
                "related": [], "article": article or sample_article()}
        if operator is not None:
            item["operator"] = operator
        d = self.site / "content/articles"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{SLUG}.json").write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")

    def add_photo(self, name="drip.jpg"):
        d = self.site / "images/articles" / SLUG
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(b"\xff\xd8\xff\xd9")  # 中身は問わない（存在確認のみ）
        return f"images/articles/{SLUG}/{name}"

    def build(self):
        p = subprocess.run([sys.executable, str(self.site / "tools/site/build.py")], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def check(self):
        return subprocess.run([sys.executable, str(self.site / "tools/site/check.py")], env=self.env,
                              capture_output=True, text=True)

    def assert_check_ok(self):
        p = self.check()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def assert_check_fails(self, needle):
        p = self.check()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn(needle, p.stdout)

    def page(self, rel):
        return (self.site / rel).read_text(encoding="utf-8")

    def article_ld(self):
        src = self.page(f"column/{SLUG}/index.html")
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', src, re.S):
            data = json.loads(m.group(1))
            if data.get("@type") == "Article":
                return data
        self.fail("Article の JSON-LD がない")

    # ---------------------------------------------------------------- Search Console
    def test_no_verification_tag_by_default(self):
        self.build()
        self.assertNotIn("google-site-verification", self.page("index.html"))

    def test_verification_tag_on_every_page(self):
        self.set_site(gsc_verification="abc123XYZ")
        self.add_article()
        self.build()
        for rel in ("index.html", "about.html", "privacy.html", "disclaimer.html", f"column/{SLUG}/index.html"):
            head = self.page(rel).split("</head>")[0]
            self.assertIn('<meta name="google-site-verification" content="abc123XYZ">', head, rel)
        self.assert_check_ok()

    # ---------------------------------------------------------------- 運営者プロフィール
    def test_operator_profile_on_about_page(self):
        self.set_site(operator_profile=["家で毎朝ハンドドリップで淹れています。", "誤りの指摘は連絡先までお願いします。"])
        self.build()
        about = self.page("about.html")
        self.assertIn("<h2>運営者について</h2>", about)
        self.assertIn("<p>家で毎朝ハンドドリップで淹れています。</p>", about)
        self.assertLess(about.index("運営者について"), about.index("記事の作り方"))
        self.assert_check_ok()

    def test_no_profile_section_by_default(self):
        self.build()
        self.assertNotIn("運営者について", self.page("about.html"))

    # ---------------------------------------------------------------- カテゴリ・内部リンク・OGP
    def test_category_page_and_breadcrumb(self):
        self.add_article()
        self.build()
        cat = self.page("category/brew/index.html")
        self.assertIn("<h1>淹れ方の記事</h1>", cat)
        self.assertIn(f'href="../../column/{SLUG}/"', cat)
        page = self.page(f"column/{SLUG}/index.html")
        self.assertIn('<li><a href="../../">ホーム</a></li><li><a href="../../category/brew/">淹れ方</a></li>', page)
        crumbs = [json.loads(m.group(1)) for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)]
        crumbs = next(c for c in crumbs if c["@type"] == "BreadcrumbList")
        self.assertEqual([x["name"] for x in crumbs["itemListElement"]], ["ホーム", "淹れ方", "粉の量の目安"])
        self.assertIn("category/brew/</loc>", self.page("sitemap.xml"))
        self.assertIn('href="category/brew/"', self.page("index.html"))
        self.assert_check_ok()

    def test_no_category_pages_without_articles(self):
        self.build()
        self.assertFalse((self.site / "category").exists())
        self.assertNotIn("カテゴリ", self.page("index.html"))

    def test_link_in_body_rendered(self):
        art = sample_article()
        art["lead"] += "落ちるのが遅いときは[[slow-drip-fix|ドリップが遅いときの直し方]]も参考になります。"
        self.add_article(article=art)
        other = dict(json.loads((self.site / f"content/articles/{SLUG}.json").read_text(encoding="utf-8")), slug="slow-drip-fix")
        other["article"] = dict(other["article"], title="ドリップが遅いときの直し方", breadcrumb="遅いとき")
        (self.site / "content/articles/slow-drip-fix.json").write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
        self.build()
        page = self.page(f"column/{SLUG}/index.html")
        self.assertIn('<a href="../slow-drip-fix/">ドリップが遅いときの直し方</a>', page)
        self.assertNotIn("[[", page)
        self.assert_check_ok()

    def test_home_links_point_to_directory(self):
        self.build()
        about = self.page("about.html")
        self.assertNotIn('href="index.html', about)
        self.assertIn('<a href="./">ホーム</a>', about)

    # ---------------------------------------------------------------- 確認メモ・写真
    def test_article_without_operator_note_keeps_ai_notice(self):
        self.add_article()
        self.build()
        page = self.page(f"column/{SLUG}/index.html")
        self.assertIn("人による実際の試飲や器具のテストは行っていません", page)
        self.assertNotIn('class="operator-note"', page)
        # 写真がないときはサイト共通のOGP画像を使う
        self.assertEqual(self.article_ld()["image"], ["https://tfqys680-jpg.github.io/home-coffee-guide/images/ogp.png"])
        self.assertIn('<meta property="og:image" content="https://tfqys680-jpg.github.io/home-coffee-guide/images/ogp.png">', page)
        self.assert_check_ok()

    def test_operator_note_and_photo_rendered(self):
        src = self.add_photo()
        self.add_article(operator={
            "checked": "2026-11-22",
            "notes": ["私が実際に淹れて、粉と湯の量を毎回量るようにしたら味のぶれが減りました。"],
            "photos": [{"src": src, "alt": "ドリッパーに粉を入れて湯を注いでいるところ", "width": 1200, "height": 800,
                        "caption": "自宅で淹れたときの様子"}]})
        self.build()
        page = self.page(f"column/{SLUG}/index.html")
        self.assertIn('class="operator-note"', page)
        self.assertIn("私が実際に淹れて", page)
        self.assertIn(f'<img src="../../{src}" alt="ドリッパーに粉を入れて湯を注いでいるところ" width="1200" height="800"', page)
        self.assertIn("<figcaption>自宅で淹れたときの様子</figcaption>", page)
        self.assertIn("2026年11月22日", page)
        # 人の確認があるのに「人は試していない」とだけ書かない
        self.assertNotIn("人による実際の試飲や器具のテストは行っていません", page)
        self.assertIn("それ以外の本文", page)
        ld = self.article_ld()
        self.assertEqual(ld["image"], ["https://tfqys680-jpg.github.io/home-coffee-guide/" + src])
        self.assertIn(f'<meta property="og:image" content="https://tfqys680-jpg.github.io/home-coffee-guide/{src}">', page)
        self.assertEqual(ld["dateModified"], "2026-11-22")
        self.assertEqual(ld["contributor"]["@type"], "Person")
        self.assertIn(f"column/{SLUG}/</loc><lastmod>2026-11-22</lastmod>", self.page("sitemap.xml"))
        self.assert_check_ok()

    def test_health_claim_in_operator_note_rejected(self):
        self.add_article(operator={"checked": "2026-11-22", "notes": ["毎日飲むと免疫力を高める気がします。"]})
        self.build()
        self.assert_check_fails("禁止表現「免疫力を高め」")

    def test_experience_phrase_outside_note_still_rejected(self):
        art = sample_article()
        art["lead"] = "私が実際に飲んで確かめました。"
        self.add_article(article=art)
        self.build()
        self.assert_check_fails("禁止表現「私が」")

    def test_invisible_characters_cannot_hide_banned_phrases(self):
        art = sample_article()
        art["lead"] = "毎日飲むと" + "\u200b".join("脂肪燃焼") + "につながります。"
        self.add_article(article=art)
        self.build()
        p = self.check()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("禁止表現「脂肪燃焼」", p.stdout)
        self.assertIn("見えない文字", p.stdout)

    def test_missing_photo_file_rejected(self):
        self.add_article(operator={"checked": "2026-11-22", "notes": ["メモ"],
                                   "photos": [{"src": f"images/articles/{SLUG}/none.jpg", "alt": "写真",
                                               "width": 800, "height": 600}]})
        self.build()
        self.assert_check_fails("画像がない")

    def test_photo_without_alt_rejected(self):
        src = self.add_photo()
        self.add_article(operator={"checked": "2026-11-22", "notes": ["メモ"],
                                   "photos": [{"src": src, "alt": "", "width": 800, "height": 600}]})
        self.build()
        self.assert_check_fails("alt がない")


if __name__ == "__main__":
    unittest.main(verbosity=2)
