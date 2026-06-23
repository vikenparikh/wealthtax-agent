"""Regression: ``_planning_artifact`` must label the YoY planning artifact with a
jurisdiction that ACTUALLY has a draft, honouring CA > US > IN precedence.

Bug (rung-3): an IN-only filer wrongly received ``jurisdiction="US"`` because the
expression was ``"CA" if "CA" in draft_returns else "US"`` — falling through to
"US" even when no US draft existed.
"""

import pytest

from wealthtax_agent.build_return import _planning_artifact
from wealthtax_agent.state import DraftReturn, GraphState


def _state(*jurisdictions):
    drafts = {
        j: DraftReturn(
            jurisdiction=j,
            totals={"total_income": 80000, "taxable_income": 70000, "total_tax": 12000},
        )
        for j in jurisdictions
    }
    return GraphState(filing_year=2024, draft_returns=drafts)


@pytest.mark.parametrize(
    "present, expected",
    [
        (("IN",), "IN"),        # was wrongly "US" before the fix
        (("CA",), "CA"),        # regression guard
        (("US",), "US"),        # regression guard
        (("CA", "US"), "CA"),   # CA precedence preserved
        (("US", "IN"), "US"),   # US precedence over IN preserved
    ],
)
def test_planning_artifact_jurisdiction_is_a_present_draft(present, expected):
    art = _planning_artifact(_state(*present))
    assert art.jurisdiction == expected
