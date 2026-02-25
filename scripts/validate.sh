#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "❌ Python not found. Install Python 3.10+ or set PYTHON_BIN." >&2
  exit 1
fi

export PYTHONPATH="${PYTHONPATH:-src}"
export GROQ_API_KEY="${GROQ_API_KEY:-gsk-test-key}"

RUN_HISTORY_FILE="$ROOT_DIR/docs/run_history.md"
RUN_TS="$(date -u +"%Y-%m-%d %H:%M:%S")"
TEST_STATUS="not-run"
BOOT_STATUS="not-run"
PORT="n/a"
NOTES=""
APP_PID=""

ensure_run_history_file() {
  if [[ ! -f "$RUN_HISTORY_FILE" ]]; then
    cat >"$RUN_HISTORY_FILE" <<'EOF'
# Validation Run History

This file is automatically updated by `scripts/validate.sh` after each run.

| Timestamp (UTC) | Status | Tests | Streamlit Boot | Port | Notes |
|---|---|---|---|---|---|
EOF
  fi
}

append_run_history() {
  local status="$1"
  ensure_run_history_file
  printf '| %s | %s | %s | %s | %s | %s |\n' \
    "$RUN_TS" "$status" "$TEST_STATUS" "$BOOT_STATUS" "$PORT" "${NOTES:-none}" >> "$RUN_HISTORY_FILE"
}

cleanup() {
  if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" >/dev/null 2>&1; then
    kill "$APP_PID" >/dev/null 2>&1 || true
    wait "$APP_PID" 2>/dev/null || true
  fi
}

on_exit() {
  local exit_code="$1"
  cleanup
  if [[ "$exit_code" -eq 0 ]]; then
    append_run_history "pass"
  else
    append_run_history "fail"
  fi
}

trap 'on_exit $?' EXIT

echo "▶ Running tests..."
"$PYTHON_BIN" -m pytest tests/unit tests/integration -q
TEST_STATUS="pass"

PORT="$("$PYTHON_BIN" - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"

LOG_FILE="$(mktemp -t wealthtax_streamlit_validate.XXXXXX.log)"

echo "▶ Boot-checking Streamlit on port $PORT..."
"$PYTHON_BIN" -m streamlit run src/wealthtax_agent/main.py --server.headless true --server.port "$PORT" >"$LOG_FILE" 2>&1 &
APP_PID=$!

sleep 8

if ! grep -q "You can now view your Streamlit app" "$LOG_FILE"; then
  echo "❌ Streamlit boot check failed. Logs:" >&2
  BOOT_STATUS="fail"
  NOTES="streamlit boot message missing"
  cat "$LOG_FILE" >&2
  exit 1
fi

BOOT_STATUS="pass"

echo "✅ Validation passed"
echo "   - Tests: unit + integration"
echo "   - Streamlit boot: http://localhost:$PORT"
