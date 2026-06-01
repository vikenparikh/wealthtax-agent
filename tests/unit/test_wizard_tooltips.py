"""P2-AC6 + P2-AC11 — file-based wizard tooltip loader.

These tests pin the tooltip contract for the intake wizard:

* `load_tooltip(jurisdiction, field_key)` reads markdown from disk.
* At least 10 canonical fields across CA, US, IN must return non-empty text.
* The loader has zero runtime dependencies on env vars or external services —
  the wizard renders even when no `GROQ_API_KEY` or `ANTHROPIC_API_KEY` is set.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from wealthtax_agent.content.tooltips import (
    available_tooltips,
    clear_cache,
    load_tooltip,
)


# ---------------------------------------------------------------------------
# Canonical fields explicitly named by P2-AC6 plus at least 10 across CA/US/IN.
# ---------------------------------------------------------------------------
CANONICAL_FIELDS = [
    # CA — three explicit + bonus
    ("CA", "rrsp_contribution"),
    ("CA", "employment_income"),
    ("CA", "fhsa_contribution"),
    ("CA", "property_tax_paid"),
    # US — PRD explicit + workhorses
    ("US", "foreign_tax_credit"),
    ("US", "wages"),
    ("US", "ira_contribution"),
    ("US", "state_local_property_tax"),
    # IN — PRD explicit + key regime levers
    ("IN", "hra_exemption"),
    ("IN", "section_80c"),
    ("IN", "section_80d"),
    ("IN", "ltcg_equity"),
]


# ---------------------------------------------------------------------------
# Markdown source files must exist on disk.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("jurisdiction,filename", [
    ("CA", "ca.md"),
    ("US", "us.md"),
    ("IN", "in.md"),
])
def test_markdown_file_exists_on_disk(jurisdiction: str, filename: str) -> None:
    here = Path(__file__).resolve().parents[2]
    p = here / "src" / "wealthtax_agent" / "content" / "tooltips" / filename
    assert p.exists(), f"Missing tooltip file: {p}"
    assert p.read_text(encoding="utf-8").strip(), f"Tooltip file {p} is empty"


# ---------------------------------------------------------------------------
# At least 10 canonical fields return non-empty strings.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("jurisdiction,field_key", CANONICAL_FIELDS)
def test_load_tooltip_returns_non_empty_string(jurisdiction: str, field_key: str) -> None:
    body = load_tooltip(jurisdiction, field_key)
    assert isinstance(body, str)
    assert body.strip(), f"Empty tooltip body for {jurisdiction}.{field_key}"
    # Tooltips should be more than a one-word stub.
    assert len(body) >= 20, f"Tooltip {jurisdiction}.{field_key} suspiciously short: {body!r}"


def test_at_least_ten_canonical_fields_defined() -> None:
    assert len(CANONICAL_FIELDS) >= 10


# ---------------------------------------------------------------------------
# Jurisdiction case-insensitivity + field-key case-insensitivity.
# ---------------------------------------------------------------------------
def test_jurisdiction_case_insensitive() -> None:
    a = load_tooltip("ca", "rrsp_contribution")
    b = load_tooltip("CA", "rrsp_contribution")
    c = load_tooltip("Ca", "rrsp_contribution")
    assert a == b == c


def test_field_key_case_insensitive() -> None:
    a = load_tooltip("CA", "rrsp_contribution")
    b = load_tooltip("CA", "RRSP_CONTRIBUTION")
    c = load_tooltip("CA", "Rrsp_Contribution")
    assert a == b == c


# ---------------------------------------------------------------------------
# Unknown jurisdiction / field raise KeyError (no silent empty string).
# ---------------------------------------------------------------------------
def test_unknown_jurisdiction_raises() -> None:
    with pytest.raises(KeyError):
        load_tooltip("UK", "foo")


def test_unknown_field_raises() -> None:
    with pytest.raises(KeyError):
        load_tooltip("CA", "definitely_not_a_real_field")


# ---------------------------------------------------------------------------
# available_tooltips() must return all keys defined per jurisdiction.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("jurisdiction", ["CA", "US", "IN"])
def test_available_tooltips_non_trivial(jurisdiction: str) -> None:
    keys = available_tooltips(jurisdiction)
    assert isinstance(keys, list)
    # Each jurisdiction file ships at least 3 sections (so 10+ total across the three).
    assert len(keys) >= 3, f"{jurisdiction} has only {len(keys)} tooltip sections"
    assert all(isinstance(k, str) and k for k in keys)


def test_total_tooltips_across_jurisdictions_at_least_ten() -> None:
    total = sum(len(available_tooltips(j)) for j in ("CA", "US", "IN"))
    assert total >= 10, f"Need ≥10 tooltips across CA/US/IN; got {total}"


# ---------------------------------------------------------------------------
# P2-AC11 — loader runs WITHOUT any LLM env vars set.
# ---------------------------------------------------------------------------
def test_loader_works_with_no_llm_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wizard must render tooltips even when no provider keys are configured."""
    for var in ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    clear_cache()  # force re-parse with the stripped env

    body = load_tooltip("US", "foreign_tax_credit")
    assert "foreign" in body.lower() or "credit" in body.lower()

    # Re-import the module from scratch to confirm there is no top-level
    # env-var lookup; load_tooltip should still work.
    import importlib

    import wealthtax_agent.content.tooltips as mod

    importlib.reload(mod)
    body2 = mod.load_tooltip("US", "foreign_tax_credit")
    assert body2 == body
