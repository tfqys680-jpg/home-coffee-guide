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


class ProductionLength(unittest.TestCase):
    """本番と同じ文字数の下限で、実際の長さの良い記事を誤って落とさないこと（E6）。"""

    def test_long_good_article_passes_with_production_limits(self):
        r = q.evaluate(fx.good_long_mill(), "コーヒーミル 種類 違い", "手挽き 電動 比較;臼式 プロペラ式",
                       [fx.good_amount(), fx.good_slow_drip()], CATS, q.published_limits())
        self.assertTrue(r["pass"], r)
        self.assertEqual(r["warnings"], [])

    def test_short_article_fails_production_length(self):
        r = q.evaluate(fx.good_amount(), *A_KW, [], CATS, q.published_limits())
        self.assertIn("本文が短すぎる", joined(r))


class EvaluatorFindings(unittest.TestCase):
    """第三者評価（2026-11-23）で見つかった抜け道。"""

    def test_description_needs_main_keyword(self):
        a = fx.good_amount()
        a["description"] = "コーヒー粉を1杯分ずつ計る手順と、濃い・薄いと感じたときにどこを一つずつ変えればよいかを整理します。"
        self.assertIn("説明文（description）にない", joined(ev(a)))

    def test_numbers_in_checklist_need_citations(self):
        a = fx.good_amount()
        a["checklist"].append("お湯を92℃にした")
        self.assertIn("出典番号のない数値", joined(ev(a)))

    def test_numbers_in_headings_must_be_cited_in_body(self):
        a = fx.good_amount()
        a["sections"][1]["heading"] = "3分で終わる計り方"
        self.assertIn("本文で出典を付けていない数値", joined(ev(a)))
        a["sections"][1]["heading"] = "湯150mlの計り方"  # 本文で [1] つきで書いている数値は見出しに使える
        self.assertNotIn("本文で出典を付けていない数値", joined(ev(a)))

    def test_ratio_and_counts_need_citations(self):
        for sentence in ("粉と湯は1:15にします。", "湯は3回に分けて注ぎます。"):
            with self.subTest(sentence=sentence):
                a = fx.good_amount()
                a["lead"] += sentence
                self.assertIn("出典番号のない数値", joined(ev(a)))

    def test_near_identical_headings_are_counted(self):
        a = fx.good_slow_drip()
        base = fx.good_amount()
        for i in range(3):
            a["sections"][i]["heading"] = base["sections"][i]["heading"] + "ポイント"
        self.assertIn("H2見出しが3つ同じかほぼ同じ", joined(ev(a, B_KW, [base])))

    def test_basics_format_needs_a_definition(self):
        a = fx.good_amount()
        a["format"] = "基礎知識"
        self.assertIn("1文での定義", joined(ev(a)))
        a["conclusion"] = "コーヒー粉の量の目安とは、湯量に対して粉を何グラム使うかの基準のことです[1]。" + a["conclusion"]
        self.assertNotIn("1文での定義", joined(ev(a)))


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


class VisualAndShoppingRules(unittest.TestCase):
    """アイキャッチ・図解・動画の元（visual）と商品の検索リンク（shopping）は必須。出典のない図解や商品の推奨は落とす。"""

    def errors(self, a):
        return q.evaluate(a, fx.task()["主キーワード"], fx.task()["補助キーワード"], [], CATS)["errors"]

    def test_good_sample_passes_with_visual_and_shopping(self):
        self.assertTrue(q.evaluate(fx.good_amount(), fx.task()["主キーワード"], fx.task()["補助キーワード"], [], CATS)["pass"])

    def test_missing_visual_or_shopping_fails(self):
        for key, msg in (("visual", "visual"), ("shopping", "shopping")):
            with self.subTest(key=key):
                a = fx.good_amount()
                del a[key]
                self.assertTrue(any(msg in e for e in self.errors(a)), self.errors(a))

    def test_diagram_needs_sources_and_catch_has_no_numbers(self):
        a = fx.good_amount()
        a["visual"]["catch"] = ["粉は10gで"]
        a["visual"]["diagram"]["items"][0]["cite"] = []
        errs = self.errors(a)
        self.assertTrue(any("catch" in e and "数値" in e for e in errs), errs)
        self.assertTrue(any("出典番号（cite）がない" in e for e in errs), errs)

    def test_unknown_motif_and_too_few_items_fail(self):
        a = fx.good_amount()
        a["visual"]["motif"] = "robot"
        a["visual"]["diagram"]["items"] = a["visual"]["diagram"]["items"][:2]
        errs = self.errors(a)
        self.assertTrue(any("motif" in e for e in errs), errs)
        self.assertTrue(any("3〜6個" in e for e in errs), errs)

    def test_shopping_must_not_recommend_or_invent_numbers(self):
        a = fx.good_amount()
        a["shopping"][0]["reason"] = "一番人気のスケールです。0.1g単位で量れるのでおすすめです。"
        a["shopping"][1]["query"] = "https://www.amazon.co.jp/dp/XXXX"
        errs = self.errors(a)
        for word in ("おすすめ", "人気", "一番"):
            self.assertTrue(any(word in e for e in errs), (word, errs))
        self.assertTrue(any("出典番号のない数値" in e for e in errs), errs)
        self.assertTrue(any("query" in e for e in errs), errs)


