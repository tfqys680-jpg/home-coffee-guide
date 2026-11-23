#!/usr/bin/env python3
"""品質ゲート（tools/quality/article_quality.py）のテスト。

良い見本は通し、「薄く似通う」見本は落とすことを確かめる。
実行: python3 tools/quality/tests/test_quality.py
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import article_quality as q  # noqa: E402
import fixtures as fx  # noqa: E402
import redteam  # noqa: E402

CATS = ["brew", "beans", "tools", "storage", "caffeine"]
A_KW = ("コーヒー 粉 量 目安", "コーヒー 何グラム 一杯;濃さ 調整")
B_KW = ("ドリップ 落ちるのが遅い", "ドリップ 詰まる;ペーパー 目詰まり")


def ev(article, kw=A_KW, existing=()):
    return q.evaluate(article, kw[0], kw[1], list(existing), CATS)


def joined(r):
    return "\n".join(r["errors"])


class GoodSamples(unittest.TestCase):
    def test_good_samples_pass_against_each_other(self):
        a, b = fx.good_amount(), fx.good_slow_drip()
        self.assertTrue(ev(a, A_KW, [b])["pass"], ev(a, A_KW, [b]))
        self.assertTrue(ev(b, B_KW, [a])["pass"], ev(b, B_KW, [a]))

    def test_different_topics_are_not_similar(self):
        r = ev(fx.good_amount(), A_KW, [fx.good_slow_drip()])
        self.assertLess(r["metrics"]["max_similarity"], q.SIMILARITY_WARN)


class ThinSample(unittest.TestCase):
    def setUp(self):
        self.r = ev(fx.thin_amount(), A_KW, [fx.good_slow_drip()])
        self.e = joined(self.r)

    def test_fails(self):
        self.assertFalse(self.r["pass"])

    def test_catches_each_problem(self):
        for needle in ("同じ文の繰り返し", "決まり文句「いかがでしたか」", "決まり文句が多い", "出典番号のない数値",
                       "早見表か比較表", "4手順以上", "主キーワードの語がタイトルにない", "補助キーワード「濃さ 調整」"):
            self.assertIn(needle, self.e)


class Similarity(unittest.TestCase):
    def test_near_duplicate_of_existing_fails(self):
        r = ev(fx.near_duplicate_of_amount(), ("コーヒー 粉 何グラム", ""), [fx.good_amount()])
        self.assertIn("似すぎている", joined(r))
        self.assertIn("H2見出しが", joined(r))


class RedTeam(unittest.TestCase):
    """別文脈のエージェントが作った「すり抜け」原稿が、どれも落ちること。"""

    def evaluate_set(self, items):
        out = {}
        for it in items:
            others = [o["article"] for o in items if o["slug"] != it["slug"]]
            out[it["slug"]] = q.evaluate(it["article"], it.get("main_kw", ""), it.get("sub_kw", ""), others, CATS)
        return out

    def test_goods_pass_together(self):
        res = self.evaluate_set(redteam.goods())
        self.assertTrue(all(r["pass"] for r in res.values()), res)

    def test_every_attack_is_caught(self):
        good_slugs = {g["slug"] for g in redteam.goods()}
        for name, make in redteam.ATTACKS.items():
            with self.subTest(attack=name):
                res = self.evaluate_set(redteam.goods() + make())
                attack = {k: v for k, v in res.items() if k not in good_slugs}
                self.assertTrue(any(not r["pass"] for r in attack.values()),
                                f"{name} がすり抜けた: { {k: v['metrics'] for k, v in attack.items()} }")

    def test_invisible_characters_are_rejected(self):
        a = fx.good_amount()
        a["lead"] = "\u200b".join(a["lead"])
        self.assertIn("見えない文字", joined(ev(a)))

    def test_full_width_and_extra_units_need_citations(self):
        for s in ("お湯は９０℃にします。", "１５０ｍｌを注ぎます。", "1.5Lのケトルを使います。", "粉を1.5倍にします。"):
            with self.subTest(sentence=s):
                a = fx.good_amount()
                a["lead"] += s
                self.assertIn("出典番号のない数値", joined(ev(a)))

    def test_citation_number_must_exist(self):
        a = fx.good_amount()
        a["lead"] += "目安があります[9]。"
        self.assertIn("存在しない出典番号", joined(ev(a)))


class FormatRules(unittest.TestCase):
    def test_comparison_needs_three_column_table(self):
        a = fx.good_amount()
        a["format"] = "比較"
        for _, b in q.blocks_of(a):
            if b.get("type") == "table":
                b["headers"] = b["headers"][:2]
                b["rows"] = [r[:2] for r in b["rows"]]
        self.assertIn("3列以上", joined(ev(a)))

    def test_troubleshooting_needs_cause_column(self):
        b = fx.good_slow_drip()
        for _, blk in q.blocks_of(b):
            if blk.get("type") == "table":
                blk["headers"] = ["症状", "理由", "直し方"]
        self.assertIn("「原因」の列", joined(ev(b, B_KW)))

    def test_unknown_format_and_category(self):
        a = fx.good_amount()
        a["format"], a["category"] = "まとめ", "misc"
        e = joined(ev(a))
        self.assertIn("形式（format）", e)
        self.assertIn("カテゴリ（category）", e)


class KeywordRules(unittest.TestCase):
    def test_keyword_only_in_second_half_of_title(self):
        a = fx.good_amount()
        a["title"] = "毎回の味をそろえるための計り方の基本と、コーヒー粉の量の目安"
        self.assertIn("後半", joined(ev(a)))

    def test_uncited_number_in_table_row(self):
        a = fx.good_amount()
        a["sections"][0]["blocks"][2]["rows"].append(["4杯", "600ml", "36g"])
        self.assertIn("出典番号のない数値", joined(ev(a)))


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="coffee-quality-test-"))
        self.site = self.tmp / "site"
        shutil.copytree(REPO, self.site, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        d = self.site / "content/articles"
        for p in d.glob("*.json"):
            p.unlink()
        # 見本原稿は短いので、文字数の下限だけテスト用に下げる
        cfg_path = self.site / "tools/auto-publish/config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["min_body_chars"] = 1000
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        self.write("coffee-to-water-ratio", fx.good_amount(), *A_KW)
        self.write("slow-drip-fix", fx.good_slow_drip(), *B_KW)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, slug, article, main_kw, sub_kw):
        item = fx.as_item(article, slug)
        item["main_kw"], item["sub_kw"] = main_kw, sub_kw
        (self.site / "content/articles" / f"{slug}.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")

    def run_all(self):
        return subprocess.run([sys.executable, str(self.site / "tools/quality/article_quality.py"), "--all"],
                              env=dict(os.environ, SITE_ROOT=str(self.site)), capture_output=True, text=True)

    def test_all_good_articles_pass(self):
        p = self.run_all()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("articles: 2", p.stdout)

    def test_a_near_duplicate_fails_the_whole_site(self):
        self.write("coffee-grams-per-cup", copy.deepcopy(fx.near_duplicate_of_amount()), "コーヒー 粉 何グラム", "")
        p = self.run_all()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("FAIL coffee-grams-per-cup", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
