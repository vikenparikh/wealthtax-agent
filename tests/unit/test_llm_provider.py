"""AC1 — Groq PII-exposure gate.

Passes when EITHER:
  (a) docs/groq-dpa-marker.md exists (DPA on file), OR
  (b) `groq` is not imported anywhere in the wealthtax_agent package
      (provider has been fully swapped to Anthropic SDK).

At present the codebase uses the Groq OpenAI-compatible endpoint and
docs/groq-dpa-marker.md documents the signed DPA.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "wealthtax_agent"
DPA_MARKER = REPO_ROOT / "docs" / "groq-dpa-marker.md"


def _groq_imported_in_src() -> bool:
    """Return True if any .py file under src/ imports the groq package directly."""
    for py_file in SRC_ROOT.rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "groq" or alias.name.startswith("groq."):
                        return True
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("groq"):
                    return True
    return False


def test_dpa_marker_or_no_groq_import():
    """Exactly one of the two mitigations must be in place."""
    dpa_ok = DPA_MARKER.exists() and DPA_MARKER.stat().st_size > 0
    no_groq = not _groq_imported_in_src()
    assert dpa_ok or no_groq, (
        "Groq PII risk: no DPA marker at docs/groq-dpa-marker.md "
        "AND groq is still directly imported in src/. "
        "Either add the marker (option a) or swap to Anthropic SDK (option b)."
    )


def test_dpa_marker_content_when_present():
    """If the marker file exists it must contain a non-empty DPA reference line."""
    if not DPA_MARKER.exists():
        return  # AC satisfied via option b — no groq import; skip content check
    content = DPA_MARKER.read_text(encoding="utf-8")
    assert "DPA" in content, "groq-dpa-marker.md must mention 'DPA'"
    assert len(content.strip()) > 50, "groq-dpa-marker.md appears too thin to be real"


def test_pii_mitigation_layers_documented():
    """DPA marker should reference the LOCAL_OCR_ONLY fallback and Fernet encryption."""
    if not DPA_MARKER.exists():
        return
    content = DPA_MARKER.read_text(encoding="utf-8")
    assert "LOCAL_OCR_ONLY" in content, "DPA marker must reference LOCAL_OCR_ONLY fallback"
    assert "Fernet" in content or "fernet" in content.lower(), (
        "DPA marker must reference Fernet encryption layer"
    )
