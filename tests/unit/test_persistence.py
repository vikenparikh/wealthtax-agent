from pathlib import Path

from wealthtax_agent.persistence import (
    list_saved_years,
    load_all_prior_returns,
    load_state,
    save_state,
)
from wealthtax_agent.state import DraftReturn, FormExtract, GraphState


def _make_state(year: int) -> GraphState:
    return GraphState(
        filing_year=year,
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON"},
        extracts=[FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 70000.0 + 1000 * (year - 2023)})],
        draft_returns={"CA": DraftReturn(
            jurisdiction="CA", tax_year=year,
            totals={"total_income": 70000.0 + 1000 * (year - 2023), "taxable_income": 70000.0, "total_tax": 14000.0},
        )},
    )


def test_save_and_load_roundtrip(tmp_path: Path):
    state = _make_state(2024)
    out = save_state(state, root=tmp_path)
    assert out.exists()

    reloaded = load_state(2024, root=tmp_path)
    assert reloaded.filing_year == 2024
    assert "CA" in reloaded.draft_returns
    assert reloaded.draft_returns["CA"].totals["total_income"] == 71000.0
    assert reloaded.extracts[0].fields["employment_income"] == 71000.0


def test_list_saved_years(tmp_path: Path):
    save_state(_make_state(2023), root=tmp_path)
    save_state(_make_state(2024), root=tmp_path)
    save_state(_make_state(2025), root=tmp_path)
    assert list_saved_years(tmp_path) == [2023, 2024, 2025]


def test_load_all_prior_returns_strict_lt(tmp_path: Path):
    save_state(_make_state(2023), root=tmp_path)
    save_state(_make_state(2024), root=tmp_path)
    prior = load_all_prior_returns(2024, root=tmp_path)
    assert list(prior.keys()) == [2023]


def test_save_drops_raw_bytes(tmp_path: Path):
    from wealthtax_agent.state import InputDocument
    state = _make_state(2024)
    state.raw_docs = [InputDocument(content=b"%PDF-binary-blob", filename="t4.pdf", mime_type="application/pdf")]
    save_state(state, root=tmp_path)
    raw = (tmp_path / "2024.json").read_text(encoding="utf-8")
    assert "PDF-binary-blob" not in raw  # bytes dropped
    reloaded = load_state(2024, root=tmp_path)
    # The filename metadata survives even though content was dropped.
    assert any(getattr(d, "filename", None) == "t4.pdf" for d in reloaded.raw_docs)
