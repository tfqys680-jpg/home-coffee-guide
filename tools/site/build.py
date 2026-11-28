#!/usr/bin/env python3
"""content/articles/*.json と site.json から静的サイト一式を生成する。

生成物: index.html, about.html, privacy.html, disclaimer.html, 404.html,
column/<slug>/index.html, category/<slug>/index.html（記事があるカテゴリのみ）, sitemap.xml, robots.txt
記事の中身は JSON に保存し、HTMLは毎回ここから作り直す（レイアウト変更が全記事に反映される）。
"""
import hashlib
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlparse

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


def asset_url(path, rel=""):
    """Fingerprint changeable entry assets so cached HTML/CSS don't mix releases."""
    digest = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()[:16]
    return f"{rel}{path}?v={digest}"


def layout(site, *, title, description, rel, path, body, page_type="website", extra_head="", noindex=False, image=None, extra_scripts="", body_class=""):
    """rel: ルートへの相対パス（'' か '../../'）。path: サイト内パス（'' や 'column/x/'）。"""
    url = site["base_url"] + path
    img = image or {"url": site["base_url"] + OGP["path"], "width": OGP["width"], "height": OGP["height"]}
    img_size = "".join(f'<meta property="og:image:{k}" content="{img[k]}">\n' for k in ("width", "height") if img.get(k))
    full_title = title if title == site["site_name"] else f"{title}｜{site['site_name']}"
    ga = ""
    amazon_note = ("Amazonのアソシエイトとして、本サイトは適格販売により収入を得ています。"
                   if (site.get("affiliate") or {}).get("amazon_tag") else "")
    if site.get("ga_id"):
        ga = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={site["ga_id"]}"></script>\n'
              f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
              f"gtag('js',new Date());gtag('config','{site['ga_id']}');</script>\n")
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    # Search Console の所有権確認（HTMLタグ方式）。site.json の gsc_verification が空なら出力しない
    body_class_attr = f' class="{e(body_class)}"' if body_class else ""
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
<link rel="stylesheet" href="{asset_url('css/style.css', rel)}">
{extra_head}</head>
<body{body_class_attr}>
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
    <p class="small">本サイトの記事は生成AIで作成し、確認した出典を記事ごとに掲載しています。本サイトはアフィリエイト広告を利用することがあります。{amazon_note}</p>
    <p class="small">&copy; <span class="js-year">2026</span> {e(site['site_name'])}</p>
  </div>
</footer>
<script src="{rel}js/main.js"></script>{extra_scripts}
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
PRESS_GUIDE = "french-press-how-to"
EDITORIAL = "images/editorial/"
ARTICLE_MEDIA = "images/articles/"


def media_of(slug):
    """tools/media/make_media.py が作った画像・動画（images/articles/<slug>/）。なければ None。"""
    m = ROOT / ARTICLE_MEDIA / slug / "media.json"
    if not m.exists():
        return None
    return {"dir": f"{ARTICLE_MEDIA}{slug}/", **json.loads(m.read_text(encoding="utf-8"))}


def cites_of(it):
    return "".join(f"[{c}]" for c in it.get("cite", []))


def eyecatch_alt(a):
    v = a.get("visual") or {}
    dg = v.get("diagram") or {}
    return f"{''.join(v.get('catch', []))}。{plain(dg.get('title', ''))}を示すイラスト"


def thumb(it, rel, eager=False):
    m = media_of(it["slug"])
    if not m:
        return ""
    base = rel + m["dir"]
    load = ' fetchpriority="high"' if eager else ' loading="lazy"'
    return (f'<img class="card-thumb" src="{base}eyecatch-640.webp" srcset="{base}eyecatch-640.webp 640w, {base}eyecatch.webp 1200w" '
            f'sizes="(max-width: 560px) 100vw, 360px" width="640" height="360" alt="{e(eyecatch_alt(it["article"]))}"{load} decoding="async">')


def is_affiliate(site):
    aff = site.get("affiliate") or {}
    return bool(aff.get("amazon_tag") or aff.get("rakuten_affiliate_id"))


