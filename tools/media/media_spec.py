"""記事の visual（アイキャッチ・図解・動画の元）と shopping（商品の検索リンク）の決まり。

Pillow を使わずに読み込めるよう、生成器（make_media.py）から分けている。品質ゲート・サイト検証・生成器が共通で使う。
"""
import hashlib
import json

GENERATOR_VERSION = 1
MOTIFS = ("mill", "dripper", "press", "canister", "beans", "kettle", "cup")
DIAGRAM_TYPES = ("scale", "steps", "compare")
MEDIA_FILES = ("eyecatch.webp", "eyecatch-640.webp", "og.jpg", "explainer.mp4", "explainer-poster.webp")
# 公開するファイルの上限（ページの重さを抑える）
MAX_BYTES = {"eyecatch.webp": 250_000, "eyecatch-640.webp": 120_000, "og.jpg": 300_000,
             "explainer.mp4": 3_000_000, "explainer-poster.webp": 200_000}
VIDEO_SECONDS = (12, 60)
# 商品の検索リンクで使わない言葉（推奨・順位づけ・誇大）
SHOP_BANNED = ("おすすめ", "オススメ", "ランキング", "人気", "最強", "コスパ", "買うべき", "No.1", "一番", "売れ筋", "神")


def visual_hash(item):
    """画像・動画に描く内容。これが変わったら make_media.py で作り直す。"""
    a = item["article"]
    payload = {"visual": a.get("visual") or {}, "category": a.get("category"), "title": a.get("title"),
               "sources": [s.get("title") for s in a.get("sources", [])], "version": GENERATOR_VERSION}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
