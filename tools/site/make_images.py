#!/usr/bin/env python3
"""サイト共通のOGP画像（images/ogp.png 1200x630）とロゴ（images/logo.png 512x512）を作る。

一度作ってコミットすれば、build.py は画像ファイルを参照するだけ（CIでは実行しない）。
必要: Pillow と日本語フォント（Noto Sans CJK）。デザインを変えたら作り直してコミットする。
実行: python3 tools/site/make_images.py [--font /path/to/NotoSansCJK-Bold.ttc]
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
BEAN, ROAST, CREMA, MILK = (59, 42, 32), (107, 74, 53), (200, 155, 109), (250, 246, 240)
FONT_CANDIDATES = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
                   "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "C:/Windows/Fonts/YuGothB.ttc"]


def font(path, size):
    return ImageFont.truetype(path, size, index=0)


def cup(draw, cx, cy, s, color, steam):
    """シンプルなカップの絵（中心 cx, cy、大きさ s）。"""
    w, h = s, s * 0.72
    draw.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=s * 0.16, fill=color)
    r = s * 0.2
    draw.ellipse([cx + w / 2 - r * 0.6, cy - r, cx + w / 2 + r * 1.4, cy + r], outline=color, width=max(4, int(s * 0.07)))
    draw.rounded_rectangle([cx - w * 0.68, cy + h / 2 + s * 0.04, cx + w * 0.68, cy + h / 2 + s * 0.12],
                           radius=s * 0.04, fill=color)
    lw, r = max(3, int(s * 0.035)), s * 0.07
    for dx in (-0.2, 0.0, 0.2):  # 湯気（S字）
        x, top = cx + dx * s, cy - h / 2 - s * 0.38
        draw.arc([x - r, top, x + r, top + 2 * r], 270, 90, fill=steam, width=lw)
        draw.arc([x - r, top + 2 * r, x + r, top + 4 * r], 90, 270, fill=steam, width=lw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", default=next((p for p in FONT_CANDIDATES if Path(p).exists()), None))
    args = ap.parse_args()
    if not args.font:
        raise SystemExit("日本語フォントが見つかりません。--font で指定してください")
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    (ROOT / "images").mkdir(exist_ok=True)

    img = Image.new("RGB", (1200, 630), BEAN)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 560, 1200, 630], fill=ROAST)
    cup(d, 1030, 300, 180, CREMA, MILK)
    d.text((80, 220), site["site_name"], font=font(args.font, 70), fill=MILK)
    d.text((84, 320), site["tagline"], font=font(args.font, 38), fill=CREMA)
    d.text((94, 578), "淹れ方・豆・器具・保存の基本を、出典を確かめてまとめるガイド", font=font(args.font, 26), fill=MILK)
    img.save(ROOT / "images/ogp.png", optimize=True)

    logo = Image.new("RGB", (512, 512), BEAN)
    cup(ImageDraw.Draw(logo), 236, 300, 240, CREMA, MILK)
    logo.save(ROOT / "images/logo.png", optimize=True)
    print("wrote images/ogp.png, images/logo.png")


if __name__ == "__main__":
    main()
