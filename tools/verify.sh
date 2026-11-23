#!/usr/bin/env bash
# サイトの検証一式（ローカル・CI・自動パイプライン共通）
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1

echo "== build is up to date =="
python3 tools/site/build.py
if ! git diff --quiet -- . ':(exclude)docs' || [ -n "$(git ls-files --others --exclude-standard -- column category)" ]; then
  echo "生成されたHTMLがコミット内容と一致しません。tools/site/build.py を実行してコミットしてください。"
  git status --short
  exit 1
fi

echo "== site check =="
python3 tools/site/check.py

echo "== public files (what deploy.yml publishes) =="
pub=$(mktemp -d)
bash tools/site/collect_public.sh "$pub/_site"
python3 tools/site/check_public.py "$pub/_site"
rm -rf "$pub"

echo "== article quality gate =="
python3 tools/quality/article_quality.py --all

echo "== pipeline tests =="
python3 tools/auto-publish/tests/test_pipeline.py

echo "== build tests =="
python3 tools/site/tests/test_build.py

echo "== quality gate tests =="
python3 tools/quality/tests/test_quality.py
