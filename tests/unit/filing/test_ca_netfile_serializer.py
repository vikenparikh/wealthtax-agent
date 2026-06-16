"""Dedicated tests for the CA NETFILE XML serializer (filing/ca_netfile.py).

serialize_t1 was only spot-checked in test_filing_artifacts.py (one slip
assertion). These tests pin: XML well-formedness + root attributes, the
Income/Tax/Taxable field mapping across line_items/totals/credits, the
CA-only slip filter, the empty-slips placeholder, and — the reason this
file also touches production — that quote/ampersand characters in a
user-uploaded filename or form code are escaped so the XML stays valid
(serialize_t1 previously used saxutils.escape, which does not escape the
double-quote used to delimit attributes).
"""

import xml.etree.ElementTree as ET

from wealthtax_agent.filing.ca_netfile import SCHEMA_VERSION, serialize_t1
from wealthtax_agent.state import DraftReturn, FormExtract


def _draft(line_items=None, totals=None, credits=None):
    return DraftReturn(
        jurisdiction="CA",
        line_items=line_items or {},
        totals=totals or {},
        credits=credits or {},
    )


def test_output_is_well_formed_xml_with_root_attributes():
    root = ET.fromstring(serialize_t1(_draft(), [], 2025))
    assert root.tag == "T1Return"
    assert root.attrib["transmissible"] == "false"
    assert root.attrib["taxYear"] == "2025"
    assert root.attrib["schemaVersion"] == SCHEMA_VERSION


def test_income_section_maps_line_items_and_totals():
    draft = _draft(
        line_items={
            "employment_income": 84500.0,
            "interest_income": 1325.4,
            "taxable_eligible_dividends": 620.0,
        },
        totals={"total_income": 86445.4},
    )
    inc = ET.fromstring(serialize_t1(draft, [], 2025)).find("Income")
    assert inc.find("EmploymentIncome").text == "84500.00"
    assert inc.find("InterestIncome").text == "1325.40"
    assert inc.find("TaxableEligibleDividends").text == "620.00"
    assert inc.find("TotalIncome").text == "86445.40"


def test_tax_section_pulls_from_line_items_totals_and_credits():
    draft = _draft(
        line_items={"federal_tax": 12000.0, "provincial_tax": 5000.0, "tax_withheld": 19250.0},
        totals={"balance_owing": 0.0, "refund": 2250.0},
        credits={"basic_personal_amount": 15705.0},
    )
    tax = ET.fromstring(serialize_t1(draft, [], 2025)).find("Tax")
    assert tax.find("FederalTax").text == "12000.00"
    assert tax.find("ProvincialTax").text == "5000.00"
    assert tax.find("BasicPersonalAmount").text == "15705.00"
    assert tax.find("TaxWithheld").text == "19250.00"
    assert tax.find("Refund").text == "2250.00"


def test_missing_values_default_to_zero_formatted_to_cents():
    root = ET.fromstring(serialize_t1(_draft(), [], 2025))
    assert root.find("Income/EmploymentIncome").text == "0.00"
    assert root.find("Taxable/TaxableIncome").text == "0.00"
    assert root.find("Tax/BalanceOwing").text == "0.00"


def test_slips_section_includes_only_ca_slips():
    extracts = [
        FormExtract(form_code="T4", jurisdiction="CA", source_filename="t4.pdf",
                    fields={"employment_income": 84500.0}),
        FormExtract(form_code="W-2", jurisdiction="US", source_filename="w2.pdf",
                    fields={"wages": 50000.0}),
        FormExtract(form_code="FORM-16", jurisdiction="IN", source_filename="f16.pdf",
                    fields={"gross_salary": 100000.0}),
    ]
    slips = ET.fromstring(serialize_t1(_draft(), extracts, 2025)).find("Slips").findall("Slip")
    assert len(slips) == 1
    assert slips[0].attrib["code"] == "T4"
    assert slips[0].attrib["source"] == "t4.pdf"
    field = slips[0].find("Field")
    assert field.attrib["name"] == "employment_income"
    assert field.text == "84500.00"


def test_empty_slips_emits_placeholder_and_stays_well_formed():
    xml = serialize_t1(_draft(), [], 2025)
    assert "<!-- no slips -->" in xml
    ET.fromstring(xml)  # must not raise


def test_special_chars_in_slip_attributes_stay_valid_xml():
    # A user-uploaded filename / form code with " & < > must not break the XML.
    # (The old saxutils.escape left the attribute-delimiting quote unescaped.)
    extracts = [
        FormExtract(
            form_code='T4 & <Co>',
            jurisdiction="CA",
            source_filename='quarterly "final".pdf',
            fields={"odd<&>name": 100.0},
        )
    ]
    xml = serialize_t1(_draft(), extracts, 2025)
    root = ET.fromstring(xml)  # would raise on the old unescaped-quote output
    slip = root.find("Slips/Slip")
    assert slip.attrib["code"] == "T4 & <Co>"
    assert slip.attrib["source"] == 'quarterly "final".pdf'
    assert slip.find("Field").attrib["name"] == "odd<&>name"
    # The dangerous ampersand/angle brackets are entity-escaped in the raw payload.
    assert "&amp;" in xml
    assert "T4 & <Co>" not in xml


