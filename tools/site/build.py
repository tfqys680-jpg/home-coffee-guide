#!/usr/bin/env python3
"""content/articles/*.json と site.json から静的サイト一式を生成する。

生成物: index.html, about.html, privacy.html, disclaimer.html, 404.html,
column/<slug>/index.html, category/<slug>/index.html（記事があるカテゴリのみ）, sitemap.xml, robots.txt
記事の中身は JSON に保存し、HTMLは毎回ここから作り直す（レイアウト変更が全記事に反映される）。
"""
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("SITE_ROOT", Path(__file__).resolve().parents[2]))
e = html.escape


def load_site():
    return json.loads((ROOT / "site.json").read_text(encoding="utf-8"))


def load_articles():
    items = []
    for p in sorted((ROOT / "content/articles").glob("*.json")):
        items.append(json.loads(p.read_text(encoding="utf-8")))
    return sorted(items, key=lambda a: (a["date"], a["slug"]), reverse=True)


def jp_date(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{y}年{m}月{d}日"


LINK = re.compile(r"\[\[([a-z0-9-]+)\|([^\]]+)\]\]")  # 本文内の記事リンク [[slug|リンク文]]
OGP = {"path": "images/ogp.png", "width": 1200, "height": 630}
LOGO = "images/logo.png"


def inline(text):
    """記事ページ（column/<slug>/）用。出典番号と記事リンクをHTMLにする。"""
    t = re.sub(r"\[(\d+)\]", r'<a href="#source\1" class="cite" aria-label="出典\1">[\1]</a>', e(str(text)))
    return LINK.sub(lambda m: f'<a href="../{m.group(1)}/">{m.group(2)}</a>', t)


def plain(text):
    return LINK.sub(r"\2", re.sub(r"\s*\[\d+\]", "", str(text))).strip()


def home(rel):
    return rel or "./"


def category_map(site):
    return {c["slug"]: c for c in site.get("categories", [])}


def ld(obj):
    return '<script type="application/ld+json">\n' + json.dumps(obj, ensure_ascii=False, indent=2) + "\n</script>"


def layout(site, *, title, description, rel, path, body, page_type="website", extra_head="", noindex=False, image=None):
    """rel: ルートへの相対パス（'' か '../../'）。path: サイト内パス（'' や 'column/x/'）。"""
    url = site["base_url"] + path
    img = image or {"url": site["base_url"] + OGP["path"], "width": OGP["width"], "height": OGP["height"]}
    img_size = "".join(f'<meta property="og:image:{k}" content="{img[k]}">\n' for k in ("width", "height") if img.get(k))
    full_title = title if title == site["site_name"] else f"{title}｜{site['site_name']}"
    ga = ""
    if site.get("ga_id"):
        ga = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={site["ga_id"]}"></script>\n'
              f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
              f"gtag('js',new Date());gtag('config','{site['ga_id']}');</script>\n")
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    # Search Console の所有権確認（HTMLタグ方式）。site.json の gsc_verification が空なら出力しない
    verify = (f'<meta name="google-site-verification" content="{e(site["gsc_verification"])}">\n'
              if site.get("gsc_verification") else "")
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{ga}<title>{e(full_title)}</title>
<meta name="description" content="{e(description)}">
{verify}{robots}<link rel="canonical" href="{url}">
<meta property="og:type" content="{page_type}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{url}">
<meta property="og:site_name" content="{e(site['site_name'])}">
<meta property="og:image" content="{e(img['url'])}">
{img_size}<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{rel}images/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{rel}css/style.css">
{extra_head}</head>
<body>
<a class="skip" href="#main">本文へ移動</a>
<header class="site-header">
  <div class="wrap header-inner">
    <p class="site-title"><a href="{home(rel)}"><span class="site-mark" aria-hidden="true"></span><span class="site-wordmark">{e(site['site_name'])}</span></a></p>
    <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="nav">メニュー</button>
    <nav id="nav" class="nav" aria-label="サイト内メニュー">
      <ul>
        <li><a href="{home(rel)}">ホーム</a></li>
        <li><a href="{home(rel)}#articles">記事一覧</a></li>
        <li><a href="{rel}about.html">運営者情報</a></li>
      </ul>
    </nav>
  </div>