def shop_links(site, query):
    """商品の検索結果へのリンク。site.json の affiliate にIDがあればアフィリエイトリンクにする。"""
    aff = site.get("affiliate") or {}
    amazon = "https://www.amazon.co.jp/s?k=" + quote(query) + (f"&tag={quote(aff['amazon_tag'])}" if aff.get("amazon_tag") else "")
    rakuten = f"https://search.rakuten.co.jp/search/mall/{quote(query, safe='')}/"
    if aff.get("rakuten_affiliate_id"):
        rakuten = f"https://hb.afl.rakuten.co.jp/hgc/{quote(aff['rakuten_affiliate_id'], safe='.')}/?pc={quote(rakuten, safe='')}"
    return [("amazon", "Amazonで探す", amazon), ("rakuten", "楽天市場で探す", rakuten)]


def shop_anchor(site, shop, label, url, item_label, placement, cls):
    rel_attr = "sponsored noopener" if is_affiliate(site) else "noopener"
    return (f'<a class="{cls}" href="{e(url)}" rel="{rel_attr}" target="_blank" data-shop="{shop}" '
            f'data-item="{e(item_label)}" data-placement="{placement}">{label}</a>')


def render_products(site, a):
    """記事の条件に合う商品の例（メーカー公式の仕様と出典つき）。順位・価格・使った感想は出さない。"""
    prods = a.get("products") or []
    if not prods:
        return ""
    cards = []
    for p in prods:
        label = f'{p["maker"]} {p["name"]}'
        model = f'<span class="prod-model">{e(p["model"])}</span>' if p.get("model") else ""
        facts = "".join(f"<li>{e(f)}</li>" for f in p["facts"])
        links = "".join(shop_anchor(site, shop, text, url, label, "product", f"shop-btn shop-{shop}")
                        for shop, text, url in shop_links(site, p["query"]))
        src = p["source"]
        cards.append(
            f'<li class="prod"><p class="prod-maker">{e(p["maker"])}</p><p class="prod-name">{e(p["name"])}{model}</p>'
            f'<p class="prod-fit">{inline(p["fit"])}</p><ul class="prod-facts">{facts}</ul>'
            f'<p class="prod-src">仕様の出典：<a href="{e(src["url"])}" rel="noopener">{e(src["title"])}</a>（{jp_date(p["checked"])}確認）</p>'
            f'<p class="shop-links">{links}</p></li>')
    return f'<h3 class="shop-sub">条件に合う商品の例</h3><ul class="prod-list">{"".join(cards)}</ul><h3 class="shop-sub">種類から探す</h3>'


def render_shop(site, a, placement="middle"):
    items = a.get("shopping") or []
    if not items:
        return ""
    pr = '<span class="shop-pr">PR</span>' if is_affiliate(site) else ""
    if placement == "end":
        prod_items = [{"label": f'{p["maker"]} {p["name"]}', "query": p["query"]} for p in a.get("products") or []]
        items = prod_items + items
        lis = "".join(
            f'<li><span class="shop-mini-label">{e(plain(it["label"]))}</span><span class="shop-mini-links">'
            + "".join(shop_anchor(site, shop, label, url, plain(it["label"]), "end", "shop-mini-link")
                      for shop, label, url in shop_links(site, it["query"])) + "</span></li>" for it in items)
        return f'<aside class="shop-mini" aria-label="この記事の道具を探す">{pr}<p class="shop-mini-head">この記事の道具を探す</p><ul>{lis}</ul></aside>'
    lis = "".join(
        f'<li class="shop-item"><p class="shop-name">{e(plain(it["label"]))}</p><p class="shop-reason">{inline(it["reason"])}</p>'
        '<p class="shop-links">' + "".join(shop_anchor(site, shop, label, url, plain(it["label"]), placement, f"shop-btn shop-{shop}")
                                           for shop, label, url in shop_links(site, it["query"])) + "</p></li>" for it in items)
    fine_products = ("商品の例は、記事の条件に合うものをメーカーの公開情報で確かめて載せています。"
                     if a.get("products") else "")
    return (f'<aside class="shop" id="shop" aria-labelledby="shop-title">{pr}<h2 id="shop-title">この記事の条件で道具を探す</h2>'
            f'{render_products(site, a)}<ul class="shop-list">{lis}</ul>'
            f'<p class="shop-fine">{fine_products}ボタンを押すと、各ショップの検索結果が新しいタブで開きます。価格や仕様は販売ページで確認してください。'
            '当サイトは商品を試したり、順位を付けたりしていません。</p></aside>')


