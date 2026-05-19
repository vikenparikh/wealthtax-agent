from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.intake import SUPPORTED_INTAKE_FORMS, field_spec_for, manual_extract


def test_t4_intake_matches_ocr_extractor_shape():
    extract = manual_extract("T4", {"employment_income": "85,000.50", "income_tax_deducted": "14000"})
    assert extract.form_code == "T4"
    assert extract.jurisdiction == "CA"
    assert extract.fields["employment_income"] == 85000.50
    assert extract.fields["income_tax_deducted"] == 14000.0
    # Engine consumes the same shape — total_income should match the entered value.
    draft = compute_ca_return([extract], year=2024, province="ON")
    assert draft.total_income == 85000.50


def test_w2_intake_drives_us_engine():
    extract = manual_extract("W-2", {"wages": 75000, "federal_income_tax_withheld": 9000})
    draft = compute_us_return([extract], year=2024, user_answers={"filing_status": "single"})
    assert draft.total_income == 75000.0
    assert draft.line_items["tax_withheld"] == 9000.0


def test_intake_drops_unknown_or_blank_fields():
    extract = manual_extract("T4", {"employment_income": 50000, "unknown_field": 999, "ei_premiums": ""})
    assert "unknown_field" not in extract.fields
    assert "ei_premiums" not in extract.fields
    assert extract.fields["employment_income"] == 50000.0


def test_field_spec_lists_required_fields():
    fields = {f["name"]: f for f in field_spec_for("T4")}
    assert fields["employment_income"]["required"] is True


def test_unknown_form_raises():
    import pytest
    with pytest.raises(ValueError):
        manual_extract("T9999", {"x": 1})


def test_every_intake_form_loads():
    for code in SUPPORTED_INTAKE_FORMS:
        spec = field_spec_for(code)
        assert spec, f"{code} has no fields"