</header>
<main id="main">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <ul class="footer-nav">
      <li><a href="{rel}about.html">運営者情報</a></li>
      <li><a href="{rel}privacy.html">プライバシーポリシー</a></li>
      <li><a href="{rel}disclaimer.html">免責事項・広告・AI利用について</a></li>
    </ul>
    <p class="small">本サイトの記事は生成AIで作成し、確認した出典を記事ごとに掲載しています。本サイトはアフィリエイト広告を利用することがあります。</p>
    <p class="small">&copy; <span class="js-year">2026</span> {e(site['site_name'])}</p>
  </div>
</footer>
<script src="{rel}js/main.js"></script>
</body>
</html>
"""


def render_block(b):
    t = b.get("type")
    if t == "p":
        return f"<p>{inline(b['text'])}</p>"
    if t == "h3":
        return f"<h3>{e(plain(b['text']))}</h3>"
    if t in ("ul", "ol"):
        return f"<{t}>" + "".join(f"<li>{inline(i)}</li>" for i in b.get("items", [])) + f"</{t}>"
    if t == "example":
        lines = "".join(f"<p>{inline(x)}</p>" for x in b.get("lines", []))
        return f'<div class="example"><p class="example-label">{e(b.get("label", "例"))}</p>{lines}</div>'
    if t == "table":
        head = "".join(f"<th scope=\"col\">{e(h)}</th>" for h in b.get("headers", []))
        body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in b.get("rows", []))
        return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    return ""


def operator_of(item):
    """運営者本人が書いた確認メモ・写真（item["operator"]）。メモも写真もなければ None。"""
    op = item.get("operator") or {}
    return op if (op.get("notes") or op.get("photos")) else None


def last_modified(item):
    dates = [item.get("updated", item["date"])]
    op = operator_of(item)
    if op and op.get("checked"):
        dates.append(op["checked"])
    return max(dates)


def render_operator(site, op, rel):
    figs = []
    for i, ph in enumerate(op.get("photos", [])):
        size = "".join(f' {k}="{int(ph[k])}"' for k in ("width", "height") if ph.get(k))
        lazy = ' loading="lazy"' if i else ""  # 1枚目は上部に出るので遅延読み込みしない
        cap = f'<figcaption>{e(ph["caption"])}</figcaption>' if ph.get("caption") else ""
        figs.append(f'<figure><img src="{rel}{e(ph["src"])}" alt="{e(ph.get("alt", ""))}"{size}{lazy} decoding="async">{cap}</figure>')
    when = f"（{jp_date(op['checked'])}・{e(site['operator'])}）" if op.get("checked") else f"（{e(site['operator'])}）"
    notes = "".join(f"<p>{e(n)}</p>" for n in op.get("notes", []))
    return (f'<aside class="operator-note" aria-label="運営者の確認メモ"><p class="operator-label">運営者の確認メモ{when}</p>'
            f'{notes}{"".join(figs)}</aside>')


BREW_FEATURE = "hand-drip-taste-adjustment"
EDITORIAL = "images/editorial/"


def render_brew_media(rel):
    media = rel + EDITORIAL
    return f"""