def render_diagram(a):
    v = a.get("visual") or {}
    dg = v.get("diagram")
    if not dg:
        return ""
    lis = []
    for i, it in enumerate(dg["items"]):
        detail = inline(f'{it["detail"]} {cites_of(it)}'.strip())
        note = f'<span class="dg-note">{inline(it["note"])}</span>' if it.get("note") else ""
        mark = f'<span class="dg-mark" aria-hidden="true">{i + 1 if dg["type"] == "steps" else ""}</span>'
        lis.append(f'<li style="--i:{i}">{mark}<strong class="dg-label">{e(plain(it["label"]))}</strong>'
                   f'<span class="dg-detail">{detail}</span>{note}</li>')
    cap = f'<figcaption>{inline(dg["caption"])}</figcaption>' if dg.get("caption") else ""
    return (f'<figure class="diagram dg-{e(dg["type"])}" id="diagram" aria-labelledby="diagram-title" style="--n:{len(dg["items"])}">'
            f'<p class="dg-title" id="diagram-title">{e(plain(dg["title"]))}</p><ol class="dg-items">{"".join(lis)}</ol>{cap}</figure>')


def render_explainer(a, media, rel):
    v = a.get("visual") or {}
    dg = v.get("diagram")
    if not (media and dg and "explainer.mp4" in media.get("files", [])):
        return ""
    base = rel + media["dir"]
    secs = round(media.get("video_seconds", 0))
    steps = "".join(f'<li><strong>{e(plain(it["label"]))}</strong>：{inline((it["detail"] + " " + cites_of(it)).strip())}'
                    + (f'（{inline(it["note"])}）' if it.get("note") else "") + "</li>" for it in dg["items"])
    return f"""<section class="explainer" id="explainer" aria-labelledby="explainer-title">
<h2 id="explainer-title">動画で見る：{e(plain(dg["title"]))}</h2>
<figure class="explainer-film">
<video controls muted playsinline preload="none" width="1280" height="720" poster="{base}explainer-poster.webp" data-play-in-view aria-label="{e(plain(dg["title"]))}の図解動画（音声なし）">
<source src="{base}explainer.mp4" type="video/mp4">このブラウザーでは動画を再生できません。下の文字版をお読みください。
</video>
<figcaption>音声のない約{secs}秒の図解です。内容は下の文字版と同じです。</figcaption>
</figure>
<details class="faq transcript"><summary>動画を文章で読む</summary><ol>{steps}</ol></details>
</section>"""


