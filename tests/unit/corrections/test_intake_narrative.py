"""Single-shot natural-language intake (deterministic fallback path)."""

from wealthtax_agent.corrections.intake import (
    _local_fallback,
    parse_intake_narrative,
)


def test_local_fallback_parses_w2_wages():
    prompt = "I earned $80,000 W-2 from Google in 2024."
    result = _local_fallback(prompt)
    assert any(e.form_code == "W-2" and e.fields.get("wages") == 80000 for e in result.extracts)
    assert "US" in result.jurisdictions


def test_local_fallback_parses_w2_with_k_magnitude():
    prompt = "Made $120k W-2 income last year."
    result = _local_fallback(prompt)
    w2 = next(e for e in result.extracts if e.form_code == "W-2")
    assert w2.fields["wages"] == 120000


def test_local_fallback_parses_days_per_country():
    prompt = "I spent 200 days in India and 165 days in the US."
    result = _local_fallback(prompt)
    assert result.residency_days["IN"] == 200
    assert result.residency_days["US"] == 165


def test_local_fallback_parses_form16():
    prompt = "Form 16 ₹18,00,000 salary from Infosys."
    result = _local_fallback(prompt)
    form16 = next(e for e in result.extracts if e.form_code == "FORM-16")
    assert form16.fields["gross_salary"] == 1800000
    assert "IN" in result.jurisdictions


def test_local_fallback_parses_form16_with_lakh_suffix():
    prompt = "My Form 16 shows ₹18L gross salary."
    result = _local_fallback(prompt)
    form16 = next(e for e in result.extracts if e.form_code == "FORM-16")
    assert form16.fields["gross_salary"] == 1800000


def test_local_fallback_parses_80c_investments():
    prompt = "Section 80C ₹1.5L PPF contribution."
    result = _local_fallback(prompt)
    eighty_c = next(e for e in result.extracts if e.form_code == "INVESTMENTS-80C")
    assert eighty_c.fields["amount"] == 150000


def test_local_fallback_parses_80d_premium():
    prompt = "80D ₹25,000 medical insurance for self."
    result = _local_fallback(prompt)
    eighty_d = next(e for e in result.extracts if e.form_code == "MEDICAL-80D")
    assert eighty_d.fields["self_premium"] == 25000


def test_local_fallback_parses_1098e_student_loan():
    prompt = "Paid $2,500 1098-E student loan interest."
    result = _local_fallback(prompt)
    loan = next(e for e in result.extracts if e.form_code == "1098-E")
    assert loan.fields["student_loan_interest"] == 2500


def test_local_fallback_parses_t4_canadian():
    prompt = "Worked in Canada earning $70k T4 wages."
    result = _local_fallback(prompt)
    t4 = next(e for e in result.extracts if e.form_code == "T4")
    assert t4.fields["employment_income"] == 70000
    assert "CA" in result.jurisdictions


def test_local_fallback_parses_us_citizenship():
    prompt = "I am a US citizen living abroad."
    result = _local_fallback(prompt)
    assert result.user_answers["is_us_citizen"] == "yes"


def test_local_fallback_parses_indian_citizenship():
    prompt = "I am an Indian citizen who worked in the US."
    result = _local_fallback(prompt)
    assert result.user_answers["is_indian_citizen"] == "yes"


def test_local_fallback_detects_move():
    prompt = "I moved from the US to Canada in July."
    result = _local_fallback(prompt)
    assert result.user_answers["moved_country_during_year"] == "yes"


def test_local_fallback_complex_paragraph():
    """The user's example narrative — a complete tax year in one prompt."""
    prompt = (
        "I'm an Indian citizen who worked in the US Jan-Jun 2024 "
        "(W-2 wages $120k, 1098-E $2500 interest) and moved back to India "
        "Jul-Dec (Form 16 ₹18L salary, 80C ₹1.5L PPF, 80D ₹25k self insurance). "
        "Days: US 180, India 184. I had a Schwab brokerage account with $5k LTCG."
    )
    result = _local_fallback(prompt)
    # W-2
    w2 = next((e for e in result.extracts if e.form_code == "W-2"), None)
    assert w2 is not None and w2.fields["wages"] == 120000
    # 1098-E
    loan = next((e for e in result.extracts if e.form_code == "1098-E"), None)
    assert loan is not None and loan.fields["student_loan_interest"] == 2500
    # Form 16
    form16 = next((e for e in result.extracts if e.form_code == "FORM-16"), None)
    assert form16 is not None and form16.fields["gross_salary"] == 1800000
    # 80C
    eighty_c = next((e for e in result.extracts if e.form_code == "INVESTMENTS-80C"), None)
    assert eighty_c is not None and eighty_c.fields["amount"] == 150000
    # Days
    assert result.residency_days["US"] == 180
    assert result.residency_days["IN"] == 184
    # Citizenship
    assert result.user_answers["is_indian_citizen"] == "yes"
    assert result.user_answers["moved_country_during_year"] == "yes"


def test_parse_intake_narrative_falls_back_when_llm_fails(monkeypatch):
    """When LLM config is missing, the local fallback is used."""
    from wealthtax_agent.corrections import intake as intake_mod
    def _raise(*args, **kwargs):
        raise RuntimeError("no llm")
    monkeypatch.setattr(intake_mod, "load_runtime_config", _raise)
    result = parse_intake_narrative("$80k W-2 wages")
    assert any(e.form_code == "W-2" for e in result.extracts)


def test_parse_intake_narrative_empty_returns_empty():
    result = parse_intake_narrative("")
    assert result.extracts == []
    assert result.residency_days == {}