<section class="brew-studio" aria-labelledby="brew-studio-title">
  <p class="kicker">BREWING NOTES / 図と動画</p>
  <h2 id="brew-studio-title">次の一杯で、ひとつだけ。</h2>
  <p>同じ豆とお湯の量で、調整するのは下のうち一つだけ。味と落ち切り方を比べると、次に何を変えるか決めやすくなります。</p>
  <figure class="brew-overview">
    <img src="{media}brew-adjustments.webp" alt="手挽きミル、細かさの異なる三つの粉、紙・布・金属のフィルターを並べたイラスト" width="1200" height="800" loading="lazy" decoding="async">
    <figcaption>挽き目とフィルターの違いを見比べるための生成イラストです。</figcaption>
  </figure>
  <ol class="brew-diagram" aria-label="三つの調整ポイント">
    <li><span class="diagram-index" aria-hidden="true">01</span><strong>注ぎ方</strong><span>湯を落とす高さと場所は同じにして、まず注ぐ速さだけを比べる。</span></li>
    <li><span class="diagram-index" aria-hidden="true">02</span><strong>挽き目</strong><span>落ち切るのが遅く渋いなら、次は少し粗く。速くて薄いなら、少し細かく。</span></li>
    <li><span class="diagram-index" aria-hidden="true">03</span><strong>フィルター</strong><span>器具に合う紙を基準に。素材を比べるときは、挽き目や注ぎ方をそろえる。</span></li>
  </ol>
  <figure class="brew-film">
    <video controls playsinline preload="none" width="1280" height="720" poster="{media}brew-pour-demo-poster.webp" aria-label="ハンドドリップで抽出時間を記録する方法の図解動画">
      <source src="{media}brew-pour-demo.mp4" type="video/mp4">
      このブラウザーでは動画を再生できません。下の説明をお読みください。
    </video>
    <figcaption>蒸らしから抽出の終わりまでを計る、無音の図解です。動画の経過秒数は抽出の目安ではありません。</figcaption>
  </figure>
  <details class="faq"><summary>動画を文章で読む</summary>
    <ol>
      <li><strong>蒸らしで計り始める。</strong> 粉に最初のお湯が触れたら、タイマーをスタート。蒸らしも含めます。</li>
      <li><strong>注ぎ終わりを記録する。</strong> 最後のお湯を注いだ時点をメモし、計測は続けます。</li>
      <li><strong>ドリッパーを外して終了する。</strong> ドリッパーを外した時点を抽出時間の終点として記録します。</li>
      <li><strong>挽き目だけを一段変える。</strong> 豆・粉量・湯量・湯温・注ぎ方をそろえ、抽出時間と味の違いを比べます。</li>
    </ol>
  </details>
</section>"""


def render_article(site, item, by_slug):
    a, slug, date = item["article"], item["slug"], item["date"]
    path = f"column/{slug}/"
    url = site["base_url"] + path
    crumb = plain(a["breadcrumb"])
    cat = category_map(site).get(a.get("category"))
    op = operator_of(item)
    modified = last_modified(item)
    article_ld = {"@context": "https://schema.org", "@type": "Article", "headline": a["title"], "description": a["description"],
                  "datePublished": date, "dateModified": modified, "mainEntityOfPage": url,
                  "author": {"@type": "Organization", "name": site["author"]},
                  "publisher": {"@type": "Organization", "name": site["site_name"],
                                "logo": {"@type": "ImageObject", "url": site["base_url"] + LOGO}}}
    if op:
        article_ld["contributor"] = {"@type": "Person", "name": site["operator"], "url": site["base_url"] + "about.html"}
    photos = (op or {}).get("photos", [])
    article_ld["image"] = [site["base_url"] + ph["src"] for ph in photos] or [site["base_url"] + OGP["path"]]
    og_image = ({"url": site["base_url"] + photos[0]["src"], "width": photos[0].get("width"), "height": photos[0].get("height")}
                if photos else None)
    crumbs = [("ホーム", site["base_url"], "../../")]
    if cat:
        crumbs.append((cat["name"], site["base_url"] + f"category/{cat['slug']}/", f"../../category/{cat['slug']}/"))
    crumbs.append((crumb, url, None))
    lds = [
        article_ld,
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i, "name": n, "item": u} for i, (n, u, _) in enumerate(crumbs, 1)]},
        {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": plain(f["q"]), "acceptedAnswer": {"@type": "Answer", "text": plain(f["a"])}}
            for f in a["faq"]]},
    ]
    toc = "".join(f'<li><a href="#sec{i}">{e(plain(s["heading"]))}</a></li>' for i, s in enumerate(a["sections"], 1))
    feature_html = render_brew_media("../../") if slug == BREW_FEATURE else ""
    if feature_html:
        toc = '<li><a href="#brew-studio-title">図と動画で見る</a></li>' + toc
    def article_section(i, section):
        heading = plain(section["heading"])
        anchor = BREW_TOPIC_ANCHORS.get(heading) if slug == BREW_FEATURE else None
        content = "\n".join(render_block(b) for b in section.get("blocks", []))
        # Keep #secN on the heading for older direct links.
        markup = f'<h2 id="sec{i}">{e(heading)}</h2>\n{content}'
        return f'<section id="{anchor}" aria-labelledby="sec{i}">{markup}</section>' if anchor else markup

    sections = "\n".join(article_section(i, section) for i, section in enumerate(a["sections"], 1))
    related = [by_slug[r] for r in item.get("related", []) if r in by_slug and r != slug]
    related_html = ""
    if related:
        related_html = ('<section class="related"><h2>あわせて読みたい</h2><ul>' + "".join(
            f'<li><a href="../{r["slug"]}/">{e(r["article"]["title"])}</a></li>' for r in related) + "</ul></section>")
    srcs = "\n".join(f'<li id="source{i}"><a href="{e(s["url"])}" rel="noopener">[{i}] {e(s["title"])}</a></li>'
                     for i, s in enumerate(a["sources"], 1))
    notice = {"中": "健康や表示に関わる内容を含みます。体質や持病がある方は医師などに相談してください。",
              "高": "健康に関わる内容を含みます。体質や持病がある方、妊娠中・服薬中の方は医師に相談してください。"}.get(item.get("ymyl"), "")
    if op:
        human = (f"「運営者の確認メモ」は運営者（{e(site['operator'])}）が自分で確かめて書いたものです。"
                 "それ以外の本文について、人による試飲や器具のテストは行っていません。")
        byline_extra = f"　確認メモ：{e(site['operator'])}"
        operator_html = "\n" + render_operator(site, op, "../../")
    else:
        human, byline_extra, operator_html = "人による実際の試飲や器具のテストは行っていません。", "", ""
    review_note = ("この記事は生成AI（ChatGPT）で作成し、出典ページの本文を確認して編集しました。"
                   if item.get("review_mode") == "manual"
                   else "この記事は生成AI（ChatGPT）で下書きし、別の生成AI（Claude）が出典ページの本文と照合・推敲して公開しました。")
    source_check = ("出典ページの本文を確認" if item.get("review_mode") == "manual"
                    else "出典ページを自動で取得し、本文と照合")
    body = f"""<div class="wrap article-wrap">
