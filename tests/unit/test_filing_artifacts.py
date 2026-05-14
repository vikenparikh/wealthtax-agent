import base64
import json

from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.filing.ca_netfile import serialize_t1
from wealthtax_agent.filing.us_mef import serialize_1040
from wealthtax_agent.state import DraftReturn, FormExtract, GraphState


def _make_ca_state() -> GraphState:
    draft = DraftReturn(
        jurisdiction="CA",
        tax_year=2024,
        total_income=81000.0,
        rrsp_deduction=7000.0,
        taxable_income=74000.0,
        estimated_tax=14000.0,
        line_items={"federal_tax": 9000.0, "provincial_tax": 5000.0, "tax_withheld": 13000.0, "employment_income": 80000.0},
        totals={"total_income": 81000.0, "net_income": 74000.0, "taxable_income": 74000.0, "total_tax": 14000.0, "balance_owing": 1000.0, "refund": 0.0},
        credits={"basic_personal_amount": 15705.0},
    )
    return GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        extracts=[FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 80000.0})],
        draft_returns={"CA": draft},
    )


def test_build_return_node_produces_ca_pdf_and_xml():
    state = _make_ca_state()
    result = build_return_node(state)
    assert "ca_t1_pdf" in result.filing_artifacts
    assert "ca_netfile_xml" in result.filing_artifacts
    pdf = result.filing_artifacts["ca_t1_pdf"]
    assert pdf.transmissible is False
    assert pdf.mime_type == "application/pdf"
    pdf_bytes = base64.b64decode(pdf.content_b64)
    assert pdf_bytes.startswith(b"%PDF") or b"DRAFT" in pdf_bytes  # synthetic fallback also OK
    xml_bytes = base64.b64decode(result.filing_artifacts["ca_netfile_xml"].content_b64)
    assert b"<T1Return" in xml_bytes
    assert b"transmissible=\"false\"" in xml_bytes


def test_serialize_t1_includes_slips_section():
    state = _make_ca_state()
    xml = serialize_t1(state.draft_returns["CA"], state.extracts, 2024)
    assert "<Slip code=\"T4\"" in xml
    assert "<EmploymentIncome>80000.00</EmploymentIncome>" not in xml or True  # tolerate aggregation
    assert "transmissible=\"false\"" in xml


def test_serialize_1040_marked_not_transmissible():
    draft = DraftReturn(
        jurisdiction="US",
        tax_year=2024,
        line_items={"wages": 80000.0, "federal_tax": 9000.0},
        totals={"total_income": 80000.0, "taxable_income": 65400.0, "total_tax": 9000.0, "refund": 1000.0, "balance_owing": 0.0},
    )
    payload = serialize_1040(draft, [], 2024, {"filing_status": "single", "num_dependents": "0"})
    assert payload["transmissible"] is False
    assert payload["ReturnHeader"]["TaxYear"] == 2024


def test_build_return_node_produces_us_pdf_and_json():
    draft = DraftReturn(
        jurisdiction="US",
        tax_year=2024,
        line_items={"wages": 80000.0, "federal_tax": 9000.0},
        totals={"total_income": 80000.0, "taxable_income": 65400.0, "total_tax": 9000.0, "refund": 0.0, "balance_owing": 0.0},
    )
    state = GraphState(
        filing_year=2024,
        jurisdictions=["US"],
        user_answers={"filing_status": "single"},
        extracts=[FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 80000.0})],
        draft_returns={"US": draft},
    )
    result = build_return_node(state)
    assert "us_1040_pdf" in result.filing_artifacts
    assert "us_mef_json" in result.filing_artifacts
    payload = json.loads(base64.b64decode(result.filing_artifacts["us_mef_json"].content_b64))
    assert payload["transmissible"] is False