class ProductRules(unittest.TestCase):
    """商品の例は任意。載せるならメーカー公式の出典・確認日つきで、順位・価格・推奨・感想を書かない。"""

    def product(self):
        return {"name": "テストミル", "maker": "テスト社", "model": "TM-1", "facts": ["臼式の手挽きミル", "挽き目を段階的に調整できる"],
                "fit": "器具ごとに挽き目を切り替えたい人向けの手挽きの例です。", "query": "テスト社 テストミル TM-1",
                "checked": "2026-11-28", "source": {"title": "テスト社：テストミル", "url": "https://www.example.co.jp/mill"}}

    def test_published_articles_have_valid_products(self):
        for p in sorted((REPO / "content/articles").glob("*.json")):
            a = json.loads(p.read_text())["article"]
            with self.subTest(slug=p.stem):
                self.assertTrue(a.get("products"))
                self.assertEqual(q.product_errors(a), [])

    def test_valid_product_passes_and_absent_is_allowed(self):
        a = fx.good_amount()
        self.assertEqual(q.product_errors(a), [])
        a["products"] = [self.product()]
        self.assertEqual(q.product_errors(a), [])

    def test_rankings_prices_experience_and_missing_source_fail(self):
        a = fx.good_amount()
        bad = self.product()
        bad["facts"].append("一番人気で税込1,980円")
        bad["fit"] = "実際に使ってみて、約4分の抽出にちょうどよかったミルです。"
        bad["source"] = {"title": "", "url": "http://example.com"}
        bad["checked"] = ""
        a["products"] = [bad]
        errs = " ".join(q.product_errors(a))
        for word in ("人気", "一番", "価格", "感想", "出典", "確かめた日", "単位つきの数値"):
            self.assertIn(word, errs)


class StorageCitationRegression(unittest.TestCase):
    """実際の保留原稿を固定し、既存の判定を変更せず修正版を検査する。"""

    @classmethod
    def setUpClass(cls):
        d = REPO / "docs/proposals/coffee-storage-20261126"
        cls.original = json.loads((d / "original-article.json").read_text())
        cls.fixed = json.loads((d / "article.json").read_text())
        # 保存時の原稿には図解と商品の検索リンクがなかった（後から必須にした）。公開版で付けたものを足して数値の判定を確かめる
        published = json.loads((REPO / "content/articles/coffee-bean-storage.json").read_text())["article"]
        cls.fixed["visual"], cls.fixed["shopping"] = published["visual"], published["shopping"]

    def evaluate(self, article):
        existing = [item["article"] for p in (REPO / "content/articles").glob("*.json")
                    if (item := json.loads(p.read_text()))["slug"] != "coffee-bean-storage"]
        return q.evaluate(article, "コーヒー豆 保存方法", "コーヒー豆 冷凍;粉 保存 期間", existing,
                          CATS, {"min_chars": 2500, "h2": (5, 8), "faq": (3, 5)})

    def test_original_reproduces_twelve_uncited_sentences(self):
        r = self.evaluate(self.original)
        self.assertEqual(r["metrics"]["uncited_numbers"], 12, r)
        self.assertFalse(r["pass"])

    def test_corrected_draft_passes_unchanged_gate(self):
        r = self.evaluate(self.fixed)
        self.assertTrue(r["pass"], r)
        self.assertEqual(r["metrics"]["uncited_numbers"], 0)

    def test_period_after_citation_is_required_in_each_sentence(self):
        for text, count in [("粉は1〜2週間 [1]。", 0), ("粉は1〜2週間。 [1]", 1),
                            ("粉は1〜2週間。豆は1〜3週間 [1]。", 1)]:
            with self.subTest(text=text):
                a = copy.deepcopy(self.fixed)
                a["lead"] += text
                self.assertEqual(self.evaluate(a)["metrics"]["uncited_numbers"], count)

    def test_missing_citation_in_each_supported_location_is_held(self):
        for key in ("conclusion", "lead", "next_step", "faq", "checklist", "can_do", "table", "example"):
            with self.subTest(key=key):
                a = copy.deepcopy(self.fixed)
                text = "保存の目安は99週間です。"
                if key in ("conclusion", "lead", "next_step"): a[key] += text
                elif key == "faq": a[key][0]["a"] += text
                elif key in ("checklist", "can_do"): a[key].append(text)
                elif key == "table": a["sections"][0]["blocks"][1]["rows"].append(["試験の豆", text, "暗所"])
                else: a["sections"][0]["blocks"].append({"type": "example", "lines": [text]})
                r = self.evaluate(a)
                self.assertFalse(r["pass"], r)
                self.assertGreater(r["metrics"]["uncited_numbers"], 0)

    def test_nonexistent_source_still_fails(self):
        a = copy.deepcopy(self.fixed)
        a["lead"] += "試験の期間は99週間です [99]。"
        self.assertIn("存在しない出典番号", joined(self.evaluate(a)))

    def test_every_numeric_table_cell_has_its_own_citation(self):
        for _, b in q.blocks_of(self.fixed):
            if b.get("type") == "table":
                for row in b["rows"]:
                    for cell in row:
                        for sentence in __import__('re').split(r"(?<=[。！？!?])", cell):
                            if q.NUMBER_WITH_UNIT.search(q.strip_cites(sentence)):
                                self.assertRegex(sentence, q.CITE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
