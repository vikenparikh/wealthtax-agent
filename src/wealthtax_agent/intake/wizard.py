"""Build ``FormExtract`` objects from manually-typed values.

Each supported intake form lists the fields the engine actually consumes
(see ``engines/ca_engine.py`` and ``engines/us_engine.py``). The wizard
validates types and snaps the result into the same shape OCR-driven
extracts produce, so downstream code can't tell the difference.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from wealthtax_agent.state import FormExtract


class FieldSpec(TypedDict, total=False):
    name: str
    label: str
    kind: str  # "number" | "text" | "choice"
    options: List[str]
    required: bool


def _f(name: str, label: str, *, kind: str = "number", required: bool = False, options: Optional[List[str]] = None) -> FieldSpec:
    spec: FieldSpec = {"name": name, "label": label, "kind": kind, "required": required}
    if options:
        spec["options"] = options
    return spec


# Field specs per supported intake form. Engines already know how to consume
# every field listed here, so a fully populated manual entry is equivalent to
# the rule-based extractor running against an uploaded slip.
SUPPORTED_INTAKE_FORMS: Dict[str, Dict[str, Any]] = {
    # Canada
    "T4": {
        "jurisdiction": "CA",
        "fields": [
            _f("employment_income", "Box 14 — Employment income", required=True),
            _f("income_tax_deducted", "Box 22 — Income tax deducted"),
            _f("cpp_contributions", "Box 16 — CPP contributions"),
            _f("ei_premiums", "Box 18 — EI premiums"),
            _f("rpp_contributions", "Box 20 — RPP contributions"),
            _f("union_dues", "Box 44 — Union dues"),
        ],
    },
    "T5": {
        "jurisdiction": "CA",
        "fields": [
            _f("interest_income", "Box 13 — Interest from Canadian sources"),
            _f("taxable_eligible_dividends", "Box 25 — Taxable amount of eligible dividends"),
            _f("actual_non_eligible_dividends", "Box 10 — Actual non-eligible dividends"),
        ],
    },
    "RRSP": {
        "jurisdiction": "CA",
        "fields": [
            _f("rrsp_contributions", "Total RRSP contributions", required=True),
            _f("first_60_days_contribution", "First-60-days contribution"),
        ],
    },
    "T2202": {
        "jurisdiction": "CA",
        "fields": [
            _f("eligible_tuition_fees", "Eligible tuition fees", required=True),
            _f("full_time_months", "Full-time months"),
            _f("part_time_months", "Part-time months"),
        ],
    },
    "T776": {
        "jurisdiction": "CA",
        "fields": [
            _f("gross_rental_income", "Gross rental income"),
            _f("total_expenses", "Total expenses"),
            _f("net_rental_income", "Net rental income", required=True),
        ],
    },
    "T2125": {
        "jurisdiction": "CA",
        "fields": [
            _f("gross_business_income", "Gross business income"),
            _f("total_expenses", "Total expenses"),
            _f("net_business_income", "Net business income", required=True),
        ],
    },

    # United States
    "W-2": {
        "jurisdiction": "US",
        "fields": [
            _f("wages", "Box 1 — Wages, tips, other compensation", required=True),
            _f("federal_income_tax_withheld", "Box 2 — Federal income tax withheld"),
            _f("social_security_wages", "Box 3 — Social security wages"),
            _f("medicare_wages", "Box 5 — Medicare wages"),
            _f("state_wages", "Box 16 — State wages"),
            _f("state_income_tax", "Box 17 — State income tax"),
        ],
    },
    "1099-INT": {
        "jurisdiction": "US",
        "fields": [
            _f("interest_income", "Box 1 — Interest income", required=True),
            _f("us_treasury_interest", "Box 3 — US Treasury interest"),
            _f("federal_income_tax_withheld", "Box 4 — Federal income tax withheld"),
        ],
    },
    "1099-DIV": {
        "jurisdiction": "US",
        "fields": [
            _f("ordinary_dividends", "Box 1a — Total ordinary dividends", required=True),
            _f("qualified_dividends", "Box 1b — Qualified dividends"),
            _f("capital_gain_distributions", "Box 2a — Capital gain distributions"),
        ],
    },
    "1099-NEC": {
        "jurisdiction": "US",
        "fields": [
            _f("nonemployee_compensation", "Box 1 — Nonemployee compensation", required=True),
            _f("federal_income_tax_withheld", "Box 4 — Federal income tax withheld"),
        ],
    },
    "1099-R": {
        "jurisdiction": "US",
        "fields": [
            _f("gross_distribution", "Box 1 — Gross distribution", required=True),
            _f("taxable_amount", "Box 2a — Taxable amount"),
            _f("federal_income_tax_withheld", "Box 4 — Federal income tax withheld"),
        ],
    },
    "SCH-C": {
        "jurisdiction": "US",
        "fields": [
            _f("gross_receipts", "Gross receipts"),
            _f("total_expenses", "Total expenses"),
            _f("net_profit", "Net profit", required=True),
        ],
    },
    "1098-E": {
        "jurisdiction": "US",
        "fields": [
            _f("student_loan_interest", "Box 1 — Student loan interest paid", required=True),
        ],
    },

    # India
    "FORM-16": {
        "jurisdiction": "IN",
        "fields": [
            _f("gross_salary", "Gross salary", required=True),
            _f("basic_salary", "Basic salary"),
            _f("hra_received", "HRA received"),
            _f("standard_deduction_salary", "Standard deduction"),
            _f("section_80c_declared", "Section 80C declared"),
            _f("section_80d_declared", "Section 80D declared"),
            _f("tds_deducted", "TDS deducted"),
        ],
    },
    "FORM-16A": {
        "jurisdiction": "IN",
        "fields": [
            _f("interest_income", "Interest income"),
            _f("dividend_income", "Dividend income"),
            _f("tds_deducted", "TDS deducted", required=True),
        ],
    },
    "INVESTMENTS-80C": {
        "jurisdiction": "IN",
        "fields": [
            _f("amount", "Section 80C investment total (PPF + ELSS + LIC + EPF + principal)", required=True),
        ],
    },
    "MEDICAL-80D": {
        "jurisdiction": "IN",
        "fields": [
            _f("self_premium", "Health insurance premium — self/family", required=True),
            _f("parents_premium", "Health insurance premium — parents"),
        ],
    },
    "STOCK-GAIN": {
        "jurisdiction": "IN",
        "fields": [
            _f("stcg_equity_pre_change", "STCG equity pre 23-Jul-2024"),
            _f("stcg_equity_post_change", "STCG equity post 23-Jul-2024"),
            _f("ltcg_equity_pre_change", "LTCG equity pre 23-Jul-2024"),
            _f("ltcg_equity_post_change", "LTCG equity post 23-Jul-2024"),
            _f("stcg_other_pre_change", "STCG other pre 23-Jul-2024"),
            _f("ltcg_other_pre_change", "LTCG other pre 23-Jul-2024"),
        ],
    },
}


def field_spec_for(form_code: str) -> List[FieldSpec]:
    return list(SUPPORTED_INTAKE_FORMS.get(form_code.upper(), {}).get("fields", []))


def manual_extract(form_code: str, values: Dict[str, Any], *, source_filename: Optional[str] = None) -> FormExtract:
    """Build a ``FormExtract`` from a dict of user-supplied values.

    Unknown form codes raise ``ValueError`` so callers fail fast.
    """
    spec = SUPPORTED_INTAKE_FORMS.get(form_code.upper())
    if spec is None:
        raise ValueError(f"Form {form_code} is not in the manual intake set; upload it instead.")

    field_names = {f["name"] for f in spec["fields"]}
    cleaned: Dict[str, float] = {}
    for name, value in values.items():
        if name not in field_names or value in (None, ""):
            continue
        try:
            cleaned[name] = float(str(value).replace(",", "").replace("$", "").strip())
        except (TypeError, ValueError):
            continue

    return FormExtract(
        form_code=form_code.upper(),
        jurisdiction=spec["jurisdiction"],
        fields=cleaned,
        source_filename=source_filename or f"manual-{form_code.lower()}",
        extractor="rule",
        confidence="high" if cleaned else "low",
    )


# ---------------------------------------------------------------------------
# 5-step intake wizard state machine
# ---------------------------------------------------------------------------

WIZARD_STEPS: List[str] = [
    "jurisdiction_year",   # step 1: jurisdiction(s) + filing year
    "residency_days",      # step 2: days per jurisdiction
    "income_sources",      # step 3: income sources per jurisdiction
    "deductions_credits",  # step 4: deductions + credits
    "review_submit",       # step 5: review + submit
]

WIZARD_STEP_COUNT = len(WIZARD_STEPS)


class WizardState:
    """Mutable wizard state that can be persisted as a plain dict.

    The state is intentionally free-form so it can accumulate partial data as
    the user moves through steps.  ``to_dict()`` / ``from_dict()`` are used
    for DB persistence via ``TaxReturn.fields``.
    """

    def __init__(self, *, step: int = 0, data: Optional[Dict[str, Any]] = None) -> None:
        if not (0 <= step < WIZARD_STEP_COUNT):
            raise ValueError(f"step must be 0-{WIZARD_STEP_COUNT - 1}, got {step}")
        self.step: int = step
        self.data: Dict[str, Any] = data or {}

    # ---- navigation ----

    def can_advance(self) -> bool:
        return self.step < WIZARD_STEP_COUNT - 1

    def can_go_back(self) -> bool:
        return self.step > 0

    def advance(self, step_data: Dict[str, Any]) -> "WizardState":
        """Return a *new* WizardState advanced by one step with merged data."""
        if not self.can_advance():
            raise ValueError("Already on the last step; cannot advance further.")
        merged = {**self.data, **step_data}
        return WizardState(step=self.step + 1, data=merged)

    def go_back(self) -> "WizardState":
        """Return a *new* WizardState at the previous step."""
        if not self.can_go_back():
            raise ValueError("Already on the first step; cannot go back.")
        return WizardState(step=self.step - 1, data=self.data)

    def update_data(self, partial: Dict[str, Any]) -> "WizardState":
        """Return a *new* WizardState with additional data merged (same step)."""
        return WizardState(step=self.step, data={**self.data, **partial})

    # ---- current step label ----

    @property
    def current_step_name(self) -> str:
        return WIZARD_STEPS[self.step]

    @property
    def progress_label(self) -> str:
        return f"{self.step + 1}/{WIZARD_STEP_COUNT}"

    # ---- serialisation ----

    def to_dict(self) -> Dict[str, Any]:
        return {"wizard_step": self.step, "wizard_data": self.data}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WizardState":
        return cls(step=d.get("wizard_step", 0), data=d.get("wizard_data") or {})

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WizardState):
            return NotImplemented
        return self.step == other.step and self.data == other.data

    def __repr__(self) -> str:
        return f"WizardState(step={self.step}, data={self.data!r})"


# ---------------------------------------------------------------------------
# DB persistence helpers (thin wrappers — keep repo.py as the only query site)
# ---------------------------------------------------------------------------

def save_wizard_draft(
    session,
    *,
    user_id: str,
    return_id: Optional[str],
    wizard: WizardState,
    filing_year: int,
    jurisdictions: List[str],
) -> "Any":
    """Upsert a TaxReturn draft for the wizard state.

    If ``return_id`` is None a new row is created; otherwise the existing row
    is updated in-place.  Returns the (possibly new) ``TaxReturn`` ORM object.
    """
    from wealthtax_agent.db.models import TaxReturn  # local import avoids circular

    if return_id is not None:
        tr = session.get(TaxReturn, return_id)
        if tr is not None and tr.user_id == user_id:
            tr.fields = wizard.to_dict()
            tr.jurisdictions_json = jurisdictions
            tr.filing_year = filing_year
            tr.status = "draft"
            session.flush()
            return tr

    tr = TaxReturn(
        user_id=user_id,
        filing_year=filing_year,
        jurisdictions_json=jurisdictions,
        status="draft",
        fields=wizard.to_dict(),
    )
    session.add(tr)
    session.flush()
    return tr


def load_wizard_draft(session, *, return_id: str, user_id: str) -> Optional[WizardState]:
    """Load a wizard draft from the DB; returns None if not found or unauthorised."""
    from wealthtax_agent.db.models import TaxReturn

    tr = session.get(TaxReturn, return_id)
    if tr is None or tr.user_id != user_id:
        return None
    if not tr.fields:
        return WizardState()
    return WizardState.from_dict(tr.fields)
