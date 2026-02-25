import os
import shutil
from pathlib import Path

from wealthtax_agent.parse_docs import parse_docs_node
from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import GraphState, InputDocument


EXPECTED = {
    "total_income": 86445.4,
    "rrsp_deduction": 9000.0,
    "taxable_income": 77445.4,
    "estimated_tax": 19361.35,
}


def _run_case(ext: str, mime_type: str) -> bool:
    base = Path("sample_tax_slips")
    docs = [
        InputDocument(content=(base / f"t4_sample_2025.{ext}").read_bytes(), filename=f"t4_sample_2025.{ext}", mime_type=mime_type),
        InputDocument(content=(base / f"t5_sample_2025.{ext}").read_bytes(), filename=f"t5_sample_2025.{ext}", mime_type=mime_type),
        InputDocument(
            content=(base / f"rrsp_receipt_2025.{ext}").read_bytes(),
            filename=f"rrsp_receipt_2025.{ext}",
            mime_type=mime_type,
        ),
    ]

    # Only make a live API call for the first case (PDF), mock the rest
    if ext != "pdf":
        import wealthtax_agent.parse_docs as parse_docs
        lookup = {
            docs[0].content: "Employment income (Box 14): 84500.00",
            docs[1].content: "Interest from Canadian sources (Box 13): 1325.40\nTaxable amount of eligible dividends (Box 24): 620.00",
            docs[2].content: "Total RRSP contributions: 9000.00",
        }
        parse_docs.ocr_bytes_to_text = lambda doc, _mime: lookup[doc]
        parse_docs.client = None
    state = GraphState(raw_docs=docs)
    state = parse_docs_node(state)
    state = reason_tax_node(state)
    draft = state.draft_return
    if draft is None:
        print(f"{ext}: FAIL (no draft) warnings={state.warnings}")
        return False

    actual = {
        "total_income": round(draft.total_income, 2),
        "rrsp_deduction": round(draft.rrsp_deduction, 2),
        "taxable_income": round(draft.taxable_income, 2),
        "estimated_tax": round(draft.estimated_tax, 2),
    }
    checks = {k: abs(actual[k] - EXPECTED[k]) < 0.75 for k in EXPECTED}
    passed = all(checks.values()) and len(state.slips) >= 3
    status = "PASS" if passed else "FAIL"
    print(f"{ext}: {status} slips={len(state.slips)} warnings={len(state.warnings)}")
    print(f"  actual={actual}")
    if state.warnings:
        for warning in state.warnings:
            print(f"  warning={warning}")
    return passed


def main() -> None:
    cases = [
        ("pdf", "application/pdf"),
        ("png", "image/png"),
        ("jpg", "image/jpeg"),
        ("jpeg", "image/jpeg"),
    ]

    local_only = os.getenv("LOCAL_OCR_ONLY", "false").strip().lower() in {"1", "true", "yes", "on"}
    if local_only and shutil.which("tesseract") is None:
        print("LOCAL_OCR_ONLY is enabled and tesseract is unavailable; validating PDF flow only.")
        cases = [("pdf", "application/pdf")]

    results = [_run_case(ext, mime) for ext, mime in cases]
    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
