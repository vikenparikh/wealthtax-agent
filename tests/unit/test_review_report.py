"""Review report jurisdiction-aware rendering — AC-R1."""

import wealthtax_agent.main as main
from wealthtax_agent.state import DraftReturn, GraphState


class TestReviewReportJurisdictionAware:
    def test_ca_report_includes_rrsp(self):
        state = GraphState(
            draft_returns={
                "CA": DraftReturn(
                    total_income=100_000.0,
                    rrsp_deduction=18_000.0,
                    taxable_income=82_000.0,
                    estimated_tax=20_500.0,
                    estimated_refund=0.0,
                )
            }
        )
        report = main._build_review_report(state, "Alex")
        assert "CA Draft Summary" in report
        assert "RRSP deduction" in report
        assert "18,000.00" in report

    def test_us_report_includes_se_tax(self):
        dr = DraftReturn(
            total_income=80_000.0,
            taxable_income=65_000.0,
            estimated_tax=14_000.0,
            estimated_refund=500.0,
        )
        dr.line_items["self_employment_tax"] = 1_200.0
        state = GraphState(draft_returns={"US": dr})
        report = main._build_review_report(state, "")
        assert "US Draft Summary" in report
        assert "SE tax" in report

    def test_in_report_includes_regime(self):
        dr = DraftReturn(
            total_income=1_200_000.0,
            taxable_income=1_100_000.0,
            estimated_tax=220_000.0,
            estimated_refund=0.0,
        )
        dr.line_items["india_regime"] = "new"
        state = GraphState(draft_returns={"IN": dr})
        report = main._build_review_report(state, "")
        assert "IN Draft Summary" in report
        assert "Regime" in report
        assert "new" in report

    def test_multi_jurisdiction_all_sections_present(self):
        state = GraphState(
            draft_returns={
                "CA": DraftReturn(
                    total_income=50_000.0, taxable_income=45_000.0,
                    estimated_tax=9_000.0, estimated_refund=0.0,
                ),
                "US": DraftReturn(
                    total_income=60_000.0, taxable_income=55_000.0,
                    estimated_tax=11_000.0, estimated_refund=200.0,
                ),
            }
        )
        report = main._build_review_report(state, "Jordan")
        assert "CA Draft Summary" in report
        assert "US Draft Summary" in report
        assert "Reviewer: Jordan" in report

    def test_fallback_to_draft_return_when_no_draft_returns(self):
        """Backward-compat: single-jurisdiction states with only draft_return."""
        state = GraphState(
            draft_return=DraftReturn(
                total_income=70_000.0,
                taxable_income=60_000.0,
                estimated_tax=12_000.0,
                estimated_refund=0.0,
            )
        )
        report = main._build_review_report(state, "")
        assert "Draft Summary" in report
        assert "70,000.00" in report

    def test_no_draft_returns_empty_message(self):
        state = GraphState()
        report = main._build_review_report(state, "")
        assert "No draft return available." in report