<nav class="breadcrumb" aria-label="パンくずリスト"><ol>{"".join(f'<li><a href="{h}">{e(n)}</a></li>' if h else f'<li>{e(n)}</li>' for n, _, h in crumbs)}</ol></nav>
<article class="article">
<p class="meta">公開日：{jp_date(date)}　最終更新日：{jp_date(modified)}　作成：{e(site["author"])}（生成AI）{byline_extra}</p>
<h1>{e(a["title"])}</h1>
<div class="ai-note">{e(review_note)}{e(notice)}{human}</div>{operator_html}
<div class="summary"><p class="summary-label">結論</p><p>{inline(a["conclusion"])}</p></div>
<p>{inline(a["lead"])}</p>
<h2 id="can-do">この記事でわかること</h2><ul class="check">{"".join(f"<li>{inline(x)}</li>" for x in a["can_do"])}</ul>
<nav class="toc" aria-label="目次"><p class="toc-label">目次</p><ol>{toc}</ol></nav>
{feature_html}
{sections}
<h2 id="checklist">チェックリスト</h2><ul class="check">{"".join(f"<li>{inline(x)}</li>" for x in a["checklist"])}</ul>
<h2 id="faq">よくある質問</h2>
{"".join(f'<details class="faq"><summary>{e(plain(f["q"]))}</summary><p>{e(plain(f["a"]))}</p></details>' for f in a["faq"])}
<h2 id="next">次の一歩</h2>
<p>{inline(a["next_step"])}</p>
<h2 id="sources">出典・参考にした情報</h2>
<ol class="sources">
{srcs}
</ol>
<p class="small">確認日：{jp_date(date)}（{e(source_check)}）。情報は変わることがあるため、最新の内容は各出典で確認してください。</p>
{related_html}
</article>
</div>"""
    return layout(site, title=a["title"], description=a["description"], rel="../../", path=path, body=body,
                  page_type="article", extra_head="\n".join(ld(x) for x in lds) + "\n", image=og_image)


def article_list(items, rel=""):
    if not items:
        return '<p class="empty">最初の記事を準備しています。公開までしばらくお待ちください。</p>'
    return '<ul class="cards">' + "".join(
        f'<li><a href="{rel}column/{it["slug"]}/"><span class="card-title">{e(it["article"]["title"])}</span>'
        f'<span class="card-desc">{e(it["article"]["description"])}</span>'
        f'<span class="card-date">{jp_date(it["date"])}</span></a></li>' for it in items) + "</ul>"


def group_by_category(site, items):
    cats = category_map(site)
    groups = {}
    for it in items:
        c = it["article"].get("category")
        if c in cats:
            groups.setdefault(c, []).append(it)
    return [(cats[c["slug"]], groups[c["slug"]]) for c in site.get("categories", []) if c["slug"] in groups]


def category_nav(site, items):
    groups = group_by_category(site, items)
    if not groups:
        return ""
    lis = "".join(f'<li><a href="category/{c["slug"]}/">{e(c["name"])}<span>{len(its)}本</span></a></li>' for c, its in groups)
    return f'<section id="categories">\n  <h2>カテゴリ</h2>\n  <ul class="cat-list">{lis}</ul>\n</section>\n'


def render_category(site, cat, items):
    path = f"category/{cat['slug']}/"
    crumb_ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "ホーム", "item": site["base_url"]},
        {"@type": "ListItem", "position": 2, "name": cat["name"], "item": site["base_url"] + path}]}
    body = ('<div class="wrap article-wrap"><nav class="breadcrumb" aria-label="パンくずリスト"><ol>'
            f'<li><a href="../../">ホーム</a></li><li>{e(cat["name"])}</li></ol></nav>'
            f'<h1>{e(cat["name"])}の記事</h1><p>{e(cat.get("description", ""))}</p>\n'
            f'{article_list(items, rel="../../")}</div>')
    return layout(site, title=f"{cat['name']}の記事", description=f"{cat['name']}の記事一覧。{cat.get('description', '')}",
                  rel="../../", path=path, body=body, extra_head=ld(crumb_ld) + "\n")


# The blueprint links use meaningful anchors while retaining the legacy numbered
# anchors (inbound links and the current article TOC use both).
BREW_TOPIC_ANCHORS = {
    "注ぐ速さと抽出時間は別": "brew-pour",
    "粉の細かさで変わる味": "brew-grind",
    "フィルターで変わる口当たり": "brew-filter",
}
BLUEPRINT_TOOLS = (
    ("01", "POUR", "注ぐ", "注ぎ終わりと、落ち切る時間を分けて見る。",
     "M12 47C36 37 64 40 81 56C98 72 77 94 63 82C48 68 65 51 101 47M101 31v45m0 7v4m0 8v4"),
    ("02", "GRIND", "挽く", "粉の細かさを一段変えて、味と流れを比べる。",
     "M21 30h60l-7 23H28zm9 23h42v35H30zm43-22 23-13h13m-67 79-3 4m13-5 2 3m8-4 3 6m19-5 3 2"),
    ("03", "FILTER", "こす", "紙・布・金属、紙を使わないセラミックを知る。",
     "M18 32c0-9 80-9 80 0S18 41 18 32zm0 0 31 49h18l31-49M31 43l23 38m30-38L61 81m-4-40v40m0 6v12"),
)


def render_blueprint_tools(feature):
    items = []
    if feature:
        anchors = set(BREW_TOPIC_ANCHORS[h["heading"]] for h in feature["article"]["sections"]
                      if h["heading"] in BREW_TOPIC_ANCHORS)
        for no, en, label, desc, drawing in BLUEPRINT_TOOLS:
            anchor = f"brew-{en.lower()}"
            if anchor not in anchors:
                continue
            url = f"column/{BREW_FEATURE}/#{anchor}"
            items.append(f"""<li><a href="{url}">
              <span class="tool-meter">{no} / {en}</span>
              <svg viewBox="0 0 120 112" width="120" height="112" aria-hidden="true" focusable="false"><path d="{drawing}"/></svg>
              <span class="tool-label">{label}<span aria-hidden="true">↗</span></span><span class="tool-desc">{desc}</span>
            </a></li>""")
    return "".join(items)


def render_index(site, items):
    ld_site = {"@context": "https://schema.org", "@type": "WebSite", "name": site["site_name"], "url": site["base_url"]}
    feature = next((it for it in items if it["slug"] == BREW_FEATURE), None)
    cta = "#blueprint-workbench" if feature else "#articles"
    cta_label = "淹れ方を選ぶ" if feature else "記事一覧へ"
    tools = render_blueprint_tools(feature)
    spotlight = ""
    if feature:
        spotlight = f"""
