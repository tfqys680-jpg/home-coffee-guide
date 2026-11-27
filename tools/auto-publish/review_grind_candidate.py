"""今回の公開前審査専用（挽き目記事の修正版）。記事の保存・キュー更新・公開処理は呼び出さない。

docs/quality/coffee-storage-20261126 の公開前審査と同じ手順で、出典を実際に取得し、
通常の審査プロンプト（prompts.REVIEWER_SYSTEM / REVIEWER_USER）で Claude に独立審査させる。
審査上限（config.json の max_review_rounds）は変更しない。
"""
import hashlib
import json
import os
from pathlib import Path

import pipeline as p

PROPOSAL = p.ROOT / "docs/proposals/coffee-grind-20261127"


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    candidate = PROPOSAL / "article.json"
    wrapper = json.loads(candidate.read_text(encoding="utf-8"))
    article = dict(wrapper["article"])
    article["related"] = list(wrapper.get("related", []))
    out = Path(os.environ["REVIEW_OUTPUT"])
    (out / "sources").mkdir(parents=True, exist_ok=True)
    cfg = json.loads((p.HERE / "config.json").read_text(encoding="utf-8"))
    # キュー（docs/auto-queue.csv）の値をそのまま使う
    task = {"テーマ": "挽き目（粗さ）の選び方と味の違い", "主キーワード": "コーヒー 挽き目 違い",
            "補助キーワード": "中挽き 細挽き;ドリップ 挽き目"}
    existing = p.existing_articles()
    prior = json.loads((PROPOSAL / "original-rejected.json").read_text(encoding="utf-8")).get("issues", [])
    history, fetched = [], {}
    result = {"pass": False, "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}
    try:
        for round_no in range(1, cfg["max_review_rounds"] + 1):
            source_lines = []
            for i, source in enumerate(article.get("sources", []), 1):
                url = source["url"]
                if url not in fetched:
                    fetched[url] = p.fetch_source(url)
                    ok, text = fetched[url]
                    name = hashlib.sha256(url.encode()).hexdigest()[:12]
                    (out / "sources" / f"{name}.txt").write_text(f"{url}\nverified={ok}\n\n{text}\n", encoding="utf-8")
                ok, text = fetched[url]
                source_lines.append(f"### [{i}] {source['title']} {url}\nverified={ok}\n{text}")
            user = p.prompts.REVIEWER_USER.format(
                theme=task["テーマ"], main_kw=task["主キーワード"], existing=p.existing_text(),
                article=json.dumps(article, ensure_ascii=False, indent=1), sources="\n\n".join(source_lines),
                quality_errors=p.review_quality_feedback(article, task, existing))
            user += "\n\n## 前回までの指摘（修正済みか本文と照合し、解決済みの表現を再導入しない）\n"
            user += json.dumps(prior + [x for r in history for x in r.get("issues", [])], ensure_ascii=False)
            review = p.ask_claude(p.prompts.REVIEWER_SYSTEM, user)
            history.append(review)
            write(out / f"round-{round_no}.json", review)
            article = review.get("article") or article
            write(out / "article.json", article)
            verdict = str(review.get("verdict", "BLOCK")).strip().upper()
            if verdict == "PASS":
                quality = p.quality_check(article, task, existing)
                errors = p.validate(article, cfg, {a["slug"] for a in existing})
                errors += quality["errors"] + p.coverage_errors(review)
                errors += [f"未取得出典: {s.get('url')}" for s in article.get("sources", [])
                           if not fetched.get(s.get("url"), (False,))[0]]
                if review.get("ymyl") not in ("低", "中"):
                    errors.append("YMYLが低・中ではない")
                result.update({"pass": not errors, "errors": errors, "verdict": verdict,
                               "ymyl": review.get("ymyl"), "quality": quality})
                break
            if verdict != "REVISE":
                result.update({"verdict": verdict, "errors": ["審査結果がPASSではない"]})
                break
        else:
            result.update({"verdict": "REVISE", "errors": ["審査上限内にPASSとならなかった"]})
    except Exception as exc:  # noqa: BLE001
        result["errors"] = [f"{type(exc).__name__}: {exc}"]
    result["rounds"] = len(history)
    result["sources"] = [{"url": u, "verified": ok, "text_chars": len(t)} for u, (ok, t) in fetched.items()]
    write(out / "result.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "sources"}, ensure_ascii=False))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
