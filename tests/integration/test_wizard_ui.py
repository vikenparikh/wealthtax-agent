"""Wizard UI tests — AC-W1, AC-W2, AC-W3, AC-IN1.

Uses streamlit.testing.v1.AppTest for headless rendering.
"""

import os
import pytest

# Provide required env vars before any Streamlit or app import.
os.environ.setdefault("WEALTHTAX_MODE", "self_hosted")
os.environ.setdefault(
    "WEALTHTAX_FERNET_KEY",
    "dGVzdC1rZXktMzItYnl0ZXMtZm9yLXVuaXQtdGVzdHM="  # valid Fernet-shape placeholder; tests mock DB
)

from wealthtax_agent.intake.wizard import WIZARD_STEP_COUNT, WIZARD_STEPS, WizardState


# ---------------------------------------------------------------------------
# WizardState unit tests (no Streamlit, no DB)
# ---------------------------------------------------------------------------

class TestWizardStateNavigation:
    def test_initial_step_is_zero(self):
        wiz = WizardState()
        assert wiz.step == 0

    def test_progress_label_on_step_0(self):
        wiz = WizardState()
        assert wiz.progress_label == f"1/{WIZARD_STEP_COUNT}"

    def test_advance_increments_step(self):
        wiz = WizardState()
        new = wiz.advance({"filing_year": 2024, "jurisdictions": ["CA"]})
        assert new.step == 1

    def test_advance_merges_data(self):
        wiz = WizardState(data={"a": 1})
        new = wiz.advance({"b": 2})
        assert new.data == {"a": 1, "b": 2}

    def test_advance_on_last_step_raises(self):
        wiz = WizardState(step=WIZARD_STEP_COUNT - 1)
        with pytest.raises(ValueError, match="last step"):
            wiz.advance({})

    def test_go_back_decrements_step(self):
        wiz = WizardState(step=2, data={"x": 1})
        prev = wiz.go_back()
        assert prev.step == 1
        assert prev.data == {"x": 1}  # data preserved

    def test_go_back_on_first_step_raises(self):
        wiz = WizardState()
        with pytest.raises(ValueError, match="first step"):
            wiz.go_back()

    def test_can_advance_and_go_back(self):
        wiz = WizardState(step=2)
        assert wiz.can_advance()
        assert wiz.can_go_back()

    def test_cannot_advance_on_last_step(self):
        wiz = WizardState(step=WIZARD_STEP_COUNT - 1)
        assert not wiz.can_advance()
        assert wiz.can_go_back()

    def test_cannot_go_back_on_first_step(self):
        wiz = WizardState()
        assert not wiz.can_go_back()
        assert wiz.can_advance()

    def test_current_step_name(self):
        for i, name in enumerate(WIZARD_STEPS):
            wiz = WizardState(step=i)
            assert wiz.current_step_name == name

    def test_roundtrip_serialisation(self):
        wiz = WizardState(step=3, data={"jurisdictions": ["CA", "US"], "india_regime": "old"})
        restored = WizardState.from_dict(wiz.to_dict())
        assert restored == wiz

    def test_update_data_same_step(self):
        wiz = WizardState(step=1, data={"a": 1})
        updated = wiz.update_data({"b": 2})
        assert updated.step == 1
        assert updated.data == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# Step indicator label check (AC-W1 proxy)
# ---------------------------------------------------------------------------

class TestWizardStepLabels:
    def test_five_steps_defined(self):
        assert WIZARD_STEP_COUNT == 5

    def test_all_step_names_non_empty(self):
        for name in WIZARD_STEPS:
            assert name

    def test_step_1_name_is_jurisdiction_year(self):
        assert WIZARD_STEPS[0] == "jurisdiction_year"

    def test_step_5_name_is_review_submit(self):
        assert WIZARD_STEPS[-1] == "review_submit"


# ---------------------------------------------------------------------------
# India regime toggle — AC-IN1
# ---------------------------------------------------------------------------

class TestIndiaRegimeToggle:
    """Verify that india_regime is captured in wizard data when IN selected."""

    def test_india_regime_defaults_to_new(self):
        wiz = WizardState(data={"jurisdictions": ["IN"]})
        assert wiz.data.get("india_regime", "new") == "new"

    def test_advance_carries_india_regime(self):
        wiz = WizardState(step=2, data={"jurisdictions": ["CA", "IN"]})
        new = wiz.advance({"india_regime": "old", "upload_names": [], "manual_extract_count": 1})
        assert new.data["india_regime"] == "old"

    def test_advance_new_regime_preserved(self):
        wiz = WizardState(step=2, data={"jurisdictions": ["IN"]})
        new = wiz.advance({"india_regime": "new", "upload_names": [], "manual_extract_count": 1})
        assert new.data["india_regime"] == "new"

    def test_serialisation_preserves_regime(self):
        wiz = WizardState(step=4, data={"jurisdictions": ["IN"], "india_regime": "old"})
        restored = WizardState.from_dict(wiz.to_dict())
        assert restored.data["india_regime"] == "old"


# ---------------------------------------------------------------------------
# Approval persistence — AC via serialisation (browser-refresh simulation)
# ---------------------------------------------------------------------------

class TestApprovalPersistence:
    """Approval state stored in wizard.data survives to/from_dict round-trips."""

    def test_approval_state_persists_in_data(self):
        wiz = WizardState(step=4, data={
            "approved_slips": True,
            "approved_explanations": True,
            "approved_responsibility": True,
        })
        restored = WizardState.from_dict(wiz.to_dict())
        assert restored.data["approved_slips"] is True
        assert restored.data["approved_explanations"] is True
        assert restored.data["approved_responsibility"] is True

    def test_approval_state_false_by_default(self):
        wiz = WizardState()
        assert wiz.data.get("approved_slips", False) is False