<section class="blueprint-workbench" id="blueprint-workbench" aria-labelledby="feature-title">
  <div class="workbench-heading">
    <p class="blueprint-label">01 / COFFEE WORKBENCH</p>
    <h2 id="feature-title">一杯を、<br>ひとつずつ分解する。</h2>
    <p>同じ豆でも、注ぎ方、粉の細かさ、こし方で変わります。次に淹れるとき、気になるところだけ試してみてください。</p>
  </div>
  <ol class="blueprint-tools">{tools}</ol>
  <div class="blueprint-film-link">
    <img src="{EDITORIAL}brew-adjustments.webp" alt="手挽きミルと細かさの違う粉、紙・布・金属のフィルターの生成イラスト" width="1200" height="800" loading="lazy" decoding="async">
    <div>
      <p class="blueprint-label">BREWING NOTES / 20秒の図解</p>
      <h3>タイマーは、どこで止める？</h3>
      <p>注ぎ終わりと、抽出の終わりは別。計り方を短い無音動画と文字で紹介します。</p>
      <a class="text-link" href="column/{BREW_FEATURE}/#brew-studio-title">図と動画で見る <span aria-hidden="true">↗</span></a>
    </div>
  </div>
</section>"""
    body = f"""<section class="blueprint-hero" aria-labelledby="blueprint-title">
  <div class="blueprint-shell blueprint-grid">
    <div class="blueprint-copy">
      <p class="blueprint-label"><span aria-hidden="true">◎</span> BREWING NOTES / FIG. 01</p>
      <h1 id="blueprint-title">一滴の<br>設計図<span>。</span></h1>
      <p class="blueprint-lead">いつもの豆で、もう一杯。<br>注ぎ方・挽き目・フィルターから<br>味の変わり方を見てみよう。</p>
      <a class="blueprint-button" href="{cta}">{cta_label} <span aria-hidden="true">↓</span></a>
    </div>
    <figure class="blueprint-figure">
      <img class="blueprint-source" src="{EDITORIAL}brew-hero.webp" alt="細口ケトルからドリッパーに湯を注いでいる生成イラスト" width="1536" height="1024" fetchpriority="high" decoding="async">
      <span class="blueprint-detail" aria-hidden="true"></span>
      <img class="blueprint-wire" src="{EDITORIAL}drip-blueprint.svg" alt="ドリッパーとカップの断面を表すワイヤーフレーム図" width="780" height="700">
      <figcaption class="blueprint-label">FIG. 01 / 構造の図解・生成イラスト</figcaption>
    </figure>
  </div>
