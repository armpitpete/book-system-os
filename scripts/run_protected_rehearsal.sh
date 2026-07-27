#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT=""
LAUNCH_LOG=""
PID_FILE=""
DETACHED_MARKER="BOOK_SYSTEM_REHEARSAL_DETACHED"
CHILD_PID=""
FINAL_WRITTEN=0
SCRIPT_ARGS=()

usage() {
    cat <<'EOF'
Usage:
  sudo bash scripts/run_protected_rehearsal.sh \
    --script <repository script path> \
    --launch-log <new absolute launch log> \
    --pid-file <new absolute pid file> \
    -- <script arguments>

The first invocation validates the command and starts a detached runner with
nohup. The detached runner records script digests, forwards termination signals,
waits for the protected script, and writes a private result sidecar.
EOF
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --script)
            SCRIPT="${2:-}"
            shift 2
            ;;
        --launch-log)
            LAUNCH_LOG="${2:-}"
            shift 2
            ;;
        --pid-file)
            PID_FILE="${2:-}"
            shift 2
            ;;
        --)
            shift
            SCRIPT_ARGS=("$@")
            break
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

[[ "$(id -u)" -eq 0 ]] || fail "run as root"
[[ -n "$SCRIPT" ]] || fail "missing script"
[[ -n "$LAUNCH_LOG" && "$LAUNCH_LOG" == /* ]] || fail "launch log must be absolute"
[[ -n "$PID_FILE" && "$PID_FILE" == /* ]] || fail "pid file must be absolute"
[[ "$LAUNCH_LOG" != "$ROOT_DIR"/* ]] || fail "launch log must be outside the repository"
[[ "$PID_FILE" != "$ROOT_DIR"/* ]] || fail "pid file must be outside the repository"

if [[ "$SCRIPT" != /* ]]; then
    SCRIPT="$ROOT_DIR/$SCRIPT"
fi
SCRIPT="$(realpath -e "$SCRIPT")"
[[ "$SCRIPT" == "$ROOT_DIR/scripts/"* ]] || fail "script must be inside repository scripts directory"
[[ -f "$SCRIPT" && ! -L "$SCRIPT" ]] || fail "script must be a regular non-symlink file"
[[ -r "$SCRIPT" ]] || fail "script is not readable"

RESULT_FILE="${LAUNCH_LOG}.result"
[[ ! -e "$RESULT_FILE" ]] || fail "result file already exists"

write_result() {
    local result="$1"
    local exit_code="$2"
    local signal_name="${3:-none}"
    if [[ $FINAL_WRITTEN -eq 1 ]]; then
        return
    fi
    local temporary="${RESULT_FILE}.tmp.$$"
    cat > "$temporary" <<EOF
rehearsal-runner-result=$result
exit-code=$exit_code
signal=$signal_name
script=$SCRIPT
launch-log=$LAUNCH_LOG
pid-file=$PID_FILE
EOF
    chmod 0600 "$temporary"
    mv "$temporary" "$RESULT_FILE"
    FINAL_WRITTEN=1
}

on_signal() {
    local signal_name="$1"
    local exit_code="$2"
    echo "rehearsal-runner-signal=$signal_name" >&2
    if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
        kill -TERM "$CHILD_PID" 2>/dev/null || true
        wait "$CHILD_PID" 2>/dev/null || true
    fi
    write_result FAIL "$exit_code" "$signal_name"
    exit "$exit_code"
}

on_exit() {
    local exit_code=$?
    if [[ $FINAL_WRITTEN -eq 0 && "${!DETACHED_MARKER:-0}" == "1" ]]; then
        if [[ $exit_code -eq 0 ]]; then
            write_result PASS 0 none
        else
            write_result FAIL "$exit_code" none
        fi
    fi
}
trap on_exit EXIT
trap 'on_signal HUP 129' HUP
trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM

if [[ "${!DETACHED_MARKER:-0}" != "1" ]]; then
    [[ ! -e "$LAUNCH_LOG" ]] || fail "launch log already exists"
    [[ ! -e "$PID_FILE" ]] || fail "pid file already exists"
    [[ -d "$(dirname "$LAUNCH_LOG")" ]] || fail "launch-log parent does not exist"
    [[ -d "$(dirname "$PID_FILE")" ]] || fail "pid-file parent does not exist"

    nohup env "$DETACHED_MARKER=1" bash "$0" \
        --script "$SCRIPT" \
        --launch-log "$LAUNCH_LOG" \
        --pid-file "$PID_FILE" \
        -- "${SCRIPT_ARGS[@]}" \
        > "$LAUNCH_LOG" 2>&1 < /dev/null &
    runner_pid=$!
    printf '%s\n' "$runner_pid" > "$PID_FILE"
    chmod 0600 "$PID_FILE"
    sleep 1
    kill -0 "$runner_pid" 2>/dev/null || fail "detached rehearsal exited during launch"
    echo "rehearsal-runner-pid=$runner_pid"
    echo "rehearsal-launch-log=$LAUNCH_LOG"
    echo "rehearsal-pid-file=$PID_FILE"
    echo "rehearsal-result-file=$RESULT_FILE"
    FINAL_WRITTEN=1
    exit 0
fi

[[ -e "$LAUNCH_LOG" ]] || fail "detached launch log is unavailable"
[[ -f "$PID_FILE" ]] || fail "detached pid file is unavailable"
[[ "$(cat "$PID_FILE")" == "$$" ]] || fail "pid file does not match detached runner"

echo "===== PROTECTED REHEARSAL RUNNER ====="
echo "timestamp=$(date -u +%Y%m%dT%H%M%SZ)"
echo "runner-pid=$$"
echo "script=$SCRIPT"
echo "launch-log=$LAUNCH_LOG"
echo "pid-file=$PID_FILE"
sha256sum "$0" "$SCRIPT"

echo
echo "===== PROTECTED SCRIPT ====="
set +e
bash "$SCRIPT" "${SCRIPT_ARGS[@]}" &
CHILD_PID=$!
wait "$CHILD_PID"
child_status=$?
set -e
CHILD_PID=""

if [[ $child_status -eq 0 ]]; then
    write_result PASS 0 none
else
    write_result FAIL "$child_status" none
fi

cat "$RESULT_FILE"
exit "$child_status"