def render_next(items, rel, current):
    """記事ページの「次に読む」。リンクは記事どうしの相対パス（../<slug>/）にする。"""
    if not items:
        return ""
    lis = "".join(f'<li><a href="../{it["slug"]}/">{thumb(it, rel)}<span class="next-title">{e(it["article"]["title"])}</span></a></li>'
                  for it in items if it["slug"] != current)
    return f'<section class="next-read" aria-labelledby="next-read-title"><h2 id="next-read-title">次に読む</h2><ul class="next-cards">{lis}</ul></section>'


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
    media = media_of(slug)
    media_images = [site["base_url"] + media["dir"] + f for f in ("og.jpg", "eyecatch.webp")] if media else []
    article_ld["image"] = [site["base_url"] + ph["src"] for ph in photos] + media_images or [site["base_url"] + OGP["path"]]
    og_image = ({"url": site["base_url"] + photos[0]["src"], "width": photos[0].get("width"), "height": photos[0].get("height")}
                if photos else {"url": site["base_url"] + media["dir"] + "og.jpg", "width": 1200, "height": 630} if media else None)
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
    diagram_html = render_diagram(a)
    explainer_html = render_explainer(a, media, "../../")
    n_sec = len(a["sections"])
    video_after = 1 if n_sec > 2 else n_sec
    shop_after = max(video_after + 1, min(n_sec, round(n_sec * 0.6)))
    extra_toc = (f'<li><a href="#diagram">図で見る</a></li>' if diagram_html else "")
    toc = extra_toc + toc
    def article_section(i, section):
        heading = plain(section["heading"])
        anchor = BREW_TOPIC_ANCHORS.get(heading) if slug == BREW_FEATURE else None
        content = "\n".join(render_block(b) for b in section.get("blocks", []))
        if slug == PRESS_GUIDE and heading == "粉を入れ、待ってからゆっくり押す":
            image = asset_url(f"{EDITORIAL}french-press-steps.svg", "../../")
            content = (f'<figure class="brew-overview press-steps"><img src="{image}" '
                       'alt="粉を湯に浸し、金属網を上げて待ち、最後にゆっくり押し下げる三工程の線画" '
                       'width="720" height="230" loading="lazy" decoding="async">'
                       '<figcaption>粉を湯に浸す → 網を上げて待つ → 最後にゆっくり押す。</figcaption></figure>\n'
                       + content)
        # Keep #secN on the heading for older direct links.
        markup = f'<h2 id="sec{i}">{e(heading)}</h2>\n{content}'
        return f'<section id="{anchor}" aria-labelledby="sec{i}">{markup}</section>' if anchor else markup

    parts = []
    for i, section in enumerate(a["sections"], 1):
        parts.append(article_section(i, section))
        if i == video_after and explainer_html:
            parts.append(explainer_html)
        if i == shop_after:
            parts.append(render_shop(site, a))
    sections = "\n".join(parts)
    related = [by_slug[r] for r in item.get("related", []) if r in by_slug and r != slug]
    others = [it for it in by_slug.values() if it["slug"] != slug and it not in related]
    next_items = (related + sorted(others, key=lambda it: it["date"], reverse=True))[:3]
    related_html = render_next(next_items, "../../", slug)
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
    eyecatch_html = ""
    if media:
        base = "../../" + media["dir"]
        eyecatch_html = (f'<figure class="eyecatch"><img src="{base}eyecatch.webp" srcset="{base}eyecatch-640.webp 640w, {base}eyecatch.webp 1200w" '
                         f'sizes="(max-width: 760px) 100vw, 720px" width="1200" height="675" alt="{e(eyecatch_alt(a))}" fetchpriority="high" decoding="async"></figure>')
    pr_note = ('<p class="pr-note">この記事には広告（アフィリエイトリンク）を含みます。</p>'
               if a.get("shopping") and is_affiliate(site) else "")
    body = f"""<div class="wrap article-wrap">
<nav class="breadcrumb" aria-label="パンくずリスト"><ol>{"".join(f'<li><a href="{h}">{e(n)}</a></li>' if h else f'<li>{e(n)}</li>' for n, _, h in crumbs)}</ol></nav>
<article class="article">
<h1>{e(a["title"])}</h1>
<p class="meta">公開日：{jp_date(date)}　最終更新日：{jp_date(modified)}　作成：{e(site["author"])}（生成AI）{byline_extra}</p>
{eyecatch_html}{pr_note}
<div class="ai-note">{e(review_note)}{e(notice)}{human}</div>{operator_html}
<div class="summary"><p class="summary-label">結論</p><p>{inline(a["conclusion"])}</p></div>
<p>{inline(a["lead"])}</p>
{diagram_html}
<h2 id="can-do">この記事でわかること</h2><ul class="check">{"".join(f"<li>{inline(x)}</li>" for x in a["can_do"])}</ul>
<nav class="toc" aria-label="目次"><p class="toc-label">目次</p><ol>{toc}</ol></nav>
{feature_html}
{sections}
<h2 id="checklist">チェックリスト</h2><ul class="check">{"".join(f"<li>{inline(x)}</li>" for x in a["checklist"])}</ul>
<h2 id="faq">よくある質問</h2>
{"".join(f'<details class="faq"><summary>{e(plain(f["q"]))}</summary><p>{e(plain(f["a"]))}</p></details>' for f in a["faq"])}
<h2 id="next">次の一歩</h2>
<p>{inline(a["next_step"])}</p>
{render_shop(site, a, "end")}
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


def article_list(items, rel="", eager_first=False):
    if not items:
        return '<p class="empty">最初の記事を準備しています。公開までしばらくお待ちください。</p>'
    return '<ul class="cards has-thumbs">' + "".join(
        f'<li><a href="{rel}column/{it["slug"]}/">{thumb(it, rel, eager=(n == 0 and eager_first))}<span class="card-title">{e(it["article"]["title"])}</span>'
        f'<span class="card-desc">{e(it["article"]["description"])}</span>'
        f'<span class="card-date">{jp_date(it["date"])}</span></a></li>' for n, it in enumerate(items)) + "</ul>"


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
EDITORIAL_TOPICS = (
    ("pour", "お湯の注ぎ方", "注ぎ終わりと、落ち切る時間を分けて見る。"),
    ("grind", "豆の挽き方", "粉の細かさを一段変えて、味と流れを比べる。"),
    ("filter", "フィルターの選び方", "紙・布・金属、紙を使わないセラミックの違いを知る。"),
)


def render_index(site, items):
    ld_site = {"@context": "https://schema.org", "@type": "WebSite", "name": site["site_name"], "url": site["base_url"]}
    feature = next((it for it in items if it["slug"] == BREW_FEATURE), None)
    spotlight = ""
    if feature:
        article_url = f"column/{BREW_FEATURE}/"
        anchors = {BREW_TOPIC_ANCHORS[h["heading"]] for h in feature["article"]["sections"]
                   if h["heading"] in BREW_TOPIC_ANCHORS}
        topics = "".join(
            f"""<li><a href="{article_url}#brew-{slug}">
      <span class="ed-topic">{label}</span><span class="ed-desc">{desc}</span>
      <span class="ed-arrow" aria-hidden="true">→</span>
    </a></li>""" for slug, label, desc in EDITORIAL_TOPICS if f"brew-{slug}" in anchors)
        topic_index = ""
        if topics:
            topic_index = f"""
