from wealthtax_agent.corrections import apply_corrections, revert_correction
from wealthtax_agent.state import Correction, FieldChange, FormExtract, GraphState


def _starter_state() -> GraphState:
    return GraphState(
        filing_year=2024, jurisdictions=["CA"],
        extracts=[FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 80000.0})],
    )


def _set_t4(amount: float) -> Correction:
    return Correction(kind="inline_edit", changes=[
        FieldChange(op="set", target="extract", form_code="T4",
                    field="employment_income", new_value=amount),
    ])


def test_revert_drops_one_correction_keeps_others():
    state = _starter_state()
    a, b, c = _set_t4(85000), _set_t4(90000), _set_t4(95000)
    state.corrections = [a, b, c]
    after = apply_corrections(state)
    assert after.extracts[0].fields["employment_income"] == 95000.0
    assert after.revision_number == 1
    # Revert the middle one
    after2, ok = revert_correction(after, b.id)
    assert ok
    # b is gone from applied_corrections
    ids = {x.id for x in after2.applied_corrections}
    assert b.id not in ids
    # a and c are re-staged as pending corrections
    staged_ids = {x.id for x in after2.corrections}
    assert a.id in staged_ids and c.id in staged_ids


def test_revert_unknown_id_is_noop():
    state = _starter_state()
    state.corrections = [_set_t4(85000)]
    after = apply_corrections(state)
    same, ok = revert_correction(after, "no-such-id")
    assert not ok
    assert same is after
