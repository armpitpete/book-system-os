#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec /usr/bin/python3 "$SCRIPT_ROOT/scripts/production_current_main_preflight.py" "$@"
