"""Build filing-ready artifacts from draft returns: filled PDFs + structured outputs.

Replaces the prior pass-through stub.
"""

from __future__ import annotations

import base64
import json
from typing import Dict, List

from wealthtax_agent.filing.ca_540 import serialize_ca540
from wealthtax_agent.filing.ca_netfile import serialize_t1
from wealthtax_agent.filing.in_itr import serialize_itr
from wealthtax_agent.filing.pdf_fill import fill_form
from wealthtax_agent.filing.quarterly import quarterly_ca_instalments, quarterly_us_1040es
from wealthtax_agent.filing.us_mef import serialize_1040
from wealthtax_agent.logging_utils import get_logger
from wealthtax_agent.projection import project_future_years
from wealthtax_agent.state import DraftReturn, FilingArtifact, FormExtract, GraphState

_log = get_logger("wealthtax_agent.build_return")


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

    # Quarterly CRA instalment vouchers when net tax owing is material
    vouchers = quarterly_ca_instalments(draft, year + 1)
    for q, text in vouchers.items():
        artifacts[f"ca_instalment_{q.lower()}"] = FilingArtifact(
            jurisdiction="CA",
            form_code=f"INNS3-{q}",
            filename=f"ca_instalment_{year + 1}_{q.lower()}.txt",
            mime_type="text/plain",
            content_b64=_b64(text),
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

    # California Form 540 state-tax artifact. Gated on CA residence specifically
    # (NOT on a state line_item being present — TX/FL/WA tables load and spread
    # state_tax=0.0 into line_items, and an NY filer is state-taxed but not on a
    # 540). This carries the state tax the federal 1040 deliberately excludes.
    if (user_answers.get("state_of_residence") or "").upper() == "CA" and draft.line_items.get("state_tax", 0.0) > 0:
        ca540_json = json.dumps(serialize_ca540(draft, extracts, year, user_answers), indent=2)
        artifacts["ca_540_json"] = FilingArtifact(
            jurisdiction="US",
            form_code="CA-540",
            filename=f"ca_540_{year}_draft.json",
            mime_type="application/json",
            content_b64=_b64(ca540_json),
        )

    # 1040-ES quarterly estimated-tax vouchers (only when meaningful)
    vouchers = quarterly_us_1040es(draft, year + 1)
    for q, text in vouchers.items():
        artifacts[f"us_1040es_{q.lower()}"] = FilingArtifact(
            jurisdiction="US",
            form_code=f"1040-ES-{q}",
            filename=f"us_1040es_{year + 1}_{q.lower()}.txt",
            mime_type="text/plain",
            content_b64=_b64(text),
        )

    return artifacts


def _in_artifacts(draft: DraftReturn, extracts: List[FormExtract], year: int, user_answers: Dict[str, str]) -> Dict[str, FilingArtifact]:
    artifacts: Dict[str, FilingArtifact] = {}
    regime = "new" if draft.line_items.get("regime", 0) == 1.0 else "old"
    itr_dict = serialize_itr(draft, extracts, year, regime)
    itr_json = json.dumps(itr_dict, indent=2)
    artifacts["in_itr_json"] = FilingArtifact(
        jurisdiction="IN",
        form_code="ITR-2",
        filename=f"in_itr_{year}_draft.json",
        mime_type="application/json",
        content_b64=_b64(itr_json),
    )
    # Plain-text summary alongside the JSON for human review.
    lines: List[str] = []
    lines.append(f"India ITR Draft — Assessment Year {year} (Regime: {regime})")
    lines.append("=" * 60)
    lines.append(f"Total income:    INR {draft.totals.get('total_income', 0):,.0f}")
    lines.append(f"Taxable income:  INR {draft.totals.get('taxable_income', 0):,.0f}")
    lines.append(f"Total tax:       INR {draft.totals.get('total_tax', 0):,.0f}")
    lines.append(f"Refund / Owing:  INR {draft.totals.get('refund', 0):,.0f} / INR {draft.totals.get('balance_owing', 0):,.0f}")
    lines.append("")
    lines.append("This is a draft only. File on incometax.gov.in.")
    artifacts["in_itr_summary"] = FilingArtifact(
        jurisdiction="IN",
        form_code="ITR-SUMMARY",
        filename=f"in_itr_{year}_summary.txt",
        mime_type="text/plain",
        content_b64=_b64("\n".join(lines)),
    )
    return artifacts


def _planning_artifact(state: GraphState) -> FilingArtifact:
    """Year-over-year planning summary + 5-year tax projection."""
    year = state.filing_year or 2024
    lines: List[str] = []
    lines.append(f"WealthTax Agent — Year-over-Year Planning Summary ({year} -> {year + 1})")
    lines.append("=" * 70)
    for jurisdiction, draft in state.draft_returns.items():
        lines.append("")
        lines.append(f"[{jurisdiction}] Filed-year totals")
        lines.append(f"  Total income:     ${draft.totals.get('total_income', 0):,.2f}")
        lines.append(f"  Taxable income:   ${draft.totals.get('taxable_income', 0):,.2f}")
        lines.append(f"  Estimated tax:    ${draft.totals.get('total_tax', 0):,.2f}")
        lines.append(f"  Refund / Owing:   ${draft.totals.get('refund', 0):,.2f} / ${draft.totals.get('balance_owing', 0):,.2f}")

    lines.append("")
    lines.append("5-Year Projection (3% annual income growth)")
    lines.append("-" * 70)
    try:
        projection = project_future_years(state, growth=0.03, horizon=5)
        for jurisdiction, rows in projection.items():
            lines.append(f"\n[{jurisdiction}]")
            lines.append(f"  {'Year':<6}{'Income':>14}{'Taxable':>14}{'Total Tax':>14}{'Refund/Owing':>16}")
            for row in rows:
                ref_owe = f"${row['refund']:,.0f} / ${row['balance_owing']:,.0f}"
                lines.append(
                    f"  {row['year']:<6}${row['total_income']:>12,.0f} ${row['taxable_income']:>12,.0f} "
                    f"${row['total_tax']:>12,.0f}  {ref_owe:>14}"
                )
    except Exception as exc:
        lines.append(f"  (projection unavailable: {exc})")

    lines.append("")
    if state.optimization_suggestions:
        lines.append("Plan-ahead actions for next year:")
        for s in state.optimization_suggestions:
            badge = "NOW" if s.horizon == "now" else "FUTURE"
            lines.append(f"  [{badge:6s}] [{s.jurisdiction}] {s.title}  (~${s.est_savings:,.0f} estimated savings)")
            for step in s.action_steps:
                lines.append(f"      • {step}")
    else:
        lines.append("No specific suggestions surfaced for this filing.")
    lines.append("")
    lines.append("DRAFT — not transmitted. Use as a planning checklist.")
    return FilingArtifact(
        jurisdiction="CA" if "CA" in state.draft_returns else "US",
        form_code="PLAN",
        filename=f"wealthtax_yoy_planning_{year}.txt",
        mime_type="text/plain",
        content_b64=_b64("\n".join(lines)),
    )


def _amendment_artifacts(state: GraphState) -> Dict[str, FilingArtifact]:
    """Emit 1040-X (US) or T1-ADJ (CA) draft when ``state.is_amendment`` is set."""
    if not state.is_amendment:
        return {}
    year = state.filing_year or 2024
    out: Dict[str, FilingArtifact] = {}
    for jurisdiction, draft in state.draft_returns.items():
        prior = state.prior_filed_totals.get(jurisdiction, {})
        lines: List[str] = []
        form_code = "1040-X" if jurisdiction == "US" else "T1-ADJ"
        lines.append(f"{form_code} Amendment Worksheet ({jurisdiction} {year})")
        lines.append("=" * 60)
        lines.append(f"{'Item':<24}{'Originally Filed':>18}{'Amended':>14}{'Difference':>14}")
        for key in ("total_income", "taxable_income", "total_tax", "refund", "balance_owing"):
            original = float(prior.get(key, 0.0))
            amended = float(draft.totals.get(key, 0.0))
            diff = amended - original
            lines.append(f"{key:<24}${original:>16,.2f}  ${amended:>12,.2f}  ${diff:>+12,.2f}")
        lines.append("")
        lines.append(
            f"This is a draft of the {form_code} worksheet. Transcribe the "
            f"three-column figures onto the official {form_code} before filing."
        )
        out[f"{jurisdiction.lower()}_amendment"] = FilingArtifact(
            jurisdiction=jurisdiction,  # type: ignore[arg-type]
            form_code=form_code,
            filename=f"{jurisdiction.lower()}_{form_code.lower()}_{year}_draft.txt",
            mime_type="text/plain",
            content_b64=_b64("\n".join(lines)),
        )
    return out


def build_return_node(state: GraphState) -> GraphState:
    """Compute filing artifacts for each jurisdiction with a draft return."""
    year = state.filing_year or 2024
    user_answers = state.user_answers or {}
    artifacts: Dict[str, FilingArtifact] = dict(state.filing_artifacts)

    _log.info(
        "build_return_start",
        extra={
            "year": year,
            "jurisdictions": sorted(state.draft_returns.keys()),
        },
    )

    for jurisdiction, draft in state.draft_returns.items():
        extracts = [e for e in state.extracts if e.jurisdiction == jurisdiction]
        try:
            if jurisdiction == "CA":
                artifacts.update(_ca_artifacts(draft, extracts, year))
            elif jurisdiction == "US":
                artifacts.update(_us_artifacts(draft, extracts, year, user_answers))
            elif jurisdiction == "IN":
                artifacts.update(_in_artifacts(draft, extracts, year, user_answers))
        except Exception as exc:
            state.warnings.append(f"Filing artifact generation failed for {jurisdiction}: {exc}")
            _log.error(
                "build_return_failed",
                extra={"jurisdiction": jurisdiction, "year": year, "error": str(exc)},
            )

    if state.draft_returns:
        try:
            artifacts["yoy_planning"] = _planning_artifact(state)
        except Exception as exc:
            state.warnings.append(f"YoY planning artifact failed: {exc}")
        try:
            artifacts.update(_amendment_artifacts(state))
        except Exception as exc:
            state.warnings.append(f"Amendment artifact failed: {exc}")

    state.filing_artifacts = artifacts
    return state
