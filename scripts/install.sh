#!/usr/bin/env bash
set -euo pipefail

BASE="/opt/book-system"

if [ "$(pwd)" != "$BASE" ]; then
  echo "Run this from $BASE"
  exit 1
fi

mkdir -p "$BASE/books/jobs" "$BASE/books/cache" "$BASE/books/outputs" "$BASE/logs"

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-venv python3-pip pandoc texlive-xetex texlive-latex-recommended texlive-fonts-recommended
else
  echo "Install Python 3, Pandoc, and XeLaTeX manually."
fi

python3 -m venv "$BASE/.venv"
"$BASE/.venv/bin/pip" install --upgrade pip
"$BASE/.venv/bin/pip" install -r "$BASE/requirements.txt"

if [ ! -f "$BASE/config/env" ]; then
  cp "$BASE/config/env.example" "$BASE/config/env"
  echo "Created $BASE/config/env"
fi

chown -R www-data:www-data "$BASE/books" "$BASE/logs" || true
chmod -R 750 "$BASE/books" "$BASE/logs" || true

echo "Install complete."
