"""Generate quarterly estimated-tax voucher artifacts.

US: 1040-ES quarterly vouchers (Q1: Apr 15, Q2: Jun 15, Q3: Sep 15, Q4: Jan 15
next year).
CA: CRA personal instalment notices (Mar 15, Jun 15, Sep 15, Dec 15).

Both are emitted as plain-text drafts (and a simple PDF via the existing
filler) so the self-employed user has something concrete to pay with.
"""

from __future__ import annotations

from typing import Dict, List

from wealthtax_agent.state import DraftReturn


def _quarter_due_dates_us(year: int) -> List[str]:
    return [
        f"{year}-04-15",
        f"{year}-06-15",
        f"{year}-09-15",
        f"{year + 1}-01-15",
    ]


def _quarter_due_dates_ca(year: int) -> List[str]:
    return [
        f"{year}-03-15",
        f"{year}-06-15",
        f"{year}-09-15",
        f"{year}-12-15",
    ]


def quarterly_us_1040es(draft: DraftReturn, year: int) -> Dict[str, str]:
    """Return a dict[quarter_label] -> human-readable voucher text.

    Self-employment income above a small threshold typically triggers
    quarterly estimated taxes. We size each voucher at 25% of the year's
    estimated federal + state + SE tax.
    """
    total_tax = float(draft.totals.get("total_tax", 0.0))
    se_tax = float(draft.line_items.get("self_employment_tax", 0.0))
    withholding = float(draft.line_items.get("tax_withheld", 0.0))
    annual_owed = max(0.0, total_tax - withholding)

    # If withholding already covers >= total tax, no voucher needed.
    if annual_owed <= 1000 and se_tax <= 1000:
        return {}

    quarter_amount = round(annual_owed / 4.0, 2)
    dates = _quarter_due_dates_us(year)
    vouchers: Dict[str, str] = {}
    for idx, due in enumerate(dates, start=1):
        vouchers[f"Q{idx}"] = (
            f"Form 1040-ES Voucher Q{idx} ({due})\n"
            f"Estimated payment: ${quarter_amount:,.2f}\n"
            f"Year-to-date federal tax estimate: ${total_tax:,.2f}\n"
            f"Self-employment tax (informational): ${se_tax:,.2f}\n"
            f"Prior withholding (W-2 + 1099 boxes): ${withholding:,.2f}\n"
            "Mail with check to the address in the 1040-ES instructions, or pay "
            "electronically at https://www.irs.gov/payments. DRAFT — not transmitted."
        )
    return vouchers


def quarterly_ca_instalments(draft: DraftReturn, year: int) -> Dict[str, str]:
    """CRA personal tax-instalment notices for self-employed Canadians.

    CRA requires instalments when net tax owing > $3,000 in the current and
    one of the prior two years. We approximate by triggering instalments
    whenever the draft return shows > $3,000 owing or significant
    self-employment / rental income.
    """
    balance_owing = float(draft.totals.get("balance_owing", 0.0))
    self_emp = (
        float(draft.line_items.get("net_business_income", 0.0))
        + float(draft.line_items.get("other_self_employment", 0.0))
    )
    if balance_owing <= 3000 and self_emp <= 5000:
        return {}

    quarter_amount = round(balance_owing / 4.0, 2) if balance_owing else round(self_emp * 0.25 / 4.0, 2)
    dates = _quarter_due_dates_ca(year)
    vouchers: Dict[str, str] = {}
    for idx, due in enumerate(dates, start=1):
        vouchers[f"Q{idx}"] = (
            f"CRA Personal Instalment Voucher Q{idx} ({due})\n"
            f"Suggested instalment: ${quarter_amount:,.2f}\n"
            f"Year-to-date balance owing (estimated): ${balance_owing:,.2f}\n"
            "Pay through CRA My Account, online banking, or by mailing the "
            "INNS3 voucher. DRAFT — not transmitted."
        )
    return vouchers