<section class="ed-section ed-toc" id="blueprint-workbench" aria-labelledby="feature-title">
  <div class="ed-section-heading">
    <h2 id="feature-title">淹れ方を読む</h2>
  </div>
  <ol class="ed-topics">{topics}</ol>
</section>"""
        spotlight = f"""{topic_index}
<section class="ed-section ed-extraction" id="extraction" aria-labelledby="extraction-title">
  <figure class="blueprint-figure">
    <div class="ed-figure-plate">
      <span class="blueprint-render" aria-hidden="true"></span>
      <img class="blueprint-wire" src="{EDITORIAL}drip-blueprint.svg" alt="ドリッパーとカップの立体構造を線で表した図" width="780" height="700" loading="lazy" decoding="async">
    </div>
    <figcaption>ドリッパーとカップの構造（線画）</figcaption>
  </figure>
  <div class="ed-section-heading">
    <h2 id="extraction-title">抽出を図で見る</h2>
    <p>お湯を注ぎ終えても、抽出はまだ続きます。タイマーをどこで止めるか、図と短い無音動画で確認できます。</p>
    <a class="ed-inline-link" href="{article_url}#brew-studio-title">図と動画で見る <span aria-hidden="true">↗</span></a>
  </div>
</section>"""
    body = f"""<div class="ed-wrap">
