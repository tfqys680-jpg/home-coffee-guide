#!/usr/bin/env python3
"""サイト生成と検証のテスト（Search Console 確認タグ、運営者プロフィール、運営者の確認メモ・写真）。

サイトを一時ディレクトリへ複製して build.py と check.py を実行する。リポジトリ本体は変更しない。
実行: python3 tools/site/tests/test_build.py
"""
import atexit
import hashlib
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
sys.path.insert(0, str(REPO / "tools/media"))
from media_spec import visual_hash  # noqa: E402

# 記事にはアイキャッチ・図解動画が必須（check.py が確かめる）。同じ visual なら一度作ったものを使い回す
MEDIA_CACHE = Path(tempfile.mkdtemp(prefix="coffee-media-cache-"))
atexit.register(shutil.rmtree, MEDIA_CACHE, True)


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
        for article in (self.site / "content/articles").glob("*.json"):
            article.unlink()
        for generated in ("column", "category"):
            shutil.rmtree(self.site / generated, ignore_errors=True)
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

    def add_article(self, operator=None, article=None, review_mode=None):
        item = {"slug": SLUG, "date": "2026-11-20", "updated": "2026-11-20", "ymyl": "低", "main_kw": "試験",
                "related": [], "article": article or sample_article()}
        if operator is not None:
            item["operator"] = operator
        if review_mode is not None:
            item["review_mode"] = review_mode
        d = self.site / "content/articles"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{SLUG}.json").write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
        self.make_media(item)

    def make_media(self, item):
        cached = MEDIA_CACHE / visual_hash(item)
        if not cached.exists():
            p = subprocess.run([sys.executable, str(self.site / "tools/media/make_media.py"), item["slug"]], env=self.env,
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            shutil.copytree(self.site / "images/articles" / item["slug"], cached)
        dest = self.site / "images/articles" / item["slug"]
        dest.mkdir(parents=True, exist_ok=True)
        for f in cached.iterdir():
            shutil.copy2(f, dest / f.name)

    def add_photo(self, name="drip.jpg"):
        d = self.site / "images/articles" / SLUG
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(b"\xff\xd8\xff\xd9")  # 中身は問わない（存在確認のみ）
        return f"images/articles/{SLUG}/{name}"

    def build(self):
        p = subprocess.run([sys.executable, str(self.site / "tools/site/build.py")], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_editorial_feature_remains_optional(self):
        self.build()
        self.assertNotIn("brew-studio-title", self.page("index.html"))
        self.add_article(review_mode="manual")
        d = self.site / "content/articles"
        source = d / f"{SLUG}.json"
        item = json.loads(source.read_text(encoding="utf-8"))
        feature_slug = "hand-drip-taste-adjustment"
        item["slug"] = feature_slug
        (d / f"{feature_slug}.json").write_text(json.dumps(item), encoding="utf-8")
        self.build()
        self.assertIn(f"column/{feature_slug}/#brew-studio-title", self.page("index.html"))
        featured = self.page(f"column/{feature_slug}/index.html")
        self.assertIn('src="../../images/editorial/brew-pour-demo.mp4"', featured)
        self.assertIn('<video controls playsinline preload="none"', featured)
        self.assertNotRegex(featured, r"<video[^>]*\sautoplay")
        self.assertIn("動画を文章で読む", featured)
        plain_page = self.page(f"column/{SLUG}/index.html")
        self.assertNotIn("brew-pour-demo.mp4", plain_page)
        # どの記事にも図解動画が付く。HTMLの autoplay 属性は使わず、読み込みは画面に入るまで待つ（preload="none"）
        self.assertIn(f'src="../../images/articles/{SLUG}/explainer.mp4"', plain_page)
        self.assertIn('<video controls muted playsinline preload="none"', plain_page)
        self.assertNotRegex(plain_page, r"<video[^>]*\sautoplay")

    def test_shop_links_become_affiliate_links_with_disclosure(self):
        self.add_article()
        self.set_site(affiliate={"amazon_tag": "", "rakuten_affiliate_id": ""})  # IDが空のときは通常の検索リンク
        self.build()
        page = self.page(f"column/{SLUG}/index.html")
        self.assertIn('https://www.amazon.co.jp/s?k=', page)
        self.assertNotIn("tag=", page)
        self.assertNotIn('class="pr-note"', page)
        self.assertNotIn("sponsored", page)
        self.assert_check_ok()
        self.set_site(affiliate={"amazon_tag": "coffeetest-22", "rakuten_affiliate_id": "1a2b3c4d.5e6f7a8b.1a2b3c4d.5e6f7a8c"})
        self.build()
        page = self.page(f"column/{SLUG}/index.html")
        self.assertIn("&amp;tag=coffeetest-22", page)
        self.assertIn("https://hb.afl.rakuten.co.jp/hgc/1a2b3c4d.5e6f7a8b.1a2b3c4d.5e6f7a8c/?pc=", page)
        self.assertIn('rel="sponsored noopener"', page)
        self.assertIn('class="pr-note"', page)
        self.assertIn('<span class="shop-pr">PR</span>', page)
        self.assertIn("Amazonのアソシエイトとして", self.page("disclaimer.html"))
        self.assertIn("Amazonのアソシエイトとして", self.page("index.html"))  # フッターにも出す
        self.assert_check_ok()

    def test_product_examples_render_with_source_and_shop_links(self):
        art = sample_article()
        art["products"] = [{"name": "テストミル", "maker": "テスト社", "model": "TM-1", "facts": ["臼式の手挽きミル"],
                            "fit": "器具ごとに挽き目を切り替えたい人向けの手挽きの例です。", "query": "テスト社 テストミル TM-1",
                            "checked": "2026-11-28", "source": {"title": "テスト社：テストミル", "url": "https://www.example.co.jp/mill"}}]
        self.add_article(article=art)
        self.set_site(affiliate={"amazon_tag": "coffeetest-22", "rakuten_affiliate_id": ""})
        self.build()
        page = self.page(f"column/{SLUG}/index.html")
        self.assertIn("条件に合う商品の例", page)
        self.assertIn('<p class="prod-name">テストミル<span class="prod-model">TM-1</span></p>', page)
        self.assertIn('href="https://www.example.co.jp/mill" rel="noopener">テスト社：テストミル</a>（2026年11月28日確認）', page)
        self.assertIn('data-item="テスト社 テストミル" data-placement="product"', page)
        self.assertIn("tag=coffeetest-22", page)
        self.assertIn('<span class="shop-mini-label">テスト社 テストミル</span>', page)
        self.assert_check_ok()

    def test_media_and_shop_are_required_on_article_pages(self):
        self.add_article()
        self.build()
        self.assert_check_ok()
        shutil.rmtree(self.site / "images/articles" / SLUG)
        self.build()
        p = subprocess.run([sys.executable, str(self.site / "tools/site/check.py")], env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("画像・動画がない", p.stdout)

    def test_in_view_playback_respects_reduced_motion_and_data_saver(self):
        js = (self.site / "js/main.js").read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion: reduce", js)
        self.assertIn("saveData", js)
        self.assertIn("v.muted = true", js)
        self.assertIn("affiliate_click", js)

    def test_blueprint_actions_target_matching_sections_without_displacing_legacy_links(self):
        self.build()
        self.assertIn('href="./#articles"', self.page("index.html"))
        self.assertNotIn('id="blueprint-workbench"', self.page("index.html"))
        self.assertNotIn("blueprint-motion", self.page("index.html"))
        self.assertNotIn('id="extraction"', self.page("index.html"))
        feature = json.loads((REPO / "content/articles/hand-drip-taste-adjustment.json").read_text(encoding="utf-8"))
        slug = feature["slug"]
        (self.site / "content/articles" / f"{slug}.json").write_text(
            json.dumps(feature, ensure_ascii=False), encoding="utf-8")
        self.build()
        index = self.page("index.html")
        page = self.page(f"column/{slug}/index.html")
        for i, anchor in enumerate(("brew-pour", "brew-grind", "brew-filter"), 1):
            self.assertIn(f'href="column/{slug}/#{anchor}"', index)
            self.assertIn(f'<section id="{anchor}" aria-labelledby="sec{i}"><h2 id="sec{i}">', page)
        self.assertIn(f'href="column/{slug}/#brew-studio-title"', index)
        self.assertIn('id="brew-studio-title"', page)
        self.assertIn('紙フィルターがいらない、多孔質セラミック', page)
        self.assertNotRegex(page, r"<video[^>]*\sautoplay")

    def test_entry_asset_fingerprints_follow_bytes_not_paths(self):
        self.add_article()
        fixture = REPO / "content/articles/hand-drip-taste-adjustment.json"
        (self.site / "content/articles" / fixture.name).write_bytes(fixture.read_bytes())
        css = "css/style.css"
        motion = "js/blueprint-motion.js"

        def fingerprint(path):
            return hashlib.sha256((self.site / path).read_bytes()).hexdigest()[:16]

        self.build()
        previous_css, previous_motion = fingerprint(css), fingerprint(motion)
        self.assertIn(f'href="{css}?v={previous_css}"', self.page("index.html"))
        self.assertIn(f'src="{motion}?v={previous_motion}"', self.page("index.html"))
        self.assertIn(f'href="../../{css}?v={previous_css}"', self.page(f"column/{SLUG}/index.html"))
        self.assertRegex(self.page("404.html"), rf'href="/[^"]*{re.escape(css)}\?v={previous_css}"')

        for path, old in ((css, previous_css), (motion, previous_motion)):
            with (self.site / path).open("ab") as f:
                f.write(b"\n/* test independently revised asset */\n")
            self.assertNotEqual(old, fingerprint(path))
        self.build()
        updated = self.page("index.html")
        self.assertIn(f'href="{css}?v={fingerprint(css)}"', updated)
        self.assertIn(f'src="{motion}?v={fingerprint(motion)}"', updated)
        self.assertNotIn(f'?v={previous_css}', updated)
        self.assertNotIn(f'?v={previous_motion}', updated)
        self.build()
        self.assertEqual(updated, self.page("index.html"))

    def test_motion_is_optional_same_origin_and_home_only(self):
        fixture = REPO / "content/articles/hand-drip-taste-adjustment.json"
        (self.site / "content/articles" / fixture.name).write_bytes(fixture.read_bytes())
        self.build()
        home = self.page("index.html")
        self.assertIn('class="home-editorial"', home)
        cover = home.split('<section class="ed-hero"', 1)[1].split("</section>", 1)[0]
        self.assertIn('<svg class="ed-drawing"', cover)
        self.assertIn('<span>家で淹れる</span><span>コーヒー</span>', cover)
        self.assertNotIn("blueprint-render", cover)
        self.assertNotIn("<img", cover)
        self.assertNotIn("<a ", cover)
        self.assertNotIn('src="images/editorial/brew-adjustments.webp"', home)
        self.assertIn('src="../../images/editorial/brew-adjustments.webp"', self.page(f"column/{fixture.stem}/index.html"))
        css = self.page("css/style.css")
        self.assertEqual(re.findall(r"--milk:\s*([^;]+);", css), ["#fff"])
        self.assertLess(home.index('id="blueprint-workbench"'), home.index('id="extraction"'))
        self.assertIn('id="extraction-title">抽出を図で見る', home)
        self.assertRegex(home, r'type="module" src="js/blueprint-motion\.js\?v=[a-f0-9]{16}"')
        self.assertIn('src="images/editorial/drip-blueprint.svg"', home)
        self.assertNotIn("blueprint-motion", self.page(f"column/{fixture.stem}/index.html"))
        self.assertNotIn("blueprint-motion", self.page("about.html"))
        js = self.page("js/blueprint-motion.js")
        self.assertIn('canvas.getContext("webgl2"', js)
        self.assertLess(js.index('if (!context) return'), js.index('import(vendor('))
        self.assertIn('prefers-reduced-motion: reduce', js)
        self.assertIn('observer.observe(panel)', js)
        self.assertIn('scrollScene?.destroy(true)', js)
        self.assertIn('new ScrollMagic.Scene', js)
        self.assertIn('TweenMax.to', js)
        self.assertIn('tween.progress(event.progress)', js)
        self.assertIn('new THREE.WebGLRenderer', js)
        vendor = self.site / "js/vendor"
        files = {
            "ScrollMagic.min.js": "22eb8669c71f095da883c5e69d2d3448e8a42a4d5e98dd049bef63ae0defeb12",
            "gsap.min.js": "3d1bea374ab1b703cc5c4105358eec63c4465efdc573931dc116e34a0a190c1b",
            "three.core.js": "60880f0fd017e6ad08a80c2f0f7015c336ba0a5b6dbdde733b9272ca89eb95e2",
            "three.module.min.js": "49bfc58c4097915b4fcf08ed1ee245c0da687f02d35908f38266dbd3d5324ac2",
        }
        for name, digest in files.items():
            self.assertEqual(hashlib.sha256((vendor / name).read_bytes()).hexdigest(), digest)
        self.assertIn('from"./three.core.js"', self.page("js/vendor/three.module.min.js"))

    def test_french_press_reachable_with_diagram_and_sources(self):
        for slug in ("french-press-how-to", "hand-drip-taste-adjustment"):
            fixture = REPO / "content" / "articles" / f"{slug}.json"
            (self.site / "content" / "articles" / fixture.name).write_bytes(fixture.read_bytes())
        self.build()
        slug = "french-press-how-to"
        new = self.page(f"column/{slug}/index.html")
        self.assertIn(f'href="column/{slug}/"', self.page("index.html"))
        self.assertIn(f'href="../../column/{slug}/"', self.page("category/brew/index.html"))
        self.assertIn(f"/column/{slug}/</loc>", self.page("sitemap.xml"))
        self.assertIn(f'href="../{slug}/"', self.page("column/hand-drip-taste-adjustment/index.html"))
        self.assertIn('href="../hand-drip-taste-adjustment/"', new)
        self.assertRegex(new, r'french-press-steps\.svg\?v=[a-f0-9]{16}" alt="[^"]+"')
        self.assertIn(".press-steps img { aspect-ratio: 720 / 230;", self.page("css/style.css"))
        self.assertIn("粉を湯に浸す → 網を上げて待つ → 最後にゆっくり押す。", new)
        self.assertIn("ゆっくり押し下げます", new)
        self.assertIn("https://www.ucc.co.jp/enjoy/brew/howto-drip_04.html", new)
        self.assertIn("https://espro.com/pages/product-care", new)

    def test_about_hides_contact_and_preserves_disclosure(self):
        self.set_site(contact="unpublished-contact-for-test")
        self.build()
        about = self.page("about.html")
        for phrase in ("unpublished-contact-for-test", "誤りに気づいた場合は", "連絡先"):
            self.assertNotIn(phrase, about)
        self.assertIn("生成AI（ChatGPT）", about)
        self.assertIn("プライバシーポリシー", about)

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

    def test_published_files_include_every_linked_page(self):
        self.add_article()
        self.build()
        pub = self.tmp / "pub"
        subprocess.run(["bash", str(self.site / "tools/site/collect_public.sh"), str(pub)], check=True, env=self.env)
        ok = subprocess.run([sys.executable, str(self.site / "tools/site/check_public.py"), str(pub)], env=self.env,
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertTrue((pub / "category/brew/index.html").exists())
        shutil.rmtree(pub / "category")  # 以前の deploy.yml のように category/ を集め忘れた場合
        ng = subprocess.run([sys.executable, str(self.site / "tools/site/check_public.py"), str(pub)], env=self.env,
                            capture_output=True, text=True)
        self.assertEqual(ng.returncode, 1, ng.stdout)
        self.assertIn("公開物にない", ng.stdout)

    def test_full_width_breadcrumb_passes_check(self):
        art = sample_article()
        art["breadcrumb"] = "粉の量（1杯分）"
        self.add_article(article=art)
        self.build()
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
        self.make_media(other)
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
        # 運営者の写真がない記事は、記事ごとに作ったOGP画像とアイキャッチを使う
        media = f"https://tfqys680-jpg.github.io/home-coffee-guide/images/articles/{SLUG}/"
        self.assertEqual(self.article_ld()["image"], [media + "og.jpg", media + "eyecatch.webp"])
        self.assertIn(f'<meta property="og:image" content="{media}og.jpg">', page)
        self.assert_check_ok()

    def test_manual_review_does_not_claim_automated_claude_review(self):
        self.add_article(review_mode="manual")
        self.build()
        page = self.page(f"column/{SLUG}/index.html")
        self.assertIn("出典ページの本文を確認して編集しました", page)
        self.assertIn("人による実際の試飲や器具のテストは行っていません", page)
        self.assertIn("（出典ページの本文を確認）", page)
        self.assertNotIn("Claude", page)
        self.assertNotIn("出典ページを自動で取得", page)
        self.add_article()
        self.build()
        auto = self.page(f"column/{SLUG}/index.html")
        self.assertIn("Claude", auto)
        self.assertIn("出典ページを自動で取得", auto)

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
        self.assertEqual(ld["image"][0], "https://tfqys680-jpg.github.io/home-coffee-guide/" + src)
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
