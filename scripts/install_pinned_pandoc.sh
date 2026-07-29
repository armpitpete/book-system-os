#!/usr/bin/env bash
set -Eeuo pipefail

PANDOC_VERSION="3.9.0.2"
PANDOC_AMD64_SHA256="a69abfababda8a56969a254b09f9553a7be89ddec00d4e0fe9fd585d71a67508"
PANDOC_ARM64_SHA256="b6d21e8f9c3b15744f5a7ab40248019157ed7793875dbe0383d4c82ff572b528"
RUNTIME_ROOT=""

usage() {
  cat <<'EOF'
Usage:
  bash scripts/install_pinned_pandoc.sh --runtime-root /absolute/path

Downloads the reviewed official Pandoc release for the current Linux
architecture, verifies the pinned SHA-256 digest, proves functional sandbox
support, installs it into a versioned directory, and atomically updates the
current symlink.
EOF
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

cleanup() {
  if [[ -n "${TEMP_DIR:-}" && -d "$TEMP_DIR" ]]; then
    rm -rf -- "$TEMP_DIR"
  fi
}
trap cleanup EXIT HUP INT TERM

while (($#)); do
  case "$1" in
    --runtime-root)
      RUNTIME_ROOT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "unknown argument: $1"
      ;;
  esac
done

[[ "$RUNTIME_ROOT" == /* ]] || fail "runtime root must be an absolute path"
[[ "$RUNTIME_ROOT" != "/" ]] || fail "runtime root must not be /"

for command_name in curl sha256sum tar python3 readlink; do
  command -v "$command_name" >/dev/null 2>&1 || fail "missing required command: $command_name"
done

case "$(uname -m)" in
  x86_64|amd64)
    ASSET_ARCH="amd64"
    EXPECTED_SHA256="$PANDOC_AMD64_SHA256"
    ;;
  aarch64|arm64)
    ASSET_ARCH="arm64"
    EXPECTED_SHA256="$PANDOC_ARM64_SHA256"
    ;;
  *)
    fail "unsupported architecture: $(uname -m)"
    ;;
esac

ASSET_NAME="pandoc-${PANDOC_VERSION}-linux-${ASSET_ARCH}.tar.gz"
ASSET_URL="https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/${ASSET_NAME}"
TARGET_DIR="$RUNTIME_ROOT/$PANDOC_VERSION"
CURRENT_LINK="$RUNTIME_ROOT/current"

umask 022
TEMP_DIR="$(mktemp -d)"
ARCHIVE="$TEMP_DIR/$ASSET_NAME"
STAGE_DIR="$TEMP_DIR/stage"
mkdir -p "$STAGE_DIR"

curl \
  --proto '=https' \
  --tlsv1.2 \
  --fail \
  --location \
  --silent \
  --show-error \
  --output "$ARCHIVE" \
  "$ASSET_URL"

echo "$EXPECTED_SHA256  $ARCHIVE" | sha256sum --check --strict --status \
  || fail "Pandoc release archive SHA-256 verification failed"

tar -xzf "$ARCHIVE" --strip-components=1 -C "$STAGE_DIR"
[[ -x "$STAGE_DIR/bin/pandoc" ]] || fail "verified archive does not contain an executable Pandoc binary"

VERSION_LINE="$($STAGE_DIR/bin/pandoc --version | head -n 1)"
[[ "$VERSION_LINE" == "pandoc $PANDOC_VERSION" ]] \
  || fail "verified archive reported unexpected version: $VERSION_LINE"

printf '# Book System OS pinned sandbox probe\n' \
  | "$STAGE_DIR/bin/pandoc" \
      --sandbox \
      --from=markdown+yaml_metadata_block \
      --to=json \
  | python3 -c 'import json, sys; payload=json.load(sys.stdin); assert isinstance(payload, dict) and isinstance(payload.get("blocks"), list)'

mkdir -p "$RUNTIME_ROOT"
chmod 0755 "$RUNTIME_ROOT"

if [[ -e "$TARGET_DIR" ]]; then
  [[ -d "$TARGET_DIR" && ! -L "$TARGET_DIR" ]] \
    || fail "existing version target is not a real directory: $TARGET_DIR"
  [[ -x "$TARGET_DIR/bin/pandoc" ]] \
    || fail "existing version target has no executable Pandoc binary"
  INSTALLED_SHA256="$(sha256sum "$TARGET_DIR/bin/pandoc" | awk '{print $1}')"
  STAGED_SHA256="$(sha256sum "$STAGE_DIR/bin/pandoc" | awk '{print $1}')"
  [[ "$INSTALLED_SHA256" == "$STAGED_SHA256" ]] \
    || fail "existing pinned version differs from the verified release asset"
else
  mv "$STAGE_DIR" "$TARGET_DIR"
fi

if [[ "$(id -u)" -eq 0 ]]; then
  chown -R root:root "$TARGET_DIR"
fi
find "$TARGET_DIR" -type d -exec chmod 0755 {} +
find "$TARGET_DIR" -type f -exec chmod 0644 {} +
chmod 0755 "$TARGET_DIR/bin/pandoc"

TEMP_LINK="$RUNTIME_ROOT/.current.$$"
ln -s "$TARGET_DIR" "$TEMP_LINK"
mv -Tf "$TEMP_LINK" "$CURRENT_LINK"

[[ "$(readlink -f "$CURRENT_LINK")" == "$(readlink -f "$TARGET_DIR")" ]] \
  || fail "current Pandoc symlink did not resolve to the pinned version"
[[ -x "$CURRENT_LINK/bin/pandoc" ]] || fail "activated Pandoc binary is not executable"

printf '# Book System OS activated sandbox probe\n' \
  | "$CURRENT_LINK/bin/pandoc" \
      --sandbox \
      --from=markdown+yaml_metadata_block \
      --to=json \
  | python3 -c 'import json, sys; payload=json.load(sys.stdin); assert isinstance(payload, dict) and isinstance(payload.get("blocks"), list)'

echo "pandoc-version=$PANDOC_VERSION"
echo "pandoc-asset=$ASSET_NAME"
echo "pandoc-asset-sha256=$EXPECTED_SHA256"
echo "pandoc-runtime=$CURRENT_LINK/bin/pandoc"
echo "pandoc-installation=pass"
