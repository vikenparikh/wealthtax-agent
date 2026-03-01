#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PID_FILE="$ROOT_DIR/.streamlit.pid"
LOG_FILE="$ROOT_DIR/.streamlit.log"
PORT="${PORT:-8501}"

find_python() {
  local candidate
  for candidate in python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
      if [[ $? -eq 0 ]]; then
        echo "$candidate"
        return 0
      fi
    fi
  done

  echo "❌ Python 3.10+ is required (found no compatible interpreter)." >&2
  exit 1
}

ensure_venv() {
  local base_python
  base_python="$(find_python)"

  if [[ -x "$PYTHON_BIN" ]]; then
    if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
    then
      echo "▶ Existing .venv uses Python < 3.10; recreating"
      rm -rf "$VENV_DIR"
    fi
  fi

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "▶ Creating virtual environment at .venv"
    "$base_python" -m venv "$VENV_DIR"
    PYTHON_BIN="$VENV_DIR/bin/python"
  fi

  if ! "$PYTHON_BIN" -c "import streamlit" >/dev/null 2>&1; then
    echo "▶ Installing dependencies"
    "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel
    "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements.txt"
  fi
}

load_env() {
  if [[ "${SKIP_DOTENV:-false}" != "true" ]] && [[ -f "$ROOT_DIR/.env" ]]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
  fi

  export LLM_PROVIDER="groq"
  export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.groq.com/openai/v1}"
  export PYTHONPATH="${PYTHONPATH:-src}"

  if [[ -z "${GROQ_API_KEY:-}" ]]; then
    echo "❌ GROQ_API_KEY is missing. Add it to .env or export it in your shell." >&2
    exit 1
  fi
}

start_app() {
  if [[ -f "$PID_FILE" ]]; then
    local existing_pid
    existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" >/dev/null 2>&1; then
      echo "✅ App already running (pid: $existing_pid)"
      echo "   URL: http://localhost:$PORT"
      exit 0
    fi
    rm -f "$PID_FILE"
  fi

  ensure_venv
  load_env

  cd "$ROOT_DIR"
  nohup "$PYTHON_BIN" -m streamlit run src/wealthtax_agent/main.py --server.headless true --server.port "$PORT" >"$LOG_FILE" 2>&1 &
  local app_pid=$!
  echo "$app_pid" >"$PID_FILE"

  sleep 2
  if ! kill -0 "$app_pid" >/dev/null 2>&1; then
    echo "❌ Failed to start Streamlit. Last logs:" >&2
    tail -n 40 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    exit 1
  fi

  echo "✅ App started"
  echo "   URL: http://localhost:$PORT"
  echo "   PID: $app_pid"
  echo "   Logs: $LOG_FILE"
}

stop_app() {
  local app_pid=""
  if [[ -f "$PID_FILE" ]]; then
    app_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  fi

  if [[ -n "$app_pid" ]] && kill -0 "$app_pid" >/dev/null 2>&1; then
    kill "$app_pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$app_pid" >/dev/null 2>&1; then
      kill -9 "$app_pid" >/dev/null 2>&1 || true
    fi
    rm -f "$PID_FILE"
    echo "✅ App stopped (pid: $app_pid)"
    exit 0
  fi

  rm -f "$PID_FILE"
  if pkill -f "streamlit run src/wealthtax_agent/main.py" >/dev/null 2>&1; then
    echo "✅ App stopped"
  else
    echo "ℹ️ App is not running"
  fi
}

case "${1:-}" in
  start)
    start_app
    ;;
  stop)
    stop_app
    ;;
  *)
    echo "Usage: ./scripts/app.sh {start|stop}" >&2
    exit 1
    ;;
esac
