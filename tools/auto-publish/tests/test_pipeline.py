#!/usr/bin/env python3
"""自動記事パイプラインの通しテスト（APIと出典取得はモック）。

サイトを一時ディレクトリへ複製し、テスト専用のキューで pipeline.py を実行してから
tools/site/check.py が通ることを確認する。本番のキューや公開済み記事には依存しない。
実行: python3 tools/auto-publish/tests/test_pipeline.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC1 = "https://www.example.go.jp/coffee"
SRC2 = "https://www.example.or.jp/brew"
SLUGS = ["zz-test-sample-one", "zz-test-sample-two"]


def sample_article(n, related=()):
    para = ("コーヒーをおいしく淹れるには、粉の量とお湯の量の比率をそろえることが大切です。"
            "毎回同じ道具と同じ手順で淹れると、味の違いに気づきやすくなります。")
    sections = [{"heading": f"試験見出し{n}-{i}",
                 "blocks": [{"type": "p", "text": para * 5 + "[1]"},
                            {"type": "h3", "text": f"小見出し{i}"},
                            {"type": "ol", "items": ["粉を量る", "お湯を注ぐ [2]"]},
                            {"type": "example", "label": "例", "lines": ["粉と湯の量を記録する"]},
                            {"type": "table", "headers": ["項目", "目安"], "rows": [["粉", "好みで調整"], ["湯", "好みで調整"]]}]}
                for i in range(1, 7)]
    return {
        "title": f"自動公開パイプライン試験用サンプル記事その{n}の手順",
        "breadcrumb": f"試験用サンプル{n}",
        "description": "自動公開パイプラインの試験に使うサンプル記事です。粉とお湯の量、淹れる手順、よくある失敗の直し方をチェックリストで確認できます。",
        "conclusion": "粉とお湯の量をそろえ、手順を毎回同じにすると味が安定します。",
        "can_do": ["量の決め方がわかる", "手順がわかる", "失敗の直し方がわかる"],
        "lead": para,
        "sections": sections,
        "checklist": ["粉を量った", "お湯を量った", "手順をそろえた", "味を記録した", "次回の調整を決めた"],
        "faq": [{"q": "毎回味が違うのはなぜ？", "a": "量や手順が変わっている可能性があります。[1]"},
                {"q": "お湯の温度は？", "a": "好みで調整します。"},
                {"q": "道具は何が必要？", "a": "まずは手持ちの道具で始められます。"}],
        "next_step": "まずは次の一杯で、粉とお湯の量を量って記録してみましょう。",
        "sources": [{"title": "テスト省「コーヒー」", "url": SRC1, "note": "テスト"},
                    {"title": "テスト協会「淹れ方」", "url": SRC2, "note": "テスト"}],
        "related": list(related),
    }


def write_fixtures(d, n, verdict, ymyl, related=()):
    d.mkdir(parents=True, exist_ok=True)
    art = sample_article(n, related)
    (d / "openai_1.json").write_text(json.dumps(art, ensure_ascii=False), encoding="utf-8")
    (d / "claude_1.json").write_text(json.dumps({"verdict": verdict, "ymyl": ymyl, "issues": ["テスト指摘"], "article": art},
                                                ensure_ascii=False), encoding="utf-8")
    (d / "sources.json").write_text(json.dumps({SRC1: "出典本文" * 100, SRC2: "出典本文" * 100}, ensure_ascii=False), encoding="utf-8")


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="coffee-auto-test-"))
        self.site = self.tmp / "site"
        shutil.copytree(REPO, self.site, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        (self.site / "docs/auto-queue.csv").write_text(
            "slug,テーマ,主キーワード,補助キーワード,想定読者,YMYL区分,状態,備考\n"
            + "".join(f"{s},試験テーマ{i},試験キーワード{i},試験,試験読者,低,待機,試験\n" for i, s in enumerate(SLUGS, 1)),
            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_pipeline(self, n, verdict="PASS", ymyl="低", related=()):
        fx = self.tmp / f"fx{n}"
        write_fixtures(fx, n, verdict, ymyl, related)
        env = dict(os.environ, SITE_ROOT=str(self.site), AUTO_PUBLISH_MOCK=str(fx), AUTO_PUBLISH_DATE=f"2026-11-1{n}",
                   PYTHONDONTWRITEBYTECODE="1")
        res = self.tmp / f"result{n}.json"
        subprocess.run([sys.executable, str(self.site / "tools/auto-publish/pipeline.py"), "--result", str(res)],
                       env=env, check=True, capture_output=True)
        return json.loads(res.read_text(encoding="utf-8"))

    def check_site(self):
        p = subprocess.run([sys.executable, str(self.site / "tools/site/check.py")], capture_output=True, text=True,
                           env=dict(os.environ, SITE_ROOT=str(self.site)))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def queue(self):
        return (self.site / "docs/auto-queue.csv").read_text(encoding="utf-8")

    def test_two_articles_published_and_linked(self):
        r1 = self.run_pipeline(1)
        self.assertEqual(r1["status"], "created", r1)
        self.assertTrue(r1["auto_merge"])
        r2 = self.run_pipeline(2, related=[SLUGS[0]])
        self.assertEqual(r2["status"], "created", r2)
        page1 = (self.site / f"column/{SLUGS[0]}/index.html").read_text(encoding="utf-8")
        self.assertIn("生成AI（ChatGPT）で下書き", page1)
        self.assertIn('href="#source1"', page1)
        self.assertIn(f'href="../{SLUGS[1]}/"', page1, "関連記事が双方向にリンクされていない")
        index = (self.site / "index.html").read_text(encoding="utf-8")
        self.assertLess(index.index(SLUGS[1]), index.index(SLUGS[0]), "新しい記事が先頭に来ていない")
        self.assertIn("公開(2026-11-12)", self.queue())
        self.check_site()

    def test_high_ymyl_waits_for_review(self):
        r = self.run_pipeline(1, ymyl="高")
        self.assertEqual(r["status"], "created")
        self.assertFalse(r["auto_merge"])
        self.check_site()

    def test_block_creates_no_page(self):
        r = self.run_pipeline(1, verdict="BLOCK")
        self.assertEqual(r["status"], "blocked")
        self.assertFalse((self.site / "column" / SLUGS[0]).exists())
        self.assertIn("保留(2026-11-11)", self.queue())
        self.check_site()

    def test_unknown_related_is_rejected(self):
        r = self.run_pipeline(1, related=["no-such-article"])
        self.assertEqual(r["status"], "blocked")
        self.assertIn("存在しない関連記事", r["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
