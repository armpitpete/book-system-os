#!/usr/bin/env bash
set -euo pipefail

BASE="/opt/book-system"
PANDOC_RUNTIME_ROOT="/opt/book-system-runtime/pandoc"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer as root"
  exit 1
fi

if [ "$(pwd)" != "$BASE" ]; then
  echo "Run this from $BASE"
  exit 1
fi

mkdir -p "$BASE/books/jobs" "$BASE/books/cache" "$BASE/books/outputs" "$BASE/logs"

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-venv python3-pip curl ca-certificates texlive-xetex texlive-latex-recommended texlive-fonts-recommended
else
  echo "Install Python 3, curl, CA certificates and XeLaTeX manually."
fi

bash "$BASE/scripts/install_pinned_pandoc.sh" --runtime-root "$PANDOC_RUNTIME_ROOT"
export PATH="$PANDOC_RUNTIME_ROOT/current/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
python3 "$BASE/scripts/check_runtime_compatibility.py" --pandoc-only

python3 -m venv "$BASE/.venv"
"$BASE/.venv/bin/pip" install --upgrade pip
"$BASE/.venv/bin/pip" install -r "$BASE/requirements.txt"

if [ ! -f "$BASE/config/env" ]; then
  cp "$BASE/config/env.example" "$BASE/config/env"
  echo "Created $BASE/config/env"
fi

chown -R www-data:www-data "$BASE/books" "$BASE/logs" || true
chmod -R 750 "$BASE/books" "$BASE/logs" || true

"$BASE/.venv/bin/python" "$BASE/scripts/check_runtime_compatibility.py" \
  --fix-git-head-readability
runuser -u www-data -- env PATH="$PATH" \
  "$BASE/.venv/bin/python" "$BASE/scripts/check_runtime_compatibility.py"

echo "Install complete."
