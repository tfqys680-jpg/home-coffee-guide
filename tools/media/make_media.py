#!/usr/bin/env python3
"""記事ごとのアイキャッチ・OGP画像・図解動画を、記事JSONの visual から作る（Pillow + ffmpeg）。

出力（images/articles/<slug>/）:
  eyecatch.webp       1200x675  記事の先頭・カードのサムネイル
  eyecatch-640.webp    640x360  カード用の小さい版（srcset）
  og.jpg              1200x630  SNS共有用
  explainer.mp4       1280x720  無音の図解動画（図解の項目を順に見せる）
  explainer-poster.webp         動画の再生前に表示する画像
  media.json                    どの visual から作ったか（build と check が古い画像を検出する）

使い方:
  python3 tools/media/make_media.py <slug> [<slug> ...]
  python3 tools/media/make_media.py --all
  python3 tools/media/make_media.py --stale     # visual が変わった記事・画像がない記事だけ作り直す

描くのは記事の図解の項目（出典で確かめた内容）と器具のイラストだけ。人物・ブランド・商品は描かない。
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(os.environ.get("SITE_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_spec import GENERATOR_VERSION, MOTIFS, visual_hash  # noqa: E402,F401

OUT_DIR = "images/articles"

INK = "#2A211C"
MUTED = "#5E544C"
WHITE = "#FFFFFF"
# 生豆から深煎りまでの5色。どの画像・動画にも下端に入る（サイトの目印）
ROAST = ("#B9C08A", "#C99A62", "#9A6440", "#6A4130", "#3B2620")
PALETTES = {
    "brew": {"bg": "#E3ECEA", "stage": "#CFDFDB", "accent": "#2F6F73"},
    "beans": {"bg": "#F0E6D8", "stage": "#E3D0B9", "accent": "#8A5A3C"},
    "storage": {"bg": "#E5EBF0", "stage": "#D1DBE5", "accent": "#45607A"},
    "tools": {"bg": "#EBE9E1", "stage": "#DAD6C9", "accent": "#5B5A4A"},
    "caffeine": {"bg": "#EEE6EA", "stage": "#DFD0D8", "accent": "#7A4B5E"},
}
WATER = "#3F8A90"
COFFEE = "#5B3626"
S = 2  # 2倍で描いて縮小し、線をなめらかにする


class Draw(ImageDraw.ImageDraw):
    """線幅に小数を渡しても描けるようにする（座標計算を読みやすく保つため）。"""

    def _w(self, kw):
        if "width" in kw:
            kw["width"] = max(1, int(round(kw["width"])))
        return kw

    def line(self, xy, *a, **kw):
        return super().line(xy, *a, **self._w(kw))

    def ellipse(self, xy, *a, **kw):
        return super().ellipse(xy, *a, **self._w(kw))

    def polygon(self, xy, *a, **kw):
        return super().polygon(xy, *a, **self._w(kw))

    def arc(self, xy, *a, **kw):
        return super().arc(xy, *a, **self._w(kw))

    def chord(self, xy, *a, **kw):
        return super().chord(xy, *a, **self._w(kw))

    def rectangle(self, xy, *a, **kw):
        return super().rectangle(xy, *a, **self._w(kw))

    def rounded_rectangle(self, xy, *a, **kw):
        return super().rounded_rectangle(xy, *a, **self._w(kw))


# ---------------------------------------------------------------- fonts

def _fc(pattern):
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}|%{index}", pattern], capture_output=True, text=True, timeout=10).stdout
        path, index = out.split("|")
        if path and Path(path).exists():
            return path, int(index or 0)
    except Exception:  # noqa: BLE001
        pass
    return None


@lru_cache(maxsize=None)
def font(kind, size):
    """kind: serif（見出し）/ sans（本文）/ sans-bold。日本語のフォントが見つからなければ止める。"""
    pattern = {"serif": "Noto Serif CJK JP:style=Bold", "sans": "Noto Sans CJK JP:style=Regular",
               "sans-bold": "Noto Sans CJK JP:style=Bold"}[kind]
    found = _fc(pattern)
    if not found or "CJK" not in found[0]:
        raise SystemExit("日本語フォント（fonts-noto-cjk）が見つかりません。apt-get install fonts-noto-cjk")
    return ImageFont.truetype(found[0], size, index=found[1])


def text_w(draw, text, f):
    return draw.textlength(text, font=f)


# ---------------------------------------------------------------- spec helpers

def load_item(slug):
    return json.loads((ROOT / "content/articles" / f"{slug}.json").read_text(encoding="utf-8"))


def palette(item):
    return PALETTES.get(item["article"].get("category"), PALETTES["tools"])


def category_name(item):
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    for c in site.get("categories", []):
        if c["slug"] == item["article"].get("category"):
            return c["name"]
    return ""


def strip_cites(t):
    import re
    return re.sub(r"\s*\[\d+\]", "", str(t)).strip()


def short(t, n):
    t = strip_cites(t)
    return t if len(t) <= n else t[: n - 1] + "…"


# ---------------------------------------------------------------- drawing primitives (S倍の座標で受け取る)

def bezier(pts, steps=24):
    """2次ベジェ曲線の点列。"""
    (x0, y0), (x1, y1), (x2, y2) = pts
    out = []
    for i in range(steps + 1):
        t = i / steps
        out.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * x1 + t * t * x2, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * y1 + t * t * y2))
    return out


def rr(d, box, r, fill=None, outline=INK, width=6):
    d.rounded_rectangle([int(v) for v in box], radius=int(r), fill=fill, outline=outline, width=int(width))


def bean(img, cx, cy, size, angle, color=COFFEE):
    """コーヒー豆1粒（楕円＋中央の溝）。"""
    w, h = int(size * 1.0), int(size * 0.72)
    pad = int(size * 0.2)
    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ld = Draw(layer)
    ld.ellipse([pad, pad, pad + w, pad + h], fill=color, outline=INK, width=max(2, int(size * 0.06)))
    cx0, cy0 = pad + w / 2, pad + h / 2
    pts = [(cx0 - w * 0.36 + i * w * 0.72 / 12, cy0 + math.sin(i / 12 * math.pi * 2) * h * 0.08) for i in range(13)]
    ld.line(pts, fill=INK, width=max(2, int(size * 0.05)), joint="curve")
    layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)))


def motif_mill(img, d, x, y, w, h, pal):
    lw = 7 * S
    bx0, bx1 = x + w * 0.22, x + w * 0.78
    by0, by1 = y + h * 0.46, y + h * 0.95
    rr(d, (bx0, by0, bx1, by1), 18 * S, fill="#B98057", width=lw)
    rr(d, (bx0 + w * 0.1, by0 + h * 0.2, bx1 - w * 0.1, by1 - h * 0.08), 10 * S, fill="#A26D47", width=lw * 0.7)
    d.ellipse([x + w * 0.47, by0 + h * 0.31, x + w * 0.53, by0 + h * 0.35], fill=INK)
    # 豆を入れるホッパー
    d.polygon([(x + w * 0.26, y + h * 0.30), (x + w * 0.74, y + h * 0.30), (x + w * 0.66, by0), (x + w * 0.34, by0)],
              fill="#CFCBC2", outline=INK, width=lw)
    d.ellipse([x + w * 0.24, y + h * 0.26, x + w * 0.76, y + h * 0.34], fill="#E6E3DC", outline=INK, width=lw)
    for i, (bxp, byp, a) in enumerate(((0.38, 0.295, 20), (0.5, 0.285, -15), (0.61, 0.298, 40))):
        bean(img, x + w * bxp, y + h * byp, w * 0.1, a)
    # ハンドル
    d.line([(x + w * 0.5, y + h * 0.27), (x + w * 0.5, y + h * 0.16)], fill=INK, width=lw)
    d.line([(x + w * 0.5, y + h * 0.16), (x + w * 0.86, y + h * 0.12)], fill=INK, width=lw)
    d.ellipse([x + w * 0.82, y + h * 0.02, x + w * 0.94, y + h * 0.13], fill="#B98057", outline=INK, width=lw)
    d.ellipse([x + w * 0.46, y + h * 0.13, x + w * 0.54, y + h * 0.19], fill=pal["accent"], outline=INK, width=lw * 0.6)


def motif_dripper(img, d, x, y, w, h, pal):
    lw = 7 * S
    # サーバー（ガラスの容器）
    sx0, sx1, sy0, sy1 = x + w * 0.22, x + w * 0.70, y + h * 0.58, y + h * 0.96
    d.arc([sx1 - w * 0.08, sy0 + h * 0.06, sx1 + w * 0.14, sy0 + h * 0.28], 270, 90, fill=INK, width=lw)
    rr(d, (sx0, sy0, sx1, sy1), 30 * S, fill="#F4F7F6", width=lw)
    d.rounded_rectangle([sx0 + lw, sy0 + (sy1 - sy0) * 0.48, sx1 - lw, sy1 - lw], radius=24 * S, fill=COFFEE)
    # ドリッパー（円すい）
    cx = (sx0 + sx1) / 2
    top, bot = y + h * 0.24, y + h * 0.53
    d.polygon([(cx - w * 0.3, top), (cx + w * 0.3, top), (cx + w * 0.08, bot), (cx - w * 0.08, bot)], fill=WHITE, outline=INK, width=lw)
    for k in (-0.16, -0.05, 0.05, 0.16):
        d.line([(cx + w * k * 1.6, top + h * 0.03), (cx + w * k * 0.45, bot - h * 0.02)], fill="#9E968C", width=int(lw * 0.45))
    rr(d, (cx - w * 0.2, bot, cx + w * 0.2, bot + h * 0.05), 6 * S, fill=WHITE, width=lw)
    d.ellipse([cx - w * 0.27, top - h * 0.03, cx + w * 0.27, top + h * 0.04], fill="#7A4A33", outline=INK, width=lw)
    # 注ぐお湯と、細口ケトルの注ぎ口
    tip = (cx + w * 0.03, y + h * 0.07)
    d.line([tip, (tip[0], top)], fill=WATER, width=int(lw * 1.1))
    spout = bezier([(cx + w * 0.40, y + h * 0.36), (cx + w * 0.24, y + h * -0.04), tip])
    d.line(spout, fill=INK, width=int(lw * 1.6), joint="curve")
    d.ellipse([tip[0] - lw, tip[1] - lw, tip[0] + lw, tip[1] + lw], fill=INK)
    kx0, kx1, ky0, ky1 = cx + w * 0.38, cx + w * 0.66, y + h * 0.16, y + h * 0.42
    d.arc([kx1 - w * 0.06, ky0 + h * 0.03, kx1 + w * 0.08, ky1 - h * 0.03], 270, 90, fill=INK, width=int(lw * 1.4))
    d.polygon([(kx0 + w * 0.04, ky0), (kx1 - w * 0.04, ky0), (kx1, ky1), (kx0, ky1)], fill="#C9C6BE", outline=INK, width=lw)
    d.ellipse([kx0 + w * 0.1, ky0 - h * 0.035, kx1 - w * 0.1, ky0 + h * 0.01], fill="#B9B6AF", outline=INK, width=lw)


def motif_press(img, d, x, y, w, h, pal):
    lw = 7 * S
    gx0, gx1, gy0, gy1 = x + w * 0.28, x + w * 0.68, y + h * 0.26, y + h * 0.94
    d.arc([gx1 - w * 0.06, gy0 + h * 0.12, gx1 + w * 0.2, gy0 + h * 0.5], 270, 90, fill=INK, width=int(lw * 1.6))
    rr(d, (gx0, gy0, gx1, gy1), 14 * S, fill="#F4F7F6", width=lw)
    liquid_top = gy0 + (gy1 - gy0) * 0.36
    d.rounded_rectangle([gx0 + lw, liquid_top, gx1 - lw, gy1 - lw], radius=10 * S, fill=COFFEE)
    d.rectangle([gx0 + lw, liquid_top, gx1 - lw, liquid_top + h * 0.035], fill="#B88A5E")
    # 金属網とロッド
    mesh_y = gy0 + (gy1 - gy0) * 0.22
    d.line([(gx0 + lw, mesh_y), (gx1 - lw, mesh_y)], fill="#7D7A74", width=int(lw * 1.3))
    for i in range(1, 8):
        xx = gx0 + (gx1 - gx0) * i / 8
        d.line([(xx, mesh_y - 4 * S), (xx, mesh_y + 4 * S)], fill="#5F5C57", width=int(lw * 0.4))
    cx = (gx0 + gx1) / 2
    rr(d, (gx0 - w * 0.03, gy0 - h * 0.06, gx1 + w * 0.03, gy0 + h * 0.015), 10 * S, fill="#B9B6AF", width=lw)
    d.line([(cx, mesh_y), (cx, y + h * 0.08)], fill=INK, width=lw)
    d.ellipse([cx - w * 0.06, y + h * 0.01, cx + w * 0.06, y + h * 0.11], fill=pal["accent"], outline=INK, width=lw)
    rr(d, (gx0 - w * 0.04, gy1 - h * 0.02, gx1 + w * 0.04, gy1 + h * 0.03), 8 * S, fill="#B9B6AF", width=lw)


def motif_canister(img, d, x, y, w, h, pal):
    lw = 7 * S
    cx0, cx1, cy0, cy1 = x + w * 0.24, x + w * 0.72, y + h * 0.2, y + h * 0.9
    rr(d, (cx0, cy0, cx1, cy1), 26 * S, fill=WHITE, width=lw)
    rr(d, (cx0 - w * 0.02, cy0 - h * 0.08, cx1 + w * 0.02, cy0 + h * 0.06), 16 * S, fill=pal["accent"], width=lw)
    rr(d, (x + w * 0.42, cy0 - h * 0.13, x + w * 0.54, cy0 - h * 0.075), 6 * S, fill=pal["accent"], width=lw)
    ly0, ly1 = cy0 + h * 0.22, cy0 + h * 0.42
    d.rectangle([cx0 + lw, ly0, cx1 - lw, ly1], fill=pal["stage"])
    for k in (0.3, 0.5, 0.7):
        yy = ly0 + (ly1 - ly0) * k
        d.line([(cx0 + w * 0.07, yy), (cx0 + w * (0.07 + 0.34 - 0.12 * k), yy)], fill=INK, width=int(lw * 0.5))
    for bxp, byp, a in ((0.78, 0.88, 30), (0.88, 0.82, -20), (0.83, 0.74, 70), (0.14, 0.88, -35)):
        bean(img, x + w * bxp, y + h * byp, w * 0.11, a)


def motif_beans(img, d, x, y, w, h, pal):
    import random
    rnd = random.Random(7)
    for i in range(14):
        a = rnd.uniform(0, 2 * math.pi)
        r = rnd.uniform(0, 0.32)
        bean(img, x + w * (0.5 + r * math.cos(a)), y + h * (0.55 + r * math.sin(a)), w * rnd.uniform(0.14, 0.19),
             rnd.uniform(-80, 80), ROAST[2 + i % 3])


def motif_kettle(img, d, x, y, w, h, pal):
    lw = 7 * S
    d.polygon([(x + w * 0.3, y + h * 0.36), (x + w * 0.7, y + h * 0.36), (x + w * 0.78, y + h * 0.9), (x + w * 0.22, y + h * 0.9)],
              fill="#C9C6BE", outline=INK, width=lw)
    rr(d, (x + w * 0.36, y + h * 0.28, x + w * 0.64, y + h * 0.37), 10 * S, fill="#B9B6AF", width=lw)
    d.ellipse([x + w * 0.46, y + h * 0.22, x + w * 0.54, y + h * 0.29], fill=pal["accent"], outline=INK, width=lw)
    d.arc([x + w * 0.62, y + h * 0.38, x + w * 0.96, y + h * 0.8], 270, 90, fill=INK, width=int(lw * 1.6))
    d.line([(x + w * 0.26, y + h * 0.8), (x + w * 0.12, y + h * 0.5), (x + w * 0.04, y + h * 0.3)], fill=INK, width=int(lw * 1.5), joint="curve")
    d.line([(x + w * 0.04, y + h * 0.3), (x + w * 0.04, y + h * 0.5)], fill=WATER, width=int(lw * 1.0))


def motif_cup(img, d, x, y, w, h, pal):
    lw = 7 * S
    d.ellipse([x + w * 0.08, y + h * 0.78, x + w * 0.92, y + h * 0.96], fill=WHITE, outline=INK, width=lw)
    d.arc([x + w * 0.66, y + h * 0.4, x + w * 0.92, y + h * 0.7], 270, 90, fill=INK, width=int(lw * 1.6))
    d.chord([x + w * 0.18, y + h * 0.2, x + w * 0.82, y + h * 0.9], 0, 180, fill=WHITE, outline=INK, width=lw)
    d.ellipse([x + w * 0.18, y + h * 0.48, x + w * 0.82, y + h * 0.62], fill=COFFEE, outline=INK, width=lw)
    for k in (0.4, 0.55):
        d.line([(x + w * k, y + h * 0.4), (x + w * (k + 0.04), y + h * 0.26), (x + w * k, y + h * 0.12)], fill="#9E968C",
               width=int(lw * 0.6), joint="curve")


MOTIF_FN = {"mill": motif_mill, "dripper": motif_dripper, "press": motif_press, "canister": motif_canister,
            "beans": motif_beans, "kettle": motif_kettle, "cup": motif_cup}


def roast_ribbon(d, x0, y0, x1, y1, progress=None):
    """下端の焙煎色の帯。progress（0〜1）を渡すと、進んだ分だけ色が付く（動画の進行表示）。"""
    n = len(ROAST)
    seg = (x1 - x0) / n
    for i, c in enumerate(ROAST):
        sx0, sx1 = x0 + seg * i, x0 + seg * (i + 1)
        if progress is None:
            d.rectangle([sx0, y0, sx1, y1], fill=c)
        else:
            d.rectangle([sx0, y0, sx1, y1], fill="#D9D4CC")
            fill_to = min(sx1, x0 + (x1 - x0) * progress)
            if fill_to > sx0:
                d.rectangle([sx0, y0, fill_to, y1], fill=c)


def glyph(d, diagram, x, y, w, pal, active=None, scale=1.0):
    """図解の形を小さく示す（段階・手順・比較）。active で強調する項目を選べる。"""
    items = diagram.get("items", [])
    n = len(items)
    t = diagram.get("type")
    slot = w / max(1, n)
    labels = [short(it["label"], 7) for it in items]
    size = int(22 * S * scale)
    while size > 13 * S * scale and max(text_w(d, x, font("sans-bold", size)) for x in labels) > slot * 0.9:
        size -= S
    lab = font("sans-bold", size)
    if t == "scale":
        step = w / n
        maxr = min(step * 0.32, 44 * S * scale)
        for i, it in enumerate(items):
            cx = x + step * (i + 0.5)
            r = maxr * (1 - i * 0.7 / max(1, n - 1))
            on = active is None or active == i
            d.ellipse([cx - r, y + maxr - r, cx + r, y + maxr + r], fill=(COFFEE if on else "#CFC7BC"),
                      outline=INK if on else "#B5ADA2", width=int(3 * S * scale))
            label = labels[i]
            d.text((cx - text_w(d, label, lab) / 2, y + maxr * 2 + 12 * S * scale), label, font=lab,
                   fill=INK if on else "#8F877D")
    elif t == "steps":
        step = w / n
        r = 26 * S * scale
        d.line([(x + step * 0.5, y + r), (x + step * (n - 0.5), y + r)], fill=INK, width=int(4 * S * scale))
        num = font("sans-bold", int(26 * S * scale))
        for i, it in enumerate(items):
            cx = x + step * (i + 0.5)
            on = active is None or active == i
            d.ellipse([cx - r, y, cx + r, y + 2 * r], fill=(pal["accent"] if on else "#CFC7BC"), outline=INK, width=int(3 * S * scale))
            s = str(i + 1)
            d.text((cx - text_w(d, s, num) / 2, y + r - 18 * S * scale), s, font=num, fill=WHITE)
            label = labels[i]
            d.text((cx - text_w(d, label, lab) / 2, y + 2 * r + 12 * S * scale), label, font=lab, fill=INK if on else "#8F877D")
    else:  # compare
        gap = 12 * S * scale
        tw = (w - gap * (n - 1)) / n
        for i, it in enumerate(items):
            tx = x + i * (tw + gap)
            on = active is None or active == i
            rr(d, (tx, y, tx + tw, y + 84 * S * scale), 10 * S * scale, fill=(WHITE if on else "#E4DED6"),
               outline=INK if on else "#B5ADA2", width=3 * S * scale)
            d.rectangle([tx + 3 * S * scale, y + 3 * S * scale, tx + tw - 3 * S * scale, y + 16 * S * scale],
                        fill=(pal["accent"] if on else "#CFC7BC"))
            label = short(it["label"], 7)
            f = lab
            while text_w(d, label, f) > tw - 16 * S * scale and f.size > 12 * S:
                f = font("sans-bold", f.size - 2 * S)
            d.text((tx + tw / 2 - text_w(d, label, f) / 2, y + 34 * S * scale), label, font=f, fill=INK if on else "#8F877D")


def fit_font(d, lines, kind, max_w, start, minimum):
    size = start
    while size > minimum:
        f = font(kind, size)
        if max(text_w(d, ln, f) for ln in lines) <= max_w:
            return f
        size -= 2 * S
    return font(kind, minimum)


# ---------------------------------------------------------------- eye-catch

def render_card(item, width=1200, height=675):
    a = item["article"]
    v = a["visual"]
    pal = palette(item)
    W, H = width * S, height * S
    img = Image.new("RGBA", (W, H), pal["bg"])
    d = Draw(img)
    # 器具のイラスト（右側の舞台）
    stage_r = H * 0.41
    scx, scy = W * 0.765, H * 0.47
    d.ellipse([scx - stage_r, scy - stage_r, scx + stage_r, scy + stage_r], fill=pal["stage"])
    ms = stage_r * 1.45
    MOTIF_FN[v["motif"]](img, d, scx - ms / 2, scy - ms / 2 - H * 0.01, ms, ms, pal)
    # 文字（左側）
    left, maxw = 76 * S, W * 0.47
    cat = category_name(item)
    fcat = font("sans-bold", 28 * S)
    y = H * 0.12
    if cat:
        d.text((left, y), cat, font=fcat, fill=pal["accent"])
        d.line([(left, y + 48 * S), (left + 56 * S, y + 48 * S)], fill=pal["accent"], width=4 * S)
    lines = v["catch"]
    y = H * 0.12 + 78 * S
    gy = H * 0.64
    by_height = int((gy - 24 * S - y) / (len(lines) * 1.24))
    fc = fit_font(d, lines, "serif", maxw, min(88 * S, by_height), 48 * S)
    for ln in lines:
        d.text((left, y), ln, font=fc, fill=INK)
        y += fc.size * 1.24
    glyph(d, v["diagram"], left, gy, maxw * 0.92, pal, scale=0.92 if height < 650 else 1.0)
    fsite = font("sans", 22 * S)
    d.text((left, H - 84 * S), "はじめてのおうちコーヒー", font=fsite, fill=MUTED)
    roast_ribbon(d, 0, H - 26 * S, W, H)
    return img.resize((width, height), Image.LANCZOS).convert("RGB")


# ---------------------------------------------------------------- video

def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def supersampled(width, height, draw_fn):
    """S倍の透明キャンバスに描いて縮小した RGBA 画像を返す。"""
    big = Image.new("RGBA", (width * S, height * S), (0, 0, 0, 0))
    draw_fn(big, Draw(big))
    return big.resize((width, height), Image.LANCZOS)


TITLE_LEN, ITEM_LEN, END_LEN = 3.4, 3.6, 3.2


def video_seconds(item):
    return TITLE_LEN + ITEM_LEN * len(item["article"]["visual"]["diagram"]["items"]) + END_LEN


def video_frames(item, fps=24):
    """フレームを順に返す。タイトル → 図解の項目を1つずつ（右下で現在の項目を強調） → 終わりの案内。"""
    a = item["article"]
    v = a["visual"]
    dg = v["diagram"]
    pal = palette(item)
    items = dg["items"]
    sources = a.get("sources", [])
    total = video_seconds(item)

    def panel_fn(img, d):
        d.ellipse([0, 0, 420 * S, 420 * S], fill=pal["stage"])
        MOTIF_FN[v["motif"]](img, d, 45 * S, 30 * S, 330 * S, 330 * S, pal)

    panel = supersampled(420, 420, panel_fn)
    glyphs = [supersampled(1120, 150, lambda img, d, i=i: glyph(d, dg, 0, 6 * S, 1120 * S, pal, active=i, scale=0.62))
              for i in range(len(items))]
    title_img = render_card(item, 1280, 720)
    f_count, f_label = font("sans-bold", 24), font("serif", 66)
    f_detail, f_note, f_src = font("sans-bold", 36), font("sans", 28), font("sans", 21)

    def text_layer(i):
        it = items[i]
        layer = Image.new("RGBA", (760, 440), (0, 0, 0, 0))
        ld = Draw(layer)
        head = f"{i + 1} / {len(items)}　{strip_cites(dg.get('title', ''))}"
        ld.text((0, 0), short(head, 32), font=f_count, fill=pal["accent"])
        ld.text((0, 48), strip_cites(it["label"]), font=f_label, fill=INK)
        yy = 48 + 66 * 1.45
        for ln in wrap(ld, strip_cites(it.get("detail", "")), f_detail, 700)[:3]:
            ld.text((0, yy), ln, font=f_detail, fill=INK)
            yy += 36 * 1.5
        if it.get("note"):
            yy += 10
            for ln in wrap(ld, strip_cites(it["note"]), f_note, 700)[:3]:
                ld.text((0, yy), ln, font=f_note, fill=MUTED)
                yy += 28 * 1.55
        cites = [c for c in it.get("cite", []) if 1 <= c <= len(sources)]
        if cites:
            src = "出典 " + "／".join(f"[{c}] {short(sources[c - 1].get('title', ''), 22)}" for c in cites[:2])
            ld.text((0, 408), src if len(src) <= 58 else src[:57] + "…", font=f_src, fill=MUTED)
        return layer

    texts = [text_layer(i) for i in range(len(items))]

    def base(progress, with_panel=True):
        img = Image.new("RGBA", (1280, 720), pal["bg"])
        if with_panel:
            img.alpha_composite(panel, (820, 60))
        d = Draw(img)
        roast_ribbon(d, 0, 694, 1280, 720, progress)
        return img

    for k in range(int(TITLE_LEN * fps)):
        t = k / fps
        frame = Image.blend(base(t / total, False).convert("RGB"), title_img, ease(t / 0.6))
        roast_ribbon(Draw(frame), 0, 694, 1280, 720, t / total)
        yield frame
    for i in range(len(items)):
        for k in range(int(ITEM_LEN * fps)):
            t = k / fps
            img = base((TITLE_LEN + i * ITEM_LEN + t) / total)
            img.alpha_composite(glyphs[i], (80, 540))
            layer = texts[i]
            fade = ease(t / 0.45)
            if fade < 1:
                layer = layer.copy()
                layer.putalpha(layer.getchannel("A").point(lambda p, f=fade: int(p * f)))
            img.alpha_composite(layer, (80, int(70 + (1 - ease(t / 0.5)) * 34)))
            yield img.convert("RGB")
    end = base(1.0)
    d = Draw(end)
    d.text((80, 150), "続きは記事で。", font=font("serif", 58), fill=INK)
    for n, ln in enumerate(("選び方と注意点、", "道具の探し方まで", "まとめています。")):
        d.text((80, 260 + n * 56), ln, font=f_detail, fill=INK)
    d.text((80, 560), "はじめてのおうちコーヒー", font=f_note, fill=MUTED)
    for k in range(int(END_LEN * fps)):
        t = k / fps
        frame = end.copy()
        roast_ribbon(Draw(frame), 0, 694, 1280, 720, min(1.0, (total - END_LEN + t) / total))
        yield frame.convert("RGB")


def wrap(d, text, f, max_w):
    lines, cur = [], ""
    for ch in text:
        if text_w(d, cur + ch, f) > max_w and cur:
            if ch in "、。」）・":
                cur += ch
                lines.append(cur)
                cur = ""
                continue
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def encode_video(item, out_path, fps=24):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg が見つかりません。apt-get install ffmpeg")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720", "-r", str(fps),
           "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", "-tune", "stillimage", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    poster = None
    for n, frame in enumerate(video_frames(item, fps)):
        if n == int(fps * 1.2):
            poster = frame.copy()
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg の変換に失敗しました")
    return poster


# ---------------------------------------------------------------- main

def generate(slug):
    item = load_item(slug)
    if not item["article"].get("visual"):
        raise SystemExit(f"{slug}: visual がありません")
    out = ROOT / OUT_DIR / slug
    out.mkdir(parents=True, exist_ok=True)
    card = render_card(item)
    card.save(out / "eyecatch.webp", "WEBP", quality=84, method=6)
    card.resize((640, 360), Image.LANCZOS).save(out / "eyecatch-640.webp", "WEBP", quality=82, method=6)
    render_card(item, 1200, 630).save(out / "og.jpg", "JPEG", quality=86, optimize=True, progressive=True)
    poster = encode_video(item, out / "explainer.mp4")
    poster.save(out / "explainer-poster.webp", "WEBP", quality=80, method=6)
    manifest = {"visual_sha256": visual_hash(item), "generator_version": GENERATOR_VERSION,
                "video_seconds": round(video_seconds(item), 2),
                "files": sorted(p.name for p in out.iterdir() if p.name != "media.json")}
    (out / "media.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def is_stale(slug):
    m = ROOT / OUT_DIR / slug / "media.json"
    if not m.exists():
        return True
    return json.loads(m.read_text(encoding="utf-8")).get("visual_sha256") != visual_hash(load_item(slug))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--stale", action="store_true")
    args = ap.parse_args()
    slugs = args.slugs
    if args.all or args.stale:
        slugs = [p.stem for p in sorted((ROOT / "content/articles").glob("*.json"))]
        if args.stale:
            slugs = [s for s in slugs if is_stale(s)]
    for s in slugs:
        print("media:", generate(s).relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
