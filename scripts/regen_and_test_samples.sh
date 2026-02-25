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

echo "▶ Regenerating realistic sample files..."
"$PYTHON_BIN" sample_tax_slips/generate_realistic_samples.py

echo "▶ Running format coverage integration test..."
"$PYTHON_BIN" -m pytest tests/integration/test_supported_file_formats.py -q

echo "✅ Sample file regeneration and format validation passed"
