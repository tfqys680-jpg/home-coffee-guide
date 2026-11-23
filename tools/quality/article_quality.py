#!/usr/bin/env python3
"""記事原稿の品質ゲート（決定論。AIの判断を使わない）。

過去の失敗「内容が薄く、どの記事も似通う」を機械的に落とすための判定。
pipeline.py が公開前に呼び、tools/verify.sh が公開済みの全記事に対して呼ぶ。

判定（errors があれば不合格、warnings は参考）:
- 形式（手順・比較・トラブル解決・基礎知識）とカテゴリが正しく、形式ごとの必須ブロックがある
- 早見表か比較表（3行以上の表）が1つ以上ある
- 主キーワードがタイトル前半・説明文・冒頭（結論と導入）に入り、補助キーワードが本文に入っている
- 同じ文を繰り返していない／決まり文句が多すぎない
- 単位つきの数値に出典番号 [n] が付いている
- 既存記事と本文が似すぎていない（文字3-gramのJaccard係数）、H2見出しが重複しない
- 中身の薄いH2セクションが続かない

使い方:
  python3 tools/quality/article_quality.py --all            # 公開済みの全記事を判定（不合格があれば終了コード1）
  python3 tools/quality/article_quality.py content/articles/<slug>.json [--json]
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("SITE_ROOT", Path(__file__).resolve().parents[2]))

FORMATS = ("手順", "比較", "トラブル解決", "基礎知識")
# 出たら即不合格の決まり文句
HARD_FILLERS = ("いかがでしたか", "いかがでしたでしょうか", "奥が深い", "完全ガイド", "徹底解説")
# 多すぎると不合格（1,000字あたりの回数で判定）
SOFT_FILLERS = ("様々な", "さまざまな", "ぜひ", "大切です", "重要です", "ポイントです", "おすすめです", "魅力",
                "楽しみ方", "参考にしてください", "してみてください", "と言えるでしょう", "ではないでしょうか")
SOFT_FILLER_MAX_PER_1000 = 2.0
SIMILARITY_ERROR = 0.40
SIMILARITY_WARN = 0.30
UNIT = r"(?:g|グラム|mg|ml|mL|ミリリットル|cc|℃|度|分|秒|時間|日|週間|か月|ヶ月|カ月|%|％)"
NUMBER_WITH_UNIT = re.compile(r"\d+(?:\.\d+)?\s*(?:[〜～\-]\s*\d+(?:\.\d+)?)?\s*" + UNIT + r"(?![a-zA-Z])")
CITE = re.compile(r"\[\d+\]")
LINK = re.compile(r"\[\[[^|\]]+\|([^\]]+)\]\]")  # 本文内の記事リンク [[slug|リンク文]]


# ---------------------------------------------------------------- text helpers

def strip_cites(s):
    """出典番号を消し、記事リンクはリンク文だけにする。"""
    return CITE.sub("", LINK.sub(r"\1", str(s)))


def norm(s):
    return re.sub(r"[\s　、。・「」『』（）()！？!?：:,.\-]", "", strip_cites(s))


def blocks_of(article):
    for s in article.get("sections", []):
        for b in s.get("blocks", []):
            yield s, b


def body_units(article):
    """出典チェックや重複チェックの単位（段落・箇条・表の行・例・FAQ回答など）。"""
    units = [article.get("conclusion", ""), article.get("lead", ""), article.get("next_step", "")]
    for _, b in blocks_of(article):
        t = b.get("type")
        if t == "p":
            units.append(b.get("text", ""))
        elif t in ("ul", "ol"):
            units += list(b.get("items", []))
        elif t == "example":
            units += list(b.get("lines", []))
        elif t == "table":
            units += [" ".join(map(str, row)) for row in b.get("rows", [])]
    units += [f.get("a", "") for f in article.get("faq", [])]
    return [str(u) for u in units if str(u).strip()]


def full_text(article):
    parts = [article.get(k, "") for k in ("title", "description", "conclusion", "lead", "next_step")]
    parts += list(article.get("can_do", [])) + list(article.get("checklist", []))
    for s in article.get("sections", []):
        parts.append(s.get("heading", ""))
    for _, b in blocks_of(article):
        parts += [b.get("text", "")] + list(b.get("items", [])) + list(b.get("lines", [])) + list(b.get("headers", []))
        for row in b.get("rows", []):
            parts += list(row)
    for f in article.get("faq", []):
        parts += [f.get("q", ""), f.get("a", "")]
    return strip_cites("\n".join(str(p) for p in parts))


def headings(article):
    hs = [s.get("heading", "") for s in article.get("sections", [])]
    hs += [b.get("text", "") for _, b in blocks_of(article) if b.get("type") == "h3"]
    return hs


def sentences(text):
    return [x for x in re.split(r"(?<=[。！？!?])", strip_cites(text)) if x.strip()]


def trigrams(text):
    t = re.sub(r"\s+", "", text)
    return {t[i:i + 3] for i in range(max(0, len(t) - 2))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def tokens(keyword):
    return [x for x in re.split(r"[\s　]+", str(keyword or "")) if x]


def missing_tokens(toks, text):
    return [t for t in toks if t not in text]


def allowed_missing(toks):
    return 1 if len(toks) >= 3 else 0


# ---------------------------------------------------------------- the gate

def evaluate(article, main_kw="", sub_kw="", existing=(), categories=None):
    """article: 記事本体（item["article"]）。existing: 比べる既存記事の本体のリスト（自分を含めない）。"""
    errors, warnings, metrics = [], [], {}

    # 形式・カテゴリ
    fmt = article.get("format")
    if fmt not in FORMATS:
        errors.append(f"形式（format）が「{fmt}」。{'・'.join(FORMATS)}のどれかにする")
    if categories is not None and article.get("category") not in categories:
        errors.append(f"カテゴリ（category）が「{article.get('category')}」。{', '.join(categories)} のどれかにする")

    tables = [b for _, b in blocks_of(article) if b.get("type") == "table"]
    big_tables = [b for b in tables if len(b.get("rows", [])) >= 3]
    ols = [b for _, b in blocks_of(article) if b.get("type") == "ol"]
    if not big_tables:
        errors.append("早見表か比較表（3行以上の表）がない")
    if fmt == "手順" and not any(len(b.get("items", [])) >= 4 for b in ols):
        errors.append("形式=手順なのに、4手順以上の番号付きリストがない")
    if fmt == "比較" and not any(len(b.get("headers", [])) >= 3 for b in big_tables):
        errors.append("形式=比較なのに、3列以上・3行以上の比較表がない")
    if fmt == "トラブル解決" and not any(any("原因" in str(h) for h in b.get("headers", [])) for b in big_tables):
        errors.append("形式=トラブル解決なのに、「原因」の列がある症状別の表がない")

    # キーワード
    title = str(article.get("title", ""))
    main = tokens(main_kw)
    if main:
        miss = missing_tokens(main, title)
        if len(miss) > allowed_missing(main):
            errors.append(f"主キーワードの語がタイトルにない: {'・'.join(miss)}")
        found = [title.find(t) for t in main if t in title]
        if found and min(found) > len(title) / 2:
            errors.append("主キーワードがタイトルの後半にしかない（前半に置く）")
        desc = str(article.get("description", ""))
        if len(missing_tokens(main, desc)) > len(main) // 2:
            errors.append("主キーワードの語が説明文（description）にほとんど入っていない")
        opening = str(article.get("conclusion", "")) + str(article.get("lead", ""))
        miss = missing_tokens(main, opening)
        if len(miss) > allowed_missing(main):
            errors.append(f"主キーワードの語が冒頭（結論・導入）にない: {'・'.join(miss)}")
    text = full_text(article)
    heading_text = "".join(headings(article))
    subs = [tokens(p) for p in str(sub_kw or "").split(";") if p.strip()]
    for toks in subs:
        miss = missing_tokens(toks, text)
        if len(miss) > allowed_missing(toks):
            errors.append(f"補助キーワード「{' '.join(toks)}」が本文にない")
    if subs and not any(len(missing_tokens(t, heading_text)) <= allowed_missing(t) for t in subs):
        warnings.append("補助キーワードがどの見出しにも入っていない")

    # 繰り返し・決まり文句
    seen, dups = set(), 0
    for u in body_units(article):
        for s in sentences(u):
            k = norm(s)
            if len(k) < 12:
                continue
            if k in seen:
                dups += 1
            seen.add(k)
    metrics["duplicate_sentences"] = dups
    if dups:
        errors.append(f"同じ文の繰り返しが{dups}文ある")
    for f in HARD_FILLERS:
        if f in text:
            errors.append(f"決まり文句「{f}」")
    chars = len(re.sub(r"\s", "", text))
    soft = sum(text.count(f) for f in SOFT_FILLERS)
    per1000 = soft / max(chars, 1) * 1000
    metrics["filler_per_1000"] = round(per1000, 2)
    if per1000 > SOFT_FILLER_MAX_PER_1000:
        errors.append(f"決まり文句が多い（1,000字あたり{per1000:.1f}回、上限{SOFT_FILLER_MAX_PER_1000}回）")
    elif per1000 > SOFT_FILLER_MAX_PER_1000 / 2:
        warnings.append(f"決まり文句がやや多い（1,000字あたり{per1000:.1f}回）")

    # 数値の出典
    uncited = []
    for u in body_units(article):
        for s in re.split(r"(?<=[。！？!?])", str(u)):
            if NUMBER_WITH_UNIT.search(strip_cites(s)) and not CITE.search(s):
                uncited.append(strip_cites(s).strip()[:40])
    metrics["uncited_numbers"] = len(uncited)
    if uncited:
        errors.append(f"出典番号のない数値が{len(uncited)}か所: 「{uncited[0]}」など")
    metrics["citations"] = len(CITE.findall(json.dumps(article, ensure_ascii=False)))

    # 薄いセクション
    thin = []
    for s in article.get("sections", []):
        size = sum(len(strip_cites(" ".join([b.get("text", "")] + list(b.get("items", [])) + list(b.get("lines", []))
                                              + [" ".join(map(str, r)) for r in b.get("rows", [])])))
                   for b in s.get("blocks", []))
        if size < 150:
            thin.append(s.get("heading", ""))
    if len(thin) >= 2:
        errors.append(f"中身の薄いH2が{len(thin)}つ（150字未満）: {'・'.join(thin[:3])}")
    elif thin:
        warnings.append(f"中身の薄いH2: {thin[0]}")

    # 既存記事との類似
    mine = trigrams(text)
    my_heads = {norm(h) for h in (s.get("heading", "") for s in article.get("sections", [])) if norm(h)}
    best, best_title, head_dups = 0.0, "", 0
    for other in existing:
        sim = jaccard(mine, trigrams(full_text(other)))
        if sim > best:
            best, best_title = sim, other.get("title", "")
        head_dups = max(head_dups, len(my_heads & {norm(s.get("heading", "")) for s in other.get("sections", [])}))
    metrics["max_similarity"] = round(best, 3)
    if best >= SIMILARITY_ERROR:
        errors.append(f"既存記事「{best_title}」と本文が似すぎている（類似度{best:.2f}、上限{SIMILARITY_ERROR}）")
    elif best >= SIMILARITY_WARN:
        warnings.append(f"既存記事「{best_title}」と本文がやや似ている（類似度{best:.2f}）")
    if head_dups >= 2:
        errors.append(f"既存記事とH2見出しが{head_dups}つ同じ")
    elif head_dups:
        warnings.append("既存記事と同じH2見出しが1つある")

    metrics["chars"] = chars
    return {"pass": not errors, "errors": errors, "warnings": warnings, "metrics": metrics}


# ---------------------------------------------------------------- CLI

def load_items():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "content/articles").glob("*.json"))]


def site_categories():
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    return [c["slug"] for c in site.get("categories", [])]


def evaluate_item(item, items, categories):
    others = [i["article"] for i in items if i["slug"] != item["slug"]]
    return evaluate(item["article"], item.get("main_kw", ""), item.get("sub_kw", ""), others, categories)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    items = load_items()
    categories = site_categories()
    targets = items if args.all else [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.paths]
    results = {t["slug"]: evaluate_item(t, items, categories) for t in targets}
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        print(f"articles: {len(results)}")
        for slug, r in results.items():
            print(f"{'OK  ' if r['pass'] else 'FAIL'} {slug} {json.dumps(r['metrics'], ensure_ascii=False)}")
            for x in r["errors"]:
                print(f"  × {x}")
            for x in r["warnings"]:
                print(f"  △ {x}")
    return 0 if all(r["pass"] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
