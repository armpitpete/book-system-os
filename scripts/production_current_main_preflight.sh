#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BASE="$SCRIPT_ROOT/scripts/production_current_main_preflight.py"
ASSET_CHECK="$SCRIPT_ROOT/scripts/production_author_asset_preflight.py"

[[ -f "$BASE" ]] || { echo "ERROR: production preflight engine is unavailable" >&2; exit 1; }
[[ -f "$ASSET_CHECK" ]] || { echo "ERROR: author-asset preflight helper is unavailable" >&2; exit 1; }

TMP_DIR="$(mktemp -d /var/tmp/book-system-preflight-wrapper.XXXXXX)"
cleanup() {
  rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT HUP INT TERM

BASE_OUT="$TMP_DIR/base.out"
BASE_ERR="$TMP_DIR/base.err"
ASSET_OUT="$TMP_DIR/assets.out"
ASSET_ERR="$TMP_DIR/assets.err"
SNAPSHOT="$TMP_DIR/author-assets-before.json"

/usr/bin/python3 "$ASSET_CHECK" \
  --phase before \
  --snapshot "$SNAPSHOT" \
  "$@"

set +e
/usr/bin/python3 "$BASE" "$@" >"$BASE_OUT" 2>"$BASE_ERR"
base_status=$?
set -e
if [[ "$base_status" -ne 0 ]]; then
  cat "$BASE_OUT"
  cat "$BASE_ERR" >&2
  exit "$base_status"
fi

evidence_dir="$(sed -n 's/^evidence=//p' "$BASE_OUT" | tail -n 1)"
[[ -n "$evidence_dir" && "$evidence_dir" = /* ]] || {
  cat "$BASE_OUT"
  cat "$BASE_ERR" >&2
  echo "ERROR: base preflight did not report an absolute evidence directory" >&2
  exit 1
}

set +e
/usr/bin/python3 "$ASSET_CHECK" \
  --phase after \
  --snapshot "$SNAPSHOT" \
  --evidence-dir "$evidence_dir" \
  "$@" >"$ASSET_OUT" 2>"$ASSET_ERR"
asset_status=$?
set -e
if [[ "$asset_status" -ne 0 ]]; then
  if [[ -f "$evidence_dir/result.txt" ]]; then
    cp -- "$evidence_dir/result.txt" "$evidence_dir/base-result.txt"
    chmod 0600 "$evidence_dir/base-result.txt"
  fi
  {
    echo "FAIL"
    echo "author-asset preflight invariant failed"
    echo "deployment-authorized=false"
  } >"$evidence_dir/result.txt"
  chmod 0600 "$evidence_dir/result.txt"
  cat "$ASSET_OUT"
  cat "$ASSET_ERR" >&2
  exit "$asset_status"
fi

cat "$BASE_OUT"
cat "$ASSET_OUT"
cat "$BASE_ERR" >&2
cat "$ASSET_ERR" >&2
