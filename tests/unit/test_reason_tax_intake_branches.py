"""Branch coverage for reason_tax_node dispatch, intake LLM-dict parsing, and
the wizard's manual_extract.

Gaps surfaced by a fan-out audit subagent; every value verified by running the
code read-only. reason_tax_node's multi-jurisdiction path had no direct tests
(test_reason_tax.py only hit the legacy flat path); corrections.intake's
_result_from_dict / _amount(crore) / _local_fallback(mfj, green-card) and the
wizard's manual_extract '$'/comma-strip + empty->low branches were untested.
"""

from wealthtax_agent.corrections.intake import _amount, _local_fallback, _result_from_dict
from wealthtax_agent.intake.wizard import manual_extract
from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import FormExtract, GraphState, Slip


def _f(code, juris, **fields):
    return FormExtract(form_code=code, jurisdiction=juris, fields=fields)


# --- reason_tax_node ---------------------------------------------------------


def test_reason_tax_empty_state_legacy_fallback():
    d = reason_tax_node(GraphState())
    assert d.draft_return.jurisdiction == "CA"
    assert d.draft_return.total_income == 0.0
    assert d.draft_return.estimated_tax == 0.0


def test_reason_tax_infers_jurisdiction_from_extracts():
    d = reason_tax_node(GraphState(extracts=[_f("W-2", "US", wages=50000.0)]))
    assert sorted(d.draft_returns) == ["US"]
    assert d.draft_return.jurisdiction == "US"
    assert d.warnings == []


def test_reason_tax_us_person_flag_triggers_cross_border_warning():
    d = reason_tax_node(GraphState(
        jurisdictions=["CA"], user_answers={"is_us_person": "yes"},
        extracts=[_f("T4", "CA", employment_income=40000.0)],
    ))
    assert len(d.warnings) == 1
    assert d.warnings[0].startswith("Cross-border situation detected")


def test_reason_tax_multi_jurisdiction_prefers_ca_for_legacy_draft():
    d = reason_tax_node(GraphState(
        jurisdictions=["US", "CA"],
        extracts=[_f("W-2", "US", wages=50000.0), _f("T4", "CA", employment_income=40000.0)],
    ))
    assert sorted(d.draft_returns) == ["CA", "US"]
    assert d.draft_return.jurisdiction == "CA"  # CA preferred for back-compat draft_return
    assert len(d.warnings) >= 1


def test_reason_tax_ca_falls_back_to_slips_when_no_ca_extracts():
    d = reason_tax_node(GraphState(jurisdictions=["CA"], slips=[Slip(type="t4", fields={"employment_income": 60000.0})]))
    assert d.draft_returns["CA"].total_income == 60000.0


# --- corrections.intake ------------------------------------------------------


def test_result_from_dict_parses_and_coerces_llm_payload():
    r = _result_from_dict({
        "extracts": [{"form_code": "w-2", "jurisdiction": "us", "fields": {"wages": "100000"}}],
        "user_answers": {"filing_status": "single"},
        "residency_days": {"us": "180", "ca": "bad"},
        "jurisdictions": ["us"],
        "notes": ["x"],
    })
    e = r.extracts[0]
    assert (e.form_code, e.jurisdiction, e.fields, e.extractor) == ("W-2", "US", {"wages": 100000.0}, "llm")
    assert r.residency_days == {"US": 180}   # unparseable "ca": "bad" skipped
    assert r.jurisdictions == ["US"]


def test_result_from_dict_returns_none_for_invalid_payloads():
    assert _result_from_dict({}) is None
    assert _result_from_dict([1, 2]) is None
    assert _result_from_dict({"extracts": [{"form_code": "w-2", "jurisdiction": "us", "fields": {"wages": "notnum"}}]}) is None


def test_amount_handles_crore_magnitude_and_bad_input():
    assert _amount("2", "crore") == 20_000_000.0
    assert _amount("3", "cr") == 30_000_000.0
    assert _amount("abc") == 0.0


def test_local_fallback_detects_mfj_and_green_card():
    assert _local_fallback("we are married filing jointly this year").user_answers.get("filing_status") == "married_filing_jointly"
    assert _local_fallback("I have a green card.").user_answers.get("is_green_card_holder") == "yes"


# --- wizard.manual_extract ---------------------------------------------------


def test_manual_extract_empty_cleaned_fields_is_low_confidence():
    m = manual_extract("T4", {"unknown": 5})
    assert m.fields == {} and m.confidence == "low"


def test_manual_extract_strips_currency_formatting():
    m = manual_extract("W-2", {"wages": "$1,234.56"})
    assert m.fields["wages"] == 1234.56 and m.confidence == "high"
