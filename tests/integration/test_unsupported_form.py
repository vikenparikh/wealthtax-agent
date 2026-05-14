"""Documents that are not in the v1 supported list should land in
``state.unsupported_forms`` with a clear reason and next step."""

from unittest.mock import patch

import wealthtax_agent.classify_forms as classify_forms
from wealthtax_agent.classify_forms import classify_forms_node
from wealthtax_agent.state import GraphState, InputDocument


def test_unknown_form_is_marked_unsupported(monkeypatch):
    # Simulate OCR returning text from an unrelated tax form.
    monkeypatch.setattr(
        classify_forms,
        "ocr_bytes_to_text",
        lambda data, mime: "T2 Corporation Income Tax Return\nBox 250 Net income for tax purposes: 5000",
    )
    # Ensure the LLM tie-breaker doesn't rescue it.
    with patch.object(classify_forms, "_llm_classify", return_value=None):
        state = GraphState(raw_docs=[InputDocument(content=b"%PDF-1.7\n", mime_type="application/pdf", filename="t2.pdf")])
        result = classify_forms_node(state)

    assert result.classifications == []
    assert len(result.unsupported_forms) == 1
    item = result.unsupported_forms[0]
    assert item.filename == "t2.pdf"
    assert "Supported v1 forms" in item.suggested_next_step
