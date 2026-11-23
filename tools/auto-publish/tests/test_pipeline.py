#!/usr/bin/env python3
"""自動記事パイプラインの通しテスト（APIと出典取得はモック）。

サイトを一時ディレクトリへ複製し、テスト専用のキューで pipeline.py を実行してから
tools/site/check.py と品質ゲートが通ることを確認する。本番のキューや公開済み記事には依存しない。
実行: python3 tools/auto-publish/tests/test_pipeline.py
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools/quality/tests"))
import fixtures as fx  # noqa: E402

SRC_URLS = [s["url"] for s in fx.SRC]
SLUGS = ["zz-test-sample-one", "zz-test-sample-two"]
QUEUE = [  # slug, 主キーワード, 補助キーワード（見本原稿に合わせる）
    (SLUGS[0], "コーヒー 粉 量 目安", "コーヒー 何グラム 一杯;濃さ 調整"),
    (SLUGS[1], "ドリップ 落ちるのが遅い", "ドリップ 詰まる;ペーパー 目詰まり"),
]
COVERAGE = [{"point": p, "covered": True, "note": "本文で扱った"} for p in ("基準の量", "計り方", "調整", "杯数", "道具")]


def sample_article(n, related=()):
    """n=1: 粉の量（形式=手順）、n=2: 落ちるのが遅い（形式=トラブル解決）。どちらも品質ゲートに合格する見本。"""
    art = fx.good_amount() if n == 1 else fx.good_slow_drip()
    art["related"] = list(related)
    return art


def review(article, verdict="PASS", ymyl="低", coverage=True):
    r = {"verdict": verdict, "ymyl": ymyl, "issues": ["テスト指摘"], "article": article}
    if coverage:
        r["coverage"] = copy.deepcopy(COVERAGE)
        r["unique_value"] = "出典の数値をまとめた早見表"
    return r


def broken(article):
    """品質ゲートに落ちる版（単位つきの数値に出典番号がない）。"""
    a = copy.deepcopy(article)
    a["lead"] += "粉は12g、お湯は180mlにします。"
    return a


def write_fixtures(d, writer, reviews):
    d.mkdir(parents=True, exist_ok=True)
    (d / "openai_1.json").write_text(json.dumps(writer, ensure_ascii=False), encoding="utf-8")
    for i, r in enumerate(reviews, 1):
        (d / f"claude_{i}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    (d / "sources.json").write_text(json.dumps({u: "出典本文" * 100 for u in SRC_URLS}, ensure_ascii=False), encoding="utf-8")


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="coffee-auto-test-"))
        self.site = self.tmp / "site"
        shutil.copytree(REPO, self.site, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        for p in (self.site / "content/articles").glob("*.json"):
            p.unlink()
        (self.site / "docs/auto-queue.csv").write_text(
            "slug,テーマ,主キーワード,補助キーワード,想定読者,YMYL区分,状態,備考\n"
            + "".join(f"{s},試験テーマ{i},{kw},{sub},試験読者,低,待機,試験\n" for i, (s, kw, sub) in enumerate(QUEUE, 1)),
            encoding="utf-8")
        # 見本原稿は短いので、文字数の下限だけテスト用に下げる（品質ゲートの他の基準はそのまま）
        cfg_path = self.site / "tools/auto-publish/config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["min_body_chars"] = 1000
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_pipeline(self, n, writer, reviews):
        fx_dir = self.tmp / f"fx{n}"
        write_fixtures(fx_dir, writer, reviews)
        env = dict(os.environ, SITE_ROOT=str(self.site), AUTO_PUBLISH_MOCK=str(fx_dir), AUTO_PUBLISH_DATE=f"2026-11-1{n}",
                   PYTHONDONTWRITEBYTECODE="1")
        res = self.tmp / f"result{n}.json"
        subprocess.run([sys.executable, str(self.site / "tools/auto-publish/pipeline.py"), "--result", str(res)],
                       env=env, check=True, capture_output=True)
        return json.loads(res.read_text(encoding="utf-8"))

    def publish(self, n, related=(), **kw):
        art = sample_article(n, related)
        return self.run_pipeline(n, art, [review(art, **kw)])

    def check_site(self):
        env = dict(os.environ, SITE_ROOT=str(self.site))
        for script in ("tools/site/check.py", "tools/quality/article_quality.py"):
            p = subprocess.run([sys.executable, str(self.site / script)] + (["--all"] if "quality" in script else []),
                               capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 0, script + "\n" + p.stdout + p.stderr)

    def queue(self):
        return (self.site / "docs/auto-queue.csv").read_text(encoding="utf-8")

    def runlog(self):
        return (self.site / "docs/run-log.md").read_text(encoding="utf-8")

    def test_two_articles_published_and_linked(self):
        r1 = self.publish(1)
        self.assertEqual(r1["status"], "created", r1)
        self.assertTrue(r1["auto_merge"])
        r2 = self.publish(2, related=[SLUGS[0]])
        self.assertEqual(r2["status"], "created", r2)
        page1 = (self.site / f"column/{SLUGS[0]}/index.html").read_text(encoding="utf-8")
        self.assertIn("生成AI（ChatGPT）で下書き", page1)
        self.assertIn('href="#source1"', page1)
        self.assertIn(f'href="../{SLUGS[1]}/"', page1, "関連記事が双方向にリンクされていない")
        self.assertIn('href="../../category/brew/"', page1, "パンくずにカテゴリがない")
        index = (self.site / "index.html").read_text(encoding="utf-8")
        self.assertLess(index.index(SLUGS[1]), index.index(SLUGS[0]), "新しい記事が先頭に来ていない")
        self.assertIn('href="category/brew/"', index)
        self.assertIn("公開(2026-11-12)", self.queue())
        saved = json.loads((self.site / f"content/articles/{SLUGS[0]}.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["sub_kw"], QUEUE[0][2])
        self.assertTrue(saved["pipeline"]["coverage"])
        self.assertIn("品質ゲート: 合格", self.runlog())
        self.check_site()

    def test_high_ymyl_waits_for_review(self):
        r = self.publish(1, ymyl="高")
        self.assertEqual(r["status"], "created")
        self.assertFalse(r["auto_merge"])
        self.check_site()

    def test_block_creates_no_page(self):
        r = self.publish(1, verdict="BLOCK")
        self.assertEqual(r["status"], "blocked")
        self.assertFalse((self.site / "column" / SLUGS[0]).exists())
        self.assertIn("保留(2026-11-11)", self.queue())
        self.check_site()

    def test_unknown_related_is_rejected(self):
        r = self.publish(1, related=["no-such-article"])
        self.assertEqual(r["status"], "blocked")
        self.assertIn("存在しない関連記事", r["reason"])

    def test_unknown_link_in_body_is_rejected(self):
        art = sample_article(1)
        art["lead"] += "詳しくは[[no-such-article|別の記事]]で説明します。"
        r = self.run_pipeline(1, art, [review(art)])
        self.assertEqual(r["status"], "blocked")
        self.assertIn("本文のリンク先の記事がない", r["reason"])

    # ---- キューの自動補充（D3）と本番の文字数（E6）
    def test_empty_queue_is_refilled_and_published_at_production_length(self):
        cfg_path = self.site / "tools/auto-publish/config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["min_body_chars"] = json.loads((REPO / "tools/auto-publish/config.json").read_text(encoding="utf-8"))["min_body_chars"]
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.site / "docs/auto-queue.csv").write_text(
            "slug,テーマ,主キーワード,補助キーワード,想定読者,YMYL区分,状態,備考\n"
            "old-topic,公開済みのテーマ,古い キーワード,古い,読者,低,公開(2026-11-01),\n", encoding="utf-8")
        topic = {"slug": "coffee-mill-types", "テーマ": "コーヒーミルの種類と選び方", "主キーワード": "コーヒーミル 種類 違い",
                 "補助キーワード": "手挽き 電動 比較;臼式 プロペラ式", "想定読者": "ミルを買う人", "YMYL区分": "低", "備考": "方式の違い"}
        art = fx.good_long_mill()
        d = self.tmp / "fx-refill"
        d.mkdir()
        files = {"openai_1.json": {"topics": [topic]}, "claude_1.json": {"topics": [topic], "rejected": []},
                 "openai_2.json": art, "claude_2.json": review(art)}
        for name, body in files.items():
            (d / name).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        (d / "sources.json").write_text(json.dumps({u: "出典本文" * 100 for u in SRC_URLS}, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, SITE_ROOT=str(self.site), AUTO_PUBLISH_MOCK=str(d), AUTO_PUBLISH_DATE="2026-11-24",
                   PYTHONDONTWRITEBYTECODE="1")
        res = self.tmp / "result-refill.json"
        subprocess.run([sys.executable, str(self.site / "tools/auto-publish/pipeline.py"), "--result", str(res)],
                       env=env, check=True, capture_output=True)
        r = json.loads(res.read_text(encoding="utf-8"))
        self.assertEqual(r["status"], "created", r)
        self.assertEqual(r["slug"], "coffee-mill-types")
        self.assertIn("coffee-mill-types,コーヒーミルの種類と選び方", self.queue())
        self.assertIn("公開(2026-11-24)", self.queue())
        self.assertTrue((self.site / "category/tools/index.html").exists())
        self.check_site()

    # ---- 品質ゲート（D2: 落ちたら指摘を渡して1回推敲し直す）
    def test_quality_failure_is_fixed_in_one_more_round(self):
        good = sample_article(1)
        bad = broken(good)
        r = self.run_pipeline(1, bad, [review(bad), review(good)])
        self.assertEqual(r["status"], "created", r)
        self.check_site()

    def test_quality_failure_after_fix_round_is_held(self):
        bad = broken(sample_article(1))
        r = self.run_pipeline(1, bad, [review(bad), review(bad)])
        self.assertEqual(r["status"], "blocked")
        self.assertIn("品質ゲート: 出典番号のない数値", r["reason"])
        self.assertFalse((self.site / "column" / SLUGS[0]).exists())
        self.assertIn("保留(2026-11-11)", self.queue())

    def test_thin_article_is_held(self):
        thin = fx.thin_amount()
        r = self.run_pipeline(1, thin, [review(thin), review(thin)])
        self.assertEqual(r["status"], "blocked")
        self.assertIn("同じ文の繰り返し", r["reason"])

    def test_missing_competitor_check_is_held(self):
        art = sample_article(1)
        r = self.run_pipeline(1, art, [review(art, coverage=False), review(art, coverage=False)])
        self.assertEqual(r["status"], "blocked")
        self.assertIn("競合との比較", r["reason"])

    def test_near_duplicate_of_existing_article_is_held(self):
        self.assertEqual(self.publish(1)["status"], "created")
        dup = fx.near_duplicate_of_amount()
        r = self.run_pipeline(2, dup, [review(dup), review(dup)])
        self.assertEqual(r["status"], "blocked")
        self.assertIn("似すぎている", r["reason"])


class SourceFetchTest(unittest.TestCase):
    """出典の取得確認（転送先が別ページか、本文の抜き出し）。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO / "tools/auto-publish"))
        import sources
        cls.sources = sources

    def test_redirect_to_other_page_is_not_same_page(self):
        # 2026-11-23 の実例: NCA の旧URLは数値のない一覧ページへ転送されていた
        self.assertFalse(self.sources.same_page("https://www.ncausa.org/About-Coffee/How-to-Brew-Coffee",
                                                "https://www.aboutcoffee.org/brewing/"))
        self.assertFalse(self.sources.same_page("https://example.org/a", "https://example.org/b"))

    def test_scheme_www_and_trailing_slash_are_same_page(self):
        self.assertTrue(self.sources.same_page("http://example.org/a", "https://www.example.org/a/"))
        self.assertTrue(self.sources.same_page("https://www.example.org/a/", "https://example.org/a"))

    def test_extract_prefers_main_over_navigation(self):
        raw = ("<html><body><nav>" + "メニュー項目 " * 50 + "</nav><main><h1>淹れ方</h1><p>湯温は93℃</p></main>"
               "<footer>フッター</footer></body></html>")
        text = self.sources.extract_text(raw)
        self.assertIn("湯温は93℃", text)
        self.assertNotIn("メニュー項目", text)
        self.assertNotIn("フッター", text)

    def test_extract_falls_back_to_whole_page(self):
        text = self.sources.extract_text("<html><body><div>本文 15g</div><script>x=1</script></body></html>")
        self.assertEqual(text, "本文 15g")


class ShipNotificationTest(unittest.TestCase):
    """ship.sh が止まるときに Issue で知らせること（gh は記録するだけの偽物に差し替える）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="coffee-ship-test-"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "gh.log"
        (self.bin / "gh").write_text(f'#!/usr/bin/env bash\necho "$*" >> "{self.log}"\n', encoding="utf-8")
        (self.bin / "gh").chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ship(self, result_path):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", GITHUB_OUTPUT=str(self.tmp / "out"))
        return subprocess.run(["bash", str(REPO / "tools/auto-publish/ship.sh"), str(result_path)], cwd=self.tmp,
                              env=env, capture_output=True, text=True)

    def calls(self):
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def test_missing_result_file_is_notified(self):
        p = self.ship(self.tmp / "no-such-result.json")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("issue create", self.calls())
        self.assertIn("途中で止まりました", self.calls())

    def test_empty_queue_is_notified(self):
        res = self.tmp / "result.json"
        res.write_text(json.dumps({"status": "skipped", "reason": "キューが空"}, ensure_ascii=False), encoding="utf-8")
        p = self.ship(res)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("テーマがありません", self.calls())


if __name__ == "__main__":
    unittest.main(verbosity=2)
