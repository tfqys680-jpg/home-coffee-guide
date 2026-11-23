#!/usr/bin/env bash
# 公開するファイルを $1（既定 _site）に集める。.github/workflows/deploy.yml と tools/verify.sh が使う。
# build.py が新しい種類のページ（フォルダ）を作るようになったら、ここにも足す（check_public.py が漏れを検出する）。
set -euo pipefail
cd "$(dirname "$0")/../.."
dest="${1:-_site}"
mkdir -p "$dest"
cp -r index.html about.html privacy.html disclaimer.html 404.html sitemap.xml robots.txt css js images "$dest"/
for d in column category; do
  if [ -d "$d" ]; then cp -r "$d" "$dest"/; fi
done
touch "$dest/.nojekyll"