<section class="ed-hero" aria-labelledby="editorial-title">
  <h1 id="editorial-title"><span>家で淹れる</span><span>コーヒー</span></h1>
  <svg class="ed-drawing" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 510 280" width="510" height="280" aria-hidden="true" focusable="false">
    <g stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">
      <path stroke-width="2" d="M114 118c10 72 55 113 134 113 76 0 123-41 135-113m-270 1c0-26 65-45 136-45 70 0 134 19 134 45s-64 45-134 45-136-19-136-45Zm270 2c28-14 53-6 53 16 0 22-26 44-67 46m-271 33c-41 7-63 18-63 30 0 19 88 35 211 35 128 0 218-16 218-36 0-10-23-20-61-27"/>
      <path stroke-width=".9" d="M138 135c23-17 66-28 112-28 49 0 86 12 112 30m25-5c23-9 35-4 35 7 0 12-15 25-46 32M172 248c30 4 53 4 75 4 30 0 61-2 90-7"/>
      <path stroke-width="1.3" d="M285 24c-13 13-29 30-33 44-4 13 8 18 14 9 4-6 3-14-1-21m-22 32c-1 7-3 14-9 21"/>
    </g>
  </svg>
  <p>お湯の注ぎ方、豆の挽き目、フィルター。<br>家で一杯を淹れるときの手引きです。</p>
</section>
<section class="ed-section ed-articles" id="articles" aria-labelledby="all-articles">
  <div class="ed-section-heading">
    <h2 id="all-articles">記事一覧</h2>
  </div>
  <div>{article_list(items)}</div>
</section>
{spotlight}
{category_nav(site, items)}
<section class="ed-section ed-about" aria-labelledby="guide-title">
  <div class="ed-section-heading">
    <h2 id="guide-title">このガイドについて</h2>
  </div>
  <div>
    <p>家でコーヒーを淹れ始めた人に向けて、淹れ方、豆と焙煎、器具の基本をまとめています。</p>
    <p class="small">記事は生成AIで作成し、確認した出典を記事の末尾に載せています。</p>
    <a class="ed-inline-link" href="about.html">記事の作り方 <span aria-hidden="true">↗</span></a>
  </div>
</section>
</div>"""
    return layout(site, title=site["site_name"], description=site["description"], rel="", path="", body=body,
                  extra_head=ld(ld_site) + "\n", body_class="home-editorial",
                  extra_scripts=f'\n<script type="module" src="{asset_url("js/blueprint-motion.js")}"></script>' if feature else "")


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
        h2("アクセス解析"), p("当サイトでは、利用状況を把握するためにアクセス解析ツール（Google アナリティクス）を使う場合があります。ページの閲覧時間や、記事内のリンク・動画の操作などを Cookie を使って匿名で集計し、個人を特定する情報は集めません。"),
        h2("広告"), p("当サイトは、第三者のアフィリエイトプログラムを利用する場合があります。広告配信事業者は、Cookieを使って閲覧者の興味に応じた広告を表示することがあります。"),
        h2("改定"), p("本ポリシーは、必要に応じて内容を見直し、このページで公開します。")])
    out["disclaimer.html"] = static_page(site, "免責事項・広告・AI利用について", "disclaimer.html", [
        h2("AIによる記事作成"), p("当サイトの記事は生成AIで作成し、確認した出典を記事ごとに掲載しています。内容の正確性には注意していますが、誤りが含まれる可能性があります。"),
        h2("健康に関する情報"), p("カフェインなど健康に関わる記述は一般的な情報です。体質・持病・妊娠中などの事情がある方は、医師や薬剤師に相談してください。"),
        h2("広告について"), p("当サイトはアフィリエイト広告を利用することがあります。記事内の「Amazonで探す」「楽天市場で探す」は各ショップの検索結果へのリンクです。「条件に合う商品の例」は、記事で説明した条件に合うものを、メーカーの公開情報で仕様を確かめて載せています。当サイトは商品を試したり、順位を付けたりしていません。価格や仕様は変わることがあるため、購入前に販売ページで確認してください。"),
        *([p("Amazonのアソシエイトとして、当サイトは適格販売により収入を得ています。")] if (site.get("affiliate") or {}).get("amazon_tag") else []),
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
