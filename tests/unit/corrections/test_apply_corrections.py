from wealthtax_agent.corrections import apply_corrections
from wealthtax_agent.state import Correction, FieldChange, FormExtract, GraphState


def _state_with_t4(employment: float = 80000.0) -> GraphState:
    return GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={},
        extracts=[
            FormExtract(form_code="T4", jurisdiction="CA",
                         fields={"employment_income": employment}),
        ],
    )


def test_set_extract_field_updates_value():
    state = _state_with_t4()
    state.corrections = [Correction(kind="inline_edit", changes=[
        FieldChange(op="set", target="extract", form_code="T4",
                    field="employment_income", new_value=92300),
    ])]
    new = apply_corrections(state)
    assert new.extracts[0].fields["employment_income"] == 92300.0
    assert new.revision_number == 1
    assert len(new.applied_corrections) == 1
    assert new.corrections == []  # cleared after apply


def test_add_form_appends_extract():
    state = _state_with_t4()
    state.corrections = [Correction(kind="chat", user_prompt="Add a 1099-INT for $400", changes=[
        FieldChange(op="add", target="form", form_code="1099-INT",
                    jurisdiction="US", field="interest_income", new_value=400),
    ])]
    new = apply_corrections(state)
    codes = [e.form_code for e in new.extracts]
    assert "1099-INT" in codes
    new_int = [e for e in new.extracts if e.form_code == "1099-INT"][0]
    assert new_int.fields["interest_income"] == 400.0
    assert new_int.jurisdiction == "US"


def test_remove_form_drops_extract():
    state = _state_with_t4()
    state.extracts.append(FormExtract(form_code="1099-MISC", jurisdiction="US", fields={"rents": 5000.0}))
    state.corrections = [Correction(kind="chat", changes=[
        FieldChange(op="remove", target="form", form_code="1099-MISC"),
    ])]
    new = apply_corrections(state)
    codes = [e.form_code for e in new.extracts]
    assert "1099-MISC" not in codes
    assert "T4" in codes


def test_set_user_answer():
    state = _state_with_t4()
    state.corrections = [Correction(kind="chat", changes=[
        FieldChange(op="set", target="user_answer", field="filing_status",
                    new_value="married_filing_jointly"),
    ])]
    new = apply_corrections(state)
    assert new.user_answers["filing_status"] == "married_filing_jointly"


def test_negative_income_correction_rejected():
    state = _state_with_t4()
    state.corrections = [Correction(kind="inline_edit", changes=[
        FieldChange(op="set", target="extract", form_code="T4",
                    field="employment_income", new_value=-1000),
    ])]
    new = apply_corrections(state)
    # Value unchanged + warning added
    assert new.extracts[0].fields["employment_income"] == 80000.0
    assert any("cannot be negative" in w for w in new.warnings)


def test_apply_is_pure_does_not_mutate_input():
    state = _state_with_t4()
    state.corrections = [Correction(kind="inline_edit", changes=[
        FieldChange(op="set", target="extract", form_code="T4",
                    field="employment_income", new_value=70000),
    ])]
    apply_corrections(state)
    # Original state still has the original value + the staged correction.
    assert state.extracts[0].fields["employment_income"] == 80000.0
    assert len(state.corrections) == 1
    assert state.revision_number == 0


def test_no_corrections_is_no_op():
    state = _state_with_t4()
    new = apply_corrections(state)
    assert new is state  # short-circuit returns the same object


def test_add_form_with_non_numeric_value_does_not_crash():
    """A correction adding a form with a worded amount (e.g. the LLM echoing
    "four hundred") must not raise. The add-form path called float() directly on
    the coerced value with no guard, so a non-numeric value raised ValueError and
    killed the entire correction pass. It must degrade gracefully like the
    set-extract path: add the form, skip the bad value, warn."""
    state = _state_with_t4()
    state.corrections = [Correction(kind="chat", user_prompt="add a 1099-INT for four hundred dollars", changes=[
        FieldChange(op="add", target="form", form_code="1099-INT",
                    jurisdiction="US", field="interest_income", new_value="four hundred"),
    ])]
    new = apply_corrections(state)  # before fix: ValueError
    # The form is still added (graceful degradation, not a hard drop).
    new_int = [e for e in new.extracts if e.form_code == "1099-INT"]
    assert len(new_int) == 1
    # The unparseable field is skipped, not stored as a string.
    assert "interest_income" not in new_int[0].fields
    assert any("expects numeric" in w for w in new.warnings)


def test_add_form_with_numeric_string_value_still_parses():
    # Regression guard: a numeric string ("400", "$1,200") must still coerce.
    state = _state_with_t4()
    state.corrections = [Correction(kind="chat", changes=[
        FieldChange(op="add", target="form", form_code="1099-INT",
                    jurisdiction="US", field="interest_income", new_value="$1,200"),
    ])]
    new = apply_corrections(state)
    new_int = [e for e in new.extracts if e.form_code == "1099-INT"][0]
    assert new_int.fields["interest_income"] == 1200.0


def test_add_form_with_plain_numeric_value_unchanged():
    # Regression guard: the existing numeric path is untouched.
    state = _state_with_t4()
    state.corrections = [Correction(kind="chat", changes=[
        FieldChange(op="add", target="form", form_code="1099-INT",
                    jurisdiction="US", field="interest_income", new_value=400),
    ])]
    new = apply_corrections(state)
    new_int = [e for e in new.extracts if e.form_code == "1099-INT"][0]
    assert new_int.fields["interest_income"] == 400.0
