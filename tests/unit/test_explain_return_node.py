import wealthtax_agent.explain_return as explain_return
from wealthtax_agent.state import DraftReturn, GraphState


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
    def __init__(self, output):
        self.output = output

    def create(self, **kwargs):
        return _Resp(self.output)


class _Chat:
    def __init__(self, output):
        self.completions = _Completions(output)


class _Client:
    def __init__(self, output):
        self.chat = _Chat(output)


def test_explain_return_skips_when_no_draft():
    state = GraphState()

    result = explain_return.explain_return_node(state)

    assert result.explanation is None


def test_explain_return_sets_explanation_lines(monkeypatch):
    payload = '{"lines": {"total_income": "Your income from slips.", "estimated_tax": "Estimated from simplified tax."}}'
    monkeypatch.setattr(explain_return, "client", _Client(payload))

    state = GraphState(
        draft_return=DraftReturn(
            total_income=100.0,
            rrsp_deduction=0.0,
            taxable_income=100.0,
            estimated_tax=25.0,
            estimated_refund=0.0,
        )
    )

    result = explain_return.explain_return_node(state)

    assert result.explanation is not None
    assert "total_income" in result.explanation.lines
    assert "estimated_tax" in result.explanation.lines


def test_explain_return_falls_back_on_invalid_json(monkeypatch):
    monkeypatch.setattr(explain_return, "client", _Client("not-json"))

    state = GraphState(
        draft_return=DraftReturn(
            total_income=100.0,
            rrsp_deduction=10.0,
            taxable_income=90.0,
            estimated_tax=22.5,
            estimated_refund=0.0,
        )
    )

    result = explain_return.explain_return_node(state)

    assert result.explanation is not None
    assert "total_income" in result.explanation.lines
    assert not any("invalid explanation payload" in warning.lower() for warning in result.warnings)


def test_explain_return_redacts_sensitive_error(monkeypatch):
    class _BadCompletions:
        def create(self, **kwargs):
            raise ValueError("api_key gsk-secret exposed")

    class _BadChat:
        def __init__(self):
            self.completions = _BadCompletions()

    class _BadClient:
        def __init__(self):
            self.chat = _BadChat()

    monkeypatch.setattr(explain_return, "client", _BadClient())

    state = GraphState(
        draft_return=DraftReturn(
            total_income=100.0,
            rrsp_deduction=10.0,
            taxable_income=90.0,
            estimated_tax=22.5,
            estimated_refund=0.0,
        )
    )

    result = explain_return.explain_return_node(state)

    assert result.explanation is not None
    assert any("Model provider authentication failed. Verify GROQ_API_KEY and endpoint settings." in warning for warning in result.warnings)


def test_generate_dual_outputs_sets_text_and_xml(monkeypatch):
    content = (
        "```text\nWealthTax Agent – Draft Canadian Tax Summary (Not filed)\n```\n\n"
        "```xml\n<WealthTaxDraftReturn></WealthTaxDraftReturn>\n```"
    )
    monkeypatch.setattr(explain_return, "client", _Client(content))

    state = GraphState(
        draft_return=DraftReturn(
            total_income=100.0,
            rrsp_deduction=10.0,
            taxable_income=90.0,
            estimated_tax=22.5,
            estimated_refund=0.0,
        ),
        explanation=explain_return.Explanation(lines={"total_income": "ok"}),
    )

    result = explain_return.generate_dual_outputs(state)

    assert result.draft_summary_text is not None
    assert "Draft Canadian Tax Summary" in result.draft_summary_text
    assert result.draft_pseudo_xml is not None
    assert result.draft_pseudo_xml.startswith("<WealthTaxDraftReturn>")


def test_generate_dual_outputs_falls_back_when_missing_code_blocks(monkeypatch):
    monkeypatch.setattr(explain_return, "client", _Client("invalid output"))

    state = GraphState(
        draft_return=DraftReturn(
            total_income=100.0,
            rrsp_deduction=10.0,
            taxable_income=90.0,
            estimated_tax=22.5,
            estimated_refund=0.0,
        ),
        explanation=explain_return.Explanation(lines={"total_income": "ok"}),
    )

    result = explain_return.generate_dual_outputs(state)

    assert result.draft_summary_text is not None
    assert result.draft_pseudo_xml is not None
    assert any("Output formatting fallback used:" in warning for warning in result.warnings)