def test_tax_section_includes_canada_workers_benefit():
    """The refundable Canada Workers Benefit (Schedule 6) is credited as a payment in
    the engine balance, but the NETFILE Tax block previously omitted it — so a reader
    summing the artifact's own lines could not reconcile to the emitted Refund.

    $1,200 fed + $400 prov tax, $1,500 withheld, $1,400 CWB → refund $1,700.

    FAILS before: no <CanadaWorkersBenefit> element."""
    draft = _draft(
        line_items={"federal_tax": 800.0, "provincial_tax": 400.0, "tax_withheld": 1500.0,
                    "canada_workers_benefit": 1400.0},
        totals={"balance_owing": 0.0, "refund": 1700.0},
    )
    tax = ET.fromstring(serialize_t1(draft, [], 2025)).find("Tax")
    assert tax.find("CanadaWorkersBenefit").text == "1400.00"
    # Visible-line reconciliation: tax - withheld - cwb = -refund
    total_tax = float(tax.find("FederalTax").text) + float(tax.find("ProvincialTax").text)
    withheld = float(tax.find("TaxWithheld").text)
    cwb = float(tax.find("CanadaWorkersBenefit").text)
    assert round(total_tax - withheld - cwb, 2) == -float(tax.find("Refund").text)


def test_canada_workers_benefit_reconciles_when_still_owing():
    # $3,000 tax, $0 withheld, $600 CWB → still owes $2,400; visible lines reconcile.
    draft = _draft(
        line_items={"federal_tax": 2000.0, "provincial_tax": 1000.0, "tax_withheld": 0.0,
                    "canada_workers_benefit": 600.0},
        totals={"balance_owing": 2400.0, "refund": 0.0},
    )
    tax = ET.fromstring(serialize_t1(draft, [], 2025)).find("Tax")
    assert tax.find("CanadaWorkersBenefit").text == "600.00"
    total_tax = float(tax.find("FederalTax").text) + float(tax.find("ProvincialTax").text)
    cwb = float(tax.find("CanadaWorkersBenefit").text)
    assert round(total_tax - 0.0 - cwb, 2) == float(tax.find("BalanceOwing").text)


def test_canada_workers_benefit_defaults_to_zero_when_absent():
    # No CWB key (non-resident / year without a cwb table) → 0.00, no regression.
    tax = ET.fromstring(serialize_t1(_draft(), [], 2025)).find("Tax")
    assert tax.find("CanadaWorkersBenefit").text == "0.00"


def test_income_section_surfaces_dropped_income_components():
    """The <Income> block previously omitted several components the engine folds into
    total_income (RRSP/RRIF withdrawals, T4A self-employment + lump-sum, T3 trust
    income, foreign-property income), so summing the visible lines fell short of
    <TotalIncome>. They must now appear; TotalIncome stays engine-truth."""
    draft = _draft(
        line_items={
            "employment_income": 50000.0,
            "other_self_employment": 12000.0,
            "rrsp_withdrawals": 8000.0,
            "rrif_income": 15000.0,
            "lump_sum_income": 20000.0,
            "trust_other_income": 3000.0,
            "foreign_property_income": 4000.0,
        },
        totals={"total_income": 112000.0},
    )
    inc = ET.fromstring(serialize_t1(draft, [], 2025)).find("Income")
    assert inc.find("SelfEmploymentIncome").text == "12000.00"
    assert inc.find("RRSPIncome").text == "8000.00"
    assert inc.find("RRIFIncome").text == "15000.00"
    assert inc.find("LumpSumIncome").text == "20000.00"
    assert inc.find("TrustIncome").text == "3000.00"
    assert inc.find("ForeignPropertyIncome").text == "4000.00"


def test_income_breakdown_reconciles_to_total_income():
    """Once the dropped lines are surfaced, the sum of the visible income elements
    equals <TotalIncome> for a return with no other components."""
    draft = _draft(
        line_items={
            "employment_income": 50000.0,
            "rrif_income": 15000.0,
            "foreign_property_income": 4000.0,
        },
        totals={"total_income": 69000.0},
    )
    inc = ET.fromstring(serialize_t1(draft, [], 2025)).find("Income")
    visible = sum(float(inc.find(tag).text) for tag in (
        "EmploymentIncome", "InterestIncome", "TaxableEligibleDividends",
        "TaxableNonEligibleDividends", "TaxableCapitalGains", "NetRentalIncome",
        "NetBusinessIncome", "PensionIncome", "SelfEmploymentIncome", "RRSPIncome",
        "RRIFIncome", "LumpSumIncome", "TrustIncome", "ForeignPropertyIncome",
    ))
    assert round(visible, 2) == float(inc.find("TotalIncome").text)


def test_new_income_lines_default_to_zero_no_regression():
    inc = ET.fromstring(serialize_t1(_draft(), [], 2025)).find("Income")
    for tag in ("SelfEmploymentIncome", "RRSPIncome", "RRIFIncome", "LumpSumIncome",
                "TrustIncome", "ForeignPropertyIncome"):
        assert inc.find(tag).text == "0.00"
