#!/usr/bin/env bash
# サイトの検証一式（ローカル・CI・自動パイプライン共通）
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1

echo "== build is up to date =="
python3 tools/site/build.py
if ! git diff --quiet -- . ':(exclude)docs' || [ -n "$(git ls-files --others --exclude-standard -- column)" ]; then
  echo "生成されたHTMLがコミット内容と一致しません。tools/site/build.py を実行してコミットしてください。"
  git status --short
  exit 1
fi

echo "== site check =="
python3 tools/site/check.py

echo "== pipeline tests =="
python3 tools/auto-publish/tests/test_pipeline.py