</section>
<div class="blueprint-shell blueprint-paper">
{spotlight}
<section class="blueprint-intro" aria-labelledby="guide-title">
  <p class="blueprint-label">{"02" if feature else "01"} / ABOUT THE GUIDE</p>
  <h2 id="guide-title">家で淹れる一杯のために。</h2>
  <p>家でコーヒーを淹れ始めた人へ。淹れ方、豆と焙煎、器具の基本をまとめるガイドです。</p>
  <p class="small">記事は生成AIで作成し、確認した出典を記事の末尾に載せています。<a href="about.html">記事の作り方</a></p>
</section>
{category_nav(site, items)}<section class="blueprint-index" id="articles">
  <p class="blueprint-label">INDEX / 読みもの</p>
  <h2 id="all-articles">記事一覧</h2>
  {article_list(items)}
</section>
</div>"""
    return layout(site, title=site["site_name"], description=site["description"], rel="", path="", body=body,
                  extra_head=ld(ld_site) + "\n")


def static_page(site, title, path, paragraphs):
    body = ('<div class="wrap article-wrap"><nav class="breadcrumb" aria-label="パンくずリスト"><ol>'
            f'<li><a href="./">ホーム</a></li><li>{e(title)}</li></ol></nav><article class="article">'
            f"<h1>{e(title)}</h1>" + "".join(paragraphs) + "</article></div>")
    return layout(site, title=title, description=f"{site['site_name']}の{title}です。", rel="", path=path, body=body)


def h2(t):
    return f"<h2>{e(t)}</h2>"


def p(t):
    return f"<p>{e(t)}</p>"


def build():
    site = load_site()
    items = load_articles()
    by_slug = {it["slug"]: it for it in items}
    out = {"index.html": render_index(site, items)}
    out["about.html"] = static_page(site, "運営者情報", "about.html", [
        h2("サイトについて"), p(f"{site['site_name']}は、家でコーヒーを淹れる人のための情報サイトです。個人（{site['operator']}）が運営しています。"),
        # 運営者本人が書く紹介文（site.json の operator_profile）。空なら見出しごと出さない
        *([h2("運営者について")] + [p(x) for x in site.get("operator_profile", [])] if site.get("operator_profile") else []),
        h2("記事の作り方"),
        p("記事は生成AI（ChatGPT）で作成します。自動公開の記事は別の生成AI（Claude）が出典を照合して推敲し、個別に出典を確認して編集した記事は、その方法を記事内に記載します。"),
        p("運営者や専門家による実際の試飲・器具のテスト・個別の確認は行っていません。記事内の体験談のような表現は使わない方針です。")])
    out["privacy.html"] = static_page(site, "プライバシーポリシー", "privacy.html", [
        h2("アクセス解析"), p("当サイトでは、利用状況を把握するためにアクセス解析ツールを使う場合があります。収集されるデータは匿名で、個人を特定するものではありません。"),
        h2("広告"), p("当サイトは、第三者のアフィリエイトプログラムを利用する場合があります。広告配信事業者は、Cookieを使って閲覧者の興味に応じた広告を表示することがあります。"),
        h2("改定"), p("本ポリシーは、必要に応じて内容を見直し、このページで公開します。")])
    out["disclaimer.html"] = static_page(site, "免責事項・広告・AI利用について", "disclaimer.html", [
        h2("AIによる記事作成"), p("当サイトの記事は生成AIで作成し、確認した出典を記事ごとに掲載しています。内容の正確性には注意していますが、誤りが含まれる可能性があります。"),
        h2("健康に関する情報"), p("カフェインなど健康に関わる記述は一般的な情報です。体質・持病・妊娠中などの事情がある方は、医師や薬剤師に相談してください。"),
        h2("広告について"), p("当サイトはアフィリエイト広告を利用することがあります。紹介する商品の価格や仕様は変わることがあるため、購入前に販売ページで確認してください。"),
        h2("免責"), p("当サイトの情報を利用したことで生じた損害について、当サイトは責任を負いかねます。")])
    root_path = urlparse(site["base_url"]).path  # 404はどの階層でも表示されるため絶対パスを使う
    out["404.html"] = layout(site, title="ページが見つかりません", description="お探しのページは見つかりませんでした。", rel=root_path,
                             path="404.html", noindex=True,
                             body=f'<div class="wrap article-wrap"><h1>ページが見つかりません</h1><p><a href="{root_path}">トップページへ戻る</a></p></div>')
    for it in items:
        out[f"column/{it['slug']}/index.html"] = render_article(site, it, by_slug)
    groups = group_by_category(site, items)
    for cat, its in groups:
        out[f"category/{cat['slug']}/index.html"] = render_category(site, cat, its)
    urls = [("", items[0]["date"] if items else None), ("about.html", None), ("privacy.html", None), ("disclaimer.html", None)]
    urls += [(f"category/{cat['slug']}/", max(last_modified(it) for it in its)) for cat, its in groups]
    urls += [(f"column/{it['slug']}/", last_modified(it)) for it in items]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, lastmod in urls:
        sm.append(f"  <url><loc>{site['base_url']}{path}</loc>" + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "") + "</url>")
    sm.append("</urlset>")
    out["sitemap.xml"] = "\n".join(sm) + "\n"
    out["robots.txt"] = f"User-agent: *\nAllow: /\n\nSitemap: {site['base_url']}sitemap.xml\n"

    # 記事JSONが消えたページ・記事がなくなったカテゴリを掃除
    keep = {"column": set(by_slug), "category": {cat["slug"] for cat, _ in groups}}
    for top, names in keep.items():
        base = ROOT / top
        if base.exists():
            for d in base.iterdir():
                if d.is_dir() and d.name not in names:
                    for f in d.iterdir():
                        f.unlink()
                    d.rmdir()
    for rel, text in out.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return len(items)


if __name__ == "__main__":
    print(f"built {build()} articles")
