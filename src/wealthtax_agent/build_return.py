"""Build filing-ready artifacts from draft returns: filled PDFs + structured outputs.

Replaces the prior pass-through stub.
"""

from __future__ import annotations

import base64
import json
from typing import Dict, List

from wealthtax_agent.filing.ca_netfile import serialize_t1
from wealthtax_agent.filing.pdf_fill import fill_form
from wealthtax_agent.filing.us_mef import serialize_1040
from wealthtax_agent.state import DraftReturn, FilingArtifact, FormExtract, GraphState


def _b64(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(data).decode("utf-8")


def _ca_artifacts(draft: DraftReturn, extracts: List[FormExtract], year: int) -> Dict[str, FilingArtifact]:
    artifacts: Dict[str, FilingArtifact] = {}

    # T1 summary PDF
    pdf_bytes = fill_form("ca", year, "T1", {
        "total_income": f"{draft.totals.get('total_income', 0.0):.2f}",
        "net_income": f"{draft.totals.get('net_income', 0.0):.2f}",
        "taxable_income": f"{draft.totals.get('taxable_income', 0.0):.2f}",
        "federal_tax": f"{draft.line_items.get('federal_tax', 0.0):.2f}",
        "provincial_tax": f"{draft.line_items.get('provincial_tax', 0.0):.2f}",
        "balance_owing": f"{draft.totals.get('balance_owing', 0.0):.2f}",
        "refund": f"{draft.totals.get('refund', 0.0):.2f}",
    })
    artifacts["ca_t1_pdf"] = FilingArtifact(
        jurisdiction="CA",
        form_code="T1",
        filename=f"ca_t1_{year}_draft.pdf",
        mime_type="application/pdf",
        content_b64=_b64(pdf_bytes),
    )

    # NETFILE-shaped XML
    xml_str = serialize_t1(draft, extracts, year)
    artifacts["ca_netfile_xml"] = FilingArtifact(
        jurisdiction="CA",
        form_code="T1-XML",
        filename=f"ca_t1_{year}_draft.xml",
        mime_type="application/xml",
        content_b64=_b64(xml_str),
    )

    return artifacts


def _us_artifacts(draft: DraftReturn, extracts: List[FormExtract], year: int, user_answers: Dict[str, str]) -> Dict[str, FilingArtifact]:
    artifacts: Dict[str, FilingArtifact] = {}

    pdf_bytes = fill_form("us", year, "1040", {
        "total_income": f"{draft.totals.get('total_income', 0.0):.2f}",
        "agi": f"{draft.totals.get('agi', 0.0):.2f}",
        "taxable_income": f"{draft.totals.get('taxable_income', 0.0):.2f}",
        "federal_tax": f"{draft.line_items.get('federal_tax', 0.0):.2f}",
        "self_employment_tax": f"{draft.line_items.get('self_employment_tax', 0.0):.2f}",
        "balance_owing": f"{draft.totals.get('balance_owing', 0.0):.2f}",
        "refund": f"{draft.totals.get('refund', 0.0):.2f}",
        "filing_status": user_answers.get("filing_status", "single"),
    })
    artifacts["us_1040_pdf"] = FilingArtifact(
        jurisdiction="US",
        form_code="1040",
        filename=f"us_1040_{year}_draft.pdf",
        mime_type="application/pdf",
        content_b64=_b64(pdf_bytes),
    )

    mef_dict = serialize_1040(draft, extracts, year, user_answers)
    mef_json = json.dumps(mef_dict, indent=2)
    artifacts["us_mef_json"] = FilingArtifact(
        jurisdiction="US",
        form_code="1040-MeF",
        filename=f"us_1040_{year}_mef_draft.json",
        mime_type="application/json",
        content_b64=_b64(mef_json),
    )

    return artifacts


def build_return_node(state: GraphState) -> GraphState:
    """Compute filing artifacts for each jurisdiction with a draft return."""
    year = state.filing_year or 2024
    user_answers = state.user_answers or {}
    artifacts: Dict[str, FilingArtifact] = dict(state.filing_artifacts)

    for jurisdiction, draft in state.draft_returns.items():
        extracts = [e for e in state.extracts if e.jurisdiction == jurisdiction]
        try:
            if jurisdiction == "CA":
                artifacts.update(_ca_artifacts(draft, extracts, year))
            elif jurisdiction == "US":
                artifacts.update(_us_artifacts(draft, extracts, year, user_answers))
        except Exception as exc:
            state.warnings.append(f"Filing artifact generation failed for {jurisdiction}: {exc}")

    state.filing_artifacts = artifacts
    return state
