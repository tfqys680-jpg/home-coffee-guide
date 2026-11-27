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
- 事実の裏付けがある（出典つきの記述が4か所以上・出典2種以上、数値も出典も手順もないH2が半数以下）
- 表と手順に中身がある（空・ダッシュ・「人による」だけの表、同じ値が並ぶ列、空の手順を認めない）
- あいまい表現や主キーワードの詰め込みが多すぎない
- 既存記事と同じ文・ほぼ同じ文・同じ数値の組み合わせを使い回していない
- 見えない文字（ゼロ幅スペースなど）で判定をすり抜けない（NFKC正規化してから判定）

使い方:
  python3 tools/quality/article_quality.py --all            # 公開済みの全記事を判定（不合格があれば終了コード1）
  python3 tools/quality/article_quality.py content/articles/<slug>.json [--json]
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(os.environ.get("SITE_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "media"))
from media_spec import DIAGRAM_TYPES, MOTIFS, SHOP_BANNED  # noqa: E402

FORMATS = ("手順", "比較", "トラブル解決", "基礎知識")
# 出たら即不合格の決まり文句
HARD_FILLERS = ("いかがでしたか", "いかがでしたでしょうか", "奥が深い", "完全ガイド", "徹底解説")
# 多すぎると不合格（1,000字あたりの回数で判定）
SOFT_FILLERS = ("様々な", "さまざまな", "ぜひ", "大切です", "重要です", "ポイントです", "おすすめです", "魅力",
                "楽しみ方", "参考にしてください", "してみてください", "と言えるでしょう", "ではないでしょうか")
SOFT_FILLER_MAX_PER_1000 = 2.0
# あいまいで情報のない言い回し（1,000字あたり3回まで）
HEDGES = ("人によって", "人それぞれ", "好みによる", "好みによって", "好みや使い方", "場合による", "状況に合わせ", "その時々",
          "無理なく", "無理のない", "自分に合", "自分なり", "少しずつ", "大事になります", "欠かせません", "よいでしょう",
          "柔軟", "前向き", "気持ちよく", "満足し", "意味がある", "答えは一つではない", "唯一の答え", "正解は一つ")
HEDGE_MAX_PER_1000 = 3.0
VAGUE_CELLS = {"", "—", "-", "–", "―", "なし", "特になし", "人による", "好みによる", "場合による", "状況による", "状況次第",
               "いろいろ", "さまざま", "様々"}
SIMILARITY_ERROR = 0.30
SIMILARITY_WARN = 0.22
UNIT = (r"(?:kg|g|グラム|mg|ml|mL|ミリリットル|cc|℃|°C|°|度|分|秒|時間|日|週間|か月|ヶ月|カ月|%|L|リットル|cm|mm|倍|kcal|円|気圧|回)")
NUMBER_WITH_UNIT = re.compile(r"\d+(?:\.\d+)?\s*(?:[〜～~\-]\s*\d+(?:\.\d+)?)?\s*" + UNIT + r"(?![a-zA-Z])"
                              r"|\d+(?:\.\d+)?\s*[:：]\s*\d+(?:\.\d+)?")  # 比率（1:15 など）も数値として扱う
CITE = re.compile(r"\[\d+\]")
LINK = re.compile(r"\[\[[^|\]]+\|([^\]]+)\]\]")  # 本文内の記事リンク [[slug|リンク文]]


# ---------------------------------------------------------------- text helpers

def clean(s):
    """NFKC正規化し、ゼロ幅スペースなどの書式文字（Unicode Cf）を取り除く。"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(s)) if unicodedata.category(ch) != "Cf")


def deep(o, f):
    if isinstance(o, str):
        return f(o)
    if isinstance(o, list):
        return [deep(x, f) for x in o]
    if isinstance(o, dict):
        return {k: deep(v, f) for k, v in o.items()}
    return o


def has_invisible(o):
    return any(unicodedata.category(ch) == "Cf" for ch in json.dumps(o, ensure_ascii=False))


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

def section_text(s):
    return " ".join(str(b.get("text", "")) + " " + " ".join(map(str, b.get("items", []))) + " "
                    + " ".join(map(str, b.get("lines", []))) + " " + " ".join(" ".join(map(str, r)) for r in b.get("rows", []))
                    for b in s.get("blocks", []))


def anchored(s):
    """数値・出典・3項目以上の具体的なリストのどれかがあるH2か。"""
    t = section_text(s)
    if CITE.search(t) or re.search(r"\d", t):
        return True
    return any(b.get("type") in ("ol", "ul") and len([i for i in b.get("items", []) if len(norm(i)) >= 8]) >= 3
               for b in s.get("blocks", []))


def informative_table(b):
    rows = [[norm(c) for c in r] for r in b.get("rows", [])]
    if len(rows) < 3 or len({tuple(r) for r in rows}) < len(rows):
        return False
    if any(len(c) < 2 or c in VAGUE_CELLS for r in rows for c in r):
        return False
    if any(len(set(col)) == 1 for col in list(zip(*rows))[1:]):
        return False
    return sum(1 for r in b.get("rows", []) if re.search(r"\d|\[\d+\]", " ".join(map(str, r)))) >= 2


def long_sentences(article):
    out = []
    for u in body_units(article):
        out += [norm(s) for s in sentences(u) if len(norm(s)) >= 15]
    return out


def numbers_of(article):
    return {re.sub(r"\s", "", x.group(0)) for u in body_units(article) for x in NUMBER_WITH_UNIT.finditer(strip_cites(u))}


def visual_errors(article):
    """アイキャッチ・図解・動画の元（visual）と、商品の検索リンク（shopping）の検査。
    滞在時間と商品ページへの移動を生む部分なので、ない記事・出典のない図解・商品の推奨は不合格にする。"""
    errors = []
    n_src = len(article.get("sources", []))
    v = article.get("visual")
    if not isinstance(v, dict):
        return ["アイキャッチ・図解・動画の元（visual）がない"] + shopping_errors(article)
    catch = v.get("catch")
    if not (isinstance(catch, list) and 1 <= len(catch) <= 3 and all(isinstance(c, str) and 2 <= len(c) <= 10 for c in catch)):
        errors.append("visual.catch は1〜3行、各2〜10字にする（アイキャッチの見出し）")
    elif any(NUMBER_WITH_UNIT.search(c) for c in catch):
        errors.append("visual.catch に単位つきの数値を入れない（出典番号を示せないため）")
    if v.get("motif") not in MOTIFS:
        errors.append(f"visual.motif が「{v.get('motif')}」。{', '.join(MOTIFS)} のどれかにする")
    dg = v.get("diagram")
    if not isinstance(dg, dict):
        errors.append("図解（visual.diagram）がない")
        return errors + shopping_errors(article)
    if dg.get("type") not in DIAGRAM_TYPES:
        errors.append(f"図解の種類（visual.diagram.type）が「{dg.get('type')}」。{', '.join(DIAGRAM_TYPES)} のどれかにする")
    if not 4 <= len(str(dg.get("title", ""))) <= 30:
        errors.append("図解の見出し（visual.diagram.title）は4〜30字にする")
    items = dg.get("items") or []
    if not 3 <= len(items) <= 6:
        errors.append(f"図解の項目が{len(items)}個（3〜6個にする）")
    cited = 0
    for i, it in enumerate(items):
        label, detail, note = str(it.get("label", "")), str(it.get("detail", "")), str(it.get("note", ""))
        if not 1 <= len(label) <= 12 or not 4 <= len(detail) <= 40 or len(note) > 40:
            errors.append(f"図解の項目{i + 1}: label 1〜12字・detail 4〜40字・note 40字以内にする")
        cites = it.get("cite") or []
        if not all(isinstance(c, int) and 1 <= c <= n_src for c in cites):
            errors.append(f"図解の項目{i + 1}: cite に存在しない出典番号がある {cites}")
        if cites:
            cited += 1
        elif NUMBER_WITH_UNIT.search(detail + note):
            errors.append(f"図解の項目{i + 1}: 単位つきの数値に出典番号（cite）がない")
        if CITE.search(label + detail + note):
            errors.append(f"図解の項目{i + 1}: 出典番号は本文の [n] ではなく cite に入れる")
    need = len(items) if dg.get("type") in ("scale", "compare") else (len(items) + 1) // 2
    if items and cited < need:
        errors.append(f"図解の項目のうち出典（cite）があるのが{cited}個（{need}個以上必要。図解は出典の事実から作る）")
    return errors + shopping_errors(article)


def shopping_errors(article):
    errors = []
    shop = article.get("shopping")
    if not isinstance(shop, list) or not 2 <= len(shop) <= 4:
        return ["商品の検索リンク（shopping）が2〜4件ない"]
    n_src = len(article.get("sources", []))
    for i, it in enumerate(shop):
        label, query, reason = str(it.get("label", "")), str(it.get("query", "")), str(it.get("reason", ""))
        if not 4 <= len(label) <= 30:
            errors.append(f"shopping[{i}].label は4〜30字にする")
        elif NUMBER_WITH_UNIT.search(label):
            errors.append(f"shopping[{i}].label に単位つきの数値を入れない（理由の文で出典を付けて書く）")
        if not 2 <= len(query) <= 40 or re.search(r"https?:|www\.|[<>]", query):
            errors.append(f"shopping[{i}].query は検索語（2〜40字、URLなし）にする")
        if len(reason) < 30:
            errors.append(f"shopping[{i}].reason が短い（記事の選び方の条件と結びつけて30字以上）")
        for w in SHOP_BANNED:
            if w in label + reason:
                errors.append(f"shopping[{i}]: 推奨・順位づけの言葉「{w}」を使わない")
        for s in re.split(r"(?<=[。！？!?])", reason):
            if NUMBER_WITH_UNIT.search(strip_cites(s)) and not CITE.search(s):
                errors.append(f"shopping[{i}].reason: 出典番号のない数値「{strip_cites(s).strip()[:30]}」")
        bad = [int(x) for x in re.findall(r"\[(\d+)\]", reason) if not 1 <= int(x) <= n_src]
        if bad:
            errors.append(f"shopping[{i}].reason: 存在しない出典番号 {bad}")
    return errors


def evaluate(article, main_kw="", sub_kw="", existing=(), categories=None, limits=None):
    """article: 記事本体（item["article"]）。existing: 比べる既存記事の本体のリスト（自分を含めない）。
    limits: {"min_chars": int, "h2": (min, max), "faq": (min, max)}（公開済み記事の検査で使う）"""
    errors, warnings, metrics = [], [], {}
    if has_invisible(article):
        errors.append("見えない文字（ゼロ幅スペースなど）が含まれる")
    article = deep(article, clean)
    existing = [deep(o, clean) for o in existing]
    main_kw, sub_kw = clean(main_kw), clean(sub_kw)

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
    elif fmt == "手順" and not any(len(b.get("items", [])) >= 4 and all(len(norm(i)) >= 8 for i in b["items"])
                                  and len({norm(i) for i in b["items"]}) == len(b["items"]) for b in ols):
        errors.append("番号付きの手順の中身が空・短すぎる（8字未満）・重複している")
    metrics["informative_tables"] = sum(informative_table(b) for b in big_tables)
    if big_tables and not metrics["informative_tables"]:
        errors.append("3行以上の表に中身がない（空欄・ダッシュ・「人による」だけ、同じ値が並ぶ列、数値も出典もない行ばかり）")
    if fmt == "比較" and not any(len(b.get("headers", [])) >= 3 for b in big_tables):
        errors.append("形式=比較なのに、3列以上・3行以上の比較表がない")
    if fmt == "トラブル解決" and not any(any("原因" in str(h) for h in b.get("headers", [])) for b in big_tables):
        errors.append("形式=トラブル解決なのに、「原因」の列がある症状別の表がない")
    if fmt == "基礎知識":
        first = str(article.get("conclusion", "")) + " ".join(
            str(b.get("text", "")) for b in (article.get("sections") or [{}])[0].get("blocks", []) if b.get("type") == "p")
        if not re.search(r"とは|のこと[でを]|を指し|という意味|を意味", first):
            errors.append("形式=基礎知識なのに、結論か最初のH2に1文での定義（「〜とは」「〜のことです」など）がない")

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
        miss = missing_tokens(main, desc)
        if len(miss) > allowed_missing(main):
            errors.append(f"主キーワードの語が説明文（description）にない: {'・'.join(miss)}")
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
    hedge = sum(text.count(h) for h in HEDGES) / max(chars, 1) * 1000
    metrics["hedge_per_1000"] = round(hedge, 2)
    if hedge > HEDGE_MAX_PER_1000:
        errors.append(f"あいまいな言い回しが多い（1,000字あたり{hedge:.1f}回、上限{HEDGE_MAX_PER_1000}回）")
    toks = [t for t in main if len(t) >= 2]
    if toks:
        dens = {t: text.count(t) / max(chars, 1) * 1000 for t in toks}
        sents_all = sentences(text)
        share = sum(1 for x in sents_all if all(t in x for t in toks)) / max(len(sents_all), 1)
        title_rep = max(title.count(t) for t in toks)
        metrics["keyword_max_per_1000"] = round(max(dens.values()), 1)
        if max(dens.values()) > 30 or share >= 0.4 or title_rep > 2:
            errors.append(f"主キーワードの詰め込み（1,000字あたり最大{max(dens.values()):.0f}回、"
                          f"全語を含む文の割合{share:.0%}、タイトル内の繰り返し{title_rep}回）")

    # 数値の出典
    uncited = []
    for u in body_units(article):
        for s in re.split(r"(?<=[。！？!?])", str(u)):
            if NUMBER_WITH_UNIT.search(strip_cites(s)) and not CITE.search(s):
                uncited.append(strip_cites(s).strip()[:40])
    for u in list(article.get("can_do", [])) + list(article.get("checklist", [])):
        if NUMBER_WITH_UNIT.search(strip_cites(u)) and not CITE.search(str(u)):
            uncited.append(strip_cites(u).strip()[:40])
    cited_numbers = {re.sub(r"\s", "", m.group(0)) for u in body_units(article) + list(article.get("can_do", []))
                     + list(article.get("checklist", [])) if CITE.search(str(u)) for m in NUMBER_WITH_UNIT.finditer(strip_cites(u))}
    labels = [article.get("title", ""), article.get("description", ""), article.get("breadcrumb", "")] + headings(article)
    labels += [f.get("q", "") for f in article.get("faq", [])]
    labels += [h for _, b in blocks_of(article) if b.get("type") == "table" for h in b.get("headers", [])]
    for lab in labels:
        for m in NUMBER_WITH_UNIT.finditer(strip_cites(lab)):
            if re.sub(r"\s", "", m.group(0)) not in cited_numbers:
                uncited.append(f"{strip_cites(lab).strip()[:30]}（本文で出典を付けていない数値 {m.group(0)}）")
    metrics["uncited_numbers"] = len(uncited)
    if uncited:
        errors.append(f"出典番号のない数値が{len(uncited)}か所: 「{uncited[0]}」など")
    metrics["citations"] = len(CITE.findall(json.dumps(article, ensure_ascii=False)))
    units = body_units(article)
    cited_units = [u for u in units if CITE.search(u)]
    cited_ids = {int(x) for u in units for x in re.findall(r"\[(\d+)\]", u)}
    metrics["cited_units"], metrics["sources_cited"] = len(cited_units), len(cited_ids)
    if len(cited_units) < 4 or len(cited_ids) < 2:
        errors.append(f"出典で裏付けた記述が少ない（{len(cited_units)}か所・出典{len(cited_ids)}種。4か所以上・2種以上必要）")
    bad_ids = sorted(i for i in cited_ids if not 1 <= i <= len(article.get("sources", [])))
    if bad_ids:
        errors.append(f"存在しない出典番号 {bad_ids}")
    loose = [s.get("heading", "") for s in article.get("sections", []) if not anchored(s)]
    metrics["unanchored_h2"] = len(loose)
    if len(loose) * 2 > len(article.get("sections", [])):
        errors.append(f"数値・出典・具体的な手順のないH2が半数を超える（{len(loose)}/{len(article.get('sections', []))}）")

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
    my_sents, my_nums = long_sentences(article), numbers_of(article)
    best, best_title, head_dups = 0.0, "", 0
    reuse = {"same_sentences": 0, "near_sentence_share": 0.0, "number_overlap": 0.0}
    for other in existing:
        sim = jaccard(mine, trigrams(full_text(other)))
        if sim > best:
            best, best_title = sim, other.get("title", "")
        their_heads = [trigrams(norm(s.get("heading", ""))) for s in other.get("sections", [])]
        head_dups = max(head_dups, sum(1 for h in my_heads
                                       if any(jaccard(trigrams(h), t) >= 0.6 for t in their_heads)))
        theirs = set(long_sentences(other))
        reuse["same_sentences"] = max(reuse["same_sentences"], sum(1 for x in my_sents if x in theirs))
        their_tri = [trigrams(x) for x in theirs]
        near = sum(1 for x in my_sents if max((jaccard(trigrams(x), t) for t in their_tri), default=0) >= 0.5)
        reuse["near_sentence_share"] = max(reuse["near_sentence_share"], round(near / max(len(my_sents), 1), 2))
        o_nums = numbers_of(other)
        if len(my_nums) >= 3 and len(o_nums) >= 3:
            reuse["number_overlap"] = max(reuse["number_overlap"], round(len(my_nums & o_nums) / len(my_nums | o_nums), 2))
    metrics.update(reuse)
    if reuse["same_sentences"] >= 3:
        errors.append(f"既存記事と同じ文を{reuse['same_sentences']}文使い回している")
    if reuse["near_sentence_share"] >= 0.2:
        errors.append(f"既存記事の言い換えに近い文が{reuse['near_sentence_share']:.0%}ある")
    if reuse["number_overlap"] >= 0.5:
        errors.append(f"既存記事と数値の組み合わせがほぼ同じ（重なり{reuse['number_overlap']}）")
    metrics["max_similarity"] = round(best, 3)
    if best >= SIMILARITY_ERROR:
        errors.append(f"既存記事「{best_title}」と本文が似すぎている（類似度{best:.2f}、上限{SIMILARITY_ERROR}）")
    elif best >= SIMILARITY_WARN:
        warnings.append(f"既存記事「{best_title}」と本文がやや似ている（類似度{best:.2f}）")
    if head_dups >= 2:
        errors.append(f"既存記事とH2見出しが{head_dups}つ同じかほぼ同じ")
    elif head_dups:
        warnings.append("既存記事と同じかほぼ同じH2見出しが1つある")

    # アイキャッチ・図解・動画と、商品の検索リンク（滞在時間と商品ページへの移動のための必須要素）
    errors += visual_errors(article)

    metrics["chars"] = chars
    if limits:
        if chars < limits.get("min_chars", 0):
            errors.append(f"本文が短すぎる（{chars}字、{limits['min_chars']}字以上）")
        lo, hi = limits.get("h2", (0, 99))
        if not lo <= len(article.get("sections", [])) <= hi:
            errors.append(f"H2の数が{lo}〜{hi}の範囲外")
        lo, hi = limits.get("faq", (0, 99))
        if not lo <= len(article.get("faq", [])) <= hi:
            errors.append(f"FAQの数が{lo}〜{hi}の範囲外")
    return {"pass": not errors, "errors": errors, "warnings": warnings, "metrics": metrics}


# ---------------------------------------------------------------- CLI

def load_items():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "content/articles").glob("*.json"))]


def site_categories():
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    return [c["slug"] for c in site.get("categories", [])]


def published_limits():
    """公開済み記事の検査用。パイプラインの文字数下限（数え方の差を見込んで9割）とH2・FAQの数。"""
    cfg = json.loads((ROOT / "tools/auto-publish/config.json").read_text(encoding="utf-8"))
    return {"min_chars": int(cfg["min_body_chars"] * 0.9), "h2": (4, 9), "faq": (3, 6)}


def evaluate_item(item, items, categories, limits=None):
    others = [i["article"] for i in items if i["slug"] != item["slug"]]
    return evaluate(item["article"], item.get("main_kw", ""), item.get("sub_kw", ""), others, categories, limits)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    items = load_items()
    categories = site_categories()
    targets = items if args.all else [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.paths]
    limits = published_limits()
    results = {t["slug"]: evaluate_item(t, items, categories, limits) for t in targets}
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
