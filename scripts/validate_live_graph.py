from pathlib import Path

from wealthtax_agent.graph import build_graph
from wealthtax_agent.state import GraphState, InputDocument


EXPECTED = {
    "total_income": 86445.4,
    "rrsp_deduction": 9000.0,
    "taxable_income": 77445.4,
    "estimated_tax": 19361.35,
}


def run_case(ext: str, mime: str) -> bool:
    base = Path("sample_tax_slips")
    docs = [
        InputDocument(content=(base / f"t4_sample_2025.{ext}").read_bytes(), filename=f"t4_sample_2025.{ext}", mime_type=mime),
        InputDocument(content=(base / f"t5_sample_2025.{ext}").read_bytes(), filename=f"t5_sample_2025.{ext}", mime_type=mime),
        InputDocument(content=(base / f"rrsp_receipt_2025.{ext}").read_bytes(), filename=f"rrsp_receipt_2025.{ext}", mime_type=mime),
    ]

    # Only make a live API call for the first case (PDF), mock the rest
    import wealthtax_agent.parse_docs as parse_docs
    import wealthtax_agent.explain_return as explain_return
    import wealthtax_agent.graph as graph_mod
    from wealthtax_agent.state import GraphState

    if ext != "pdf":
        # Mock OCR and LLM for non-PDF cases
        lookup = {
            docs[0].content: "Employment income (Box 14): 84500.00",
            docs[1].content: "Interest from Canadian sources (Box 13): 1325.40\nTaxable amount of eligible dividends (Box 24): 620.00",
            docs[2].content: "Total RRSP contributions: 9000.00",
        }
        parse_docs.ocr_bytes_to_text = lambda doc, _mime: lookup[doc]
        parse_docs.client = None

        # Simple explicit mock classes for explain_return.client
        class _Msg:
            def __init__(self, content):
                self.content = content
        class _Choice:
            def __init__(self, content):
                self.message = _Msg(content)
        class _Resp:
            def __init__(self, content):
                self.choices = [_Choice(content)]
        class _Completions:
            def create(self, **kwargs):
                # Return both code blocks as expected by the formatter
                mock_text = (
                    """```text\nWealthTax Agent – Draft Canadian Tax Summary (Not filed)\nTotal income: $86445.40\nRRSP deduction: $9000.00\nTaxable income: $77445.40\nEstimated tax: $19361.35\nExplanations:\n- total_income: from parsed slips\n- estimated_tax: simplified estimate\n\nDisclaimer: This is a draft from an AI prototype. It is not filed with CRA.\nYou must verify all amounts and file your tax return yourself.\n```\n\n"""
                    """```xml\n<WealthTaxDraftReturn>\n  <Meta>\n    <Version>0.1</Version>\n    <Jurisdiction>CA</Jurisdiction>\n    <Note>Prototype only - NOT CRA NETFILE compliant</Note>\n  </Meta>\n  <Summary>\n    <TotalIncome>86445.40</TotalIncome>\n    <RRSPDeduction>9000.00</RRSPDeduction>\n    <TaxableIncome>77445.40</TaxableIncome>\n    <EstimatedTax>19361.35</EstimatedTax>\n  </Summary>\n  <Explanations>\n    <Line id=\"total_income\">from parsed slips</Line>\n    <Line id=\"estimated_tax\">simplified estimate</Line>\n  </Explanations>\n</WealthTaxDraftReturn>\n```"""
                )
                return _Resp(mock_text)
        class _Chat:
            def __init__(self):
                self.completions = _Completions()
        class _Client:
            def __init__(self):
                self.chat = _Chat()
        explain_return.client = _Client()
        graph = graph_mod.build_graph()
    else:
        graph = build_graph()

    state = GraphState.model_validate(graph.invoke(GraphState(raw_docs=docs)))
    draft = state.draft_return
    if draft is None:
        print(f"{ext}: FAIL (no draft)")
        for warning in state.warnings:
            print(f"  warning={warning}")
        return False

    actual = {
        "total_income": round(draft.total_income, 2),
        "rrsp_deduction": round(draft.rrsp_deduction, 2),
        "taxable_income": round(draft.taxable_income, 2),
        "estimated_tax": round(draft.estimated_tax, 2),
    }
    checks = {key: abs(actual[key] - EXPECTED[key]) < 0.75 for key in EXPECTED}
    has_dual_outputs = bool(state.draft_summary_text) and bool(state.draft_pseudo_xml)
    passed = all(checks.values()) and len(state.slips) >= 3 and has_dual_outputs
    print(
        f"{ext}: {'PASS' if passed else 'FAIL'} slips={len(state.slips)} warnings={len(state.warnings)} "
        f"dual_outputs={has_dual_outputs}"
    )
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
    results = [run_case(ext, mime) for ext, mime in cases]
    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
