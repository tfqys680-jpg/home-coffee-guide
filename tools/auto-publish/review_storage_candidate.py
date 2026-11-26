"""今回の公開前審査専用。記事の保存・キュー更新・公開処理は呼び出さない。"""
import hashlib
import json
import os
from pathlib import Path

import pipeline as p


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    candidate = p.ROOT / "docs/proposals/coffee-storage-20261126/article.json"
    article = json.loads(candidate.read_text())
    out = Path(os.environ["REVIEW_OUTPUT"])
    out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((p.HERE / "config.json").read_text())
    task = {"主キーワード": "コーヒー豆 保存方法", "補助キーワード": "コーヒー豆 冷凍;粉 保存 期間"}
    existing = p.existing_articles()
    history = []
    fetched = {}
    result = {"pass": False, "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}
    try:
        for round_no in range(1, cfg["max_review_rounds"] + 1):
            source_lines = []
            for i, source in enumerate(article.get("sources", []), 1):
                url = source["url"]
                if url not in fetched:
                    fetched[url] = p.fetch_source(url)
                ok, text = fetched[url]
                source_lines.append(f"### [{i}] {source['title']} {url}\nverified={ok}\n{text}")
            review = p.ask_claude(p.prompts.REVIEWER_SYSTEM, p.prompts.REVIEWER_USER.format(
                theme="コーヒー豆の保存方法と保存期間の目安", main_kw=task["主キーワード"],
                existing=p.existing_text(), article=json.dumps(article, ensure_ascii=False),
                sources="\n\n".join(source_lines), quality_errors=p.review_quality_feedback(article, task, existing)))
            history.append(review)
            write(out / f"round-{round_no}.json", review)
            article = review.get("article") or article
            write(out / "article.json", article)
            verdict = str(review.get("verdict", "BLOCK")).strip()
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
    except Exception as exc:
        result["errors"] = [f"{type(exc).__name__}: {exc}"]
    result["rounds"] = len(history)
    result["sources"] = [{"url": u, "verified": ok, "text_chars": len(t)} for u, (ok, t) in fetched.items()]
    write(out / "result.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "sources"}, ensure_ascii=False))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
