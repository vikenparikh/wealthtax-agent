"""Build a CRA-NETFILE-shaped XML draft. NOT certified for transmission."""

from __future__ import annotations

from typing import List
from xml.sax.saxutils import quoteattr

from wealthtax_agent.state import DraftReturn, FormExtract


SCHEMA_VERSION = "0.1-draft"


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def serialize_t1(draft: DraftReturn, extracts: List[FormExtract], year: int) -> str:
    line_items = draft.line_items or {}
    totals = draft.totals or {}
    credits = draft.credits or {}

    slips_xml: List[str] = []
    for e in extracts:
        if e.jurisdiction != "CA":
            continue
        fields_xml = "\n".join(
            f"      <Field name={quoteattr(k)}>{_fmt(float(v))}</Field>"
            for k, v in e.fields.items()
        )
        slips_xml.append(
            f"    <Slip code={quoteattr(e.form_code)} source={quoteattr(e.source_filename or '')}>\n"
            f"{fields_xml}\n"
            "    </Slip>"
        )

    return (
        f"<T1Return transmissible=\"false\" schemaVersion=\"{SCHEMA_VERSION}\" taxYear=\"{year}\">\n"
        "  <Meta>\n"
        "    <Jurisdiction>CA</Jurisdiction>\n"
        f"    <Year>{year}</Year>\n"
        "    <Note>Prototype draft only. NOT CRA NETFILE certified. Do not transmit.</Note>\n"
        "  </Meta>\n"
        "  <Income>\n"
        f"    <EmploymentIncome>{_fmt(line_items.get('employment_income', 0.0))}</EmploymentIncome>\n"
        f"    <InterestIncome>{_fmt(line_items.get('interest_income', 0.0))}</InterestIncome>\n"
        f"    <TaxableEligibleDividends>{_fmt(line_items.get('taxable_eligible_dividends', 0.0))}</TaxableEligibleDividends>\n"
        f"    <TaxableNonEligibleDividends>{_fmt(line_items.get('taxable_non_eligible_dividends', 0.0))}</TaxableNonEligibleDividends>\n"
        f"    <TaxableCapitalGains>{_fmt(line_items.get('taxable_capital_gains', 0.0))}</TaxableCapitalGains>\n"
        f"    <NetRentalIncome>{_fmt(line_items.get('net_rental_income', 0.0))}</NetRentalIncome>\n"
        f"    <NetBusinessIncome>{_fmt(line_items.get('net_business_income', 0.0))}</NetBusinessIncome>\n"
        f"    <PensionIncome>{_fmt(line_items.get('pension_income', 0.0))}</PensionIncome>\n"
        f"    <TotalIncome>{_fmt(totals.get('total_income', 0.0))}</TotalIncome>\n"
        "  </Income>\n"
        "  <Deductions>\n"
        f"    <RRSPDeduction>{_fmt(line_items.get('rrsp_deduction', 0.0))}</RRSPDeduction>\n"
        "  </Deductions>\n"
        "  <Taxable>\n"
        f"    <NetIncome>{_fmt(totals.get('net_income', 0.0))}</NetIncome>\n"
        f"    <TaxableIncome>{_fmt(totals.get('taxable_income', 0.0))}</TaxableIncome>\n"
        "  </Taxable>\n"
        "  <Tax>\n"
        f"    <FederalTax>{_fmt(line_items.get('federal_tax', 0.0))}</FederalTax>\n"
        f"    <ProvincialTax>{_fmt(line_items.get('provincial_tax', 0.0))}</ProvincialTax>\n"
        f"    <BasicPersonalAmount>{_fmt(credits.get('basic_personal_amount', 0.0))}</BasicPersonalAmount>\n"
        f"    <TaxWithheld>{_fmt(line_items.get('tax_withheld', 0.0))}</TaxWithheld>\n"
        # Refundable Canada Workers Benefit (Schedule 6) is credited as a payment in
        # the engine balance (ca_engine: balance = total_tax - tax_withheld - cwb), so
        # it must appear on the payment side here or the artifact's visible lines
        # (FederalTax + ProvincialTax - TaxWithheld - CWB) won't reconcile with the
        # emitted BalanceOwing/Refund. Defaults to 0.00 when no CWB applies — no regression.
        f"    <CanadaWorkersBenefit>{_fmt(line_items.get('canada_workers_benefit', 0.0))}</CanadaWorkersBenefit>\n"
        f"    <BalanceOwing>{_fmt(totals.get('balance_owing', 0.0))}</BalanceOwing>\n"
        f"    <Refund>{_fmt(totals.get('refund', 0.0))}</Refund>\n"
        "  </Tax>\n"
        "  <Slips>\n"
        + ("\n".join(slips_xml) if slips_xml else "    <!-- no slips -->")
        + "\n  </Slips>\n"
        "</T1Return>"
    )
