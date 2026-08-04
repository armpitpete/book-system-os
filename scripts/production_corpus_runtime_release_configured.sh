#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
CANDIDATE_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd -P)"
BASE_LAUNCHER="$CANDIDATE_ROOT/scripts/production_corpus_runtime_release.sh"
ENV_FILE="/opt/book-system/config/env"
LOCAL_URL_PROVIDED=0
ORIGINAL_ARGS=("$@")

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

for ((index = 0; index < ${#ORIGINAL_ARGS[@]}; index++)); do
  case "${ORIGINAL_ARGS[$index]}" in
    --env-file)
      ((index + 1 < ${#ORIGINAL_ARGS[@]})) || fail "--env-file requires a value"
      ENV_FILE="${ORIGINAL_ARGS[$((index + 1))]}"
      ((index += 1))
      ;;
    --local-base-url)
      ((index + 1 < ${#ORIGINAL_ARGS[@]})) || fail "--local-base-url requires a value"
      LOCAL_URL_PROVIDED=1
      ((index += 1))
      ;;
  esac
done

[[ -f "$BASE_LAUNCHER" ]] || fail "Reviewed base launcher is unavailable: $BASE_LAUNCHER"

if [[ "$LOCAL_URL_PROVIDED" -eq 1 ]]; then
  exec bash "$BASE_LAUNCHER" "${ORIGINAL_ARGS[@]}"
fi

[[ -f "$ENV_FILE" ]] || fail "Protected environment file is unavailable: $ENV_FILE"

BOOK_BIND_PORT="$(/usr/bin/python3 - "$ENV_FILE" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
prefix = "BOOK_BIND_PORT="
value = None
for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or not line.startswith(prefix):
        continue
    candidate = line[len(prefix):].strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
        candidate = candidate[1:-1]
    value = candidate
    break

if value is None:
    raise SystemExit("BOOK_BIND_PORT is not configured")
try:
    port = int(value)
except ValueError as exc:
    raise SystemExit("BOOK_BIND_PORT is not an integer") from exc
if not 1 <= port <= 65535:
    raise SystemExit("BOOK_BIND_PORT is outside 1..65535")
print(port)
PY
)" || fail "Could not resolve BOOK_BIND_PORT from $ENV_FILE"

exec bash "$BASE_LAUNCHER" \
  "${ORIGINAL_ARGS[@]}" \
  --local-base-url "http://127.0.0.1:$BOOK_BIND_PORT"
