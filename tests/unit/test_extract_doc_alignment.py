"""Regression: extract_forms_node must pair each classification with the
document it actually came from, not a positional classifications[i] <->
raw_docs[i] guess.

classifications is *sparse*: documents that fail to classify (or are
unsupported) are dropped from state.classifications and recorded in
state.unsupported_forms instead. Before the fix, extract_forms_node read
``state.raw_docs[index]`` keyed by the classification's position, so when an
earlier document was unsupported, every surviving classification was matched
to the *wrong* raw document — the W-2 extractor would run against a receipt's
text and silently produce empty/garbage fields.
"""
from __future__ import annotations

from wealthtax_agent.classify_forms import _DOC_TEXT_CACHE, _doc_text_key
from wealthtax_agent.extract_forms import extract_forms_node
from wealthtax_agent.state import (
    FormClassification,
    GraphState,
    InputDocument,
    UnsupportedForm,
)

_W2_TEXT = (
    "Form W-2 Wage and Tax Statement 2024\n"
    "Box 1 Wages, tips, other compensation: 60000.00\n"
    "Box 2 Federal income tax withheld: 9000.00\n"
)
_JUNK_TEXT = "Grocery receipt — total 42.17 — thank you for shopping\n"


def _prime(content: bytes, text: str) -> None:
    _DOC_TEXT_CACHE[_doc_text_key(content)] = text


def test_sparse_classification_extracts_from_correct_document():
    junk = InputDocument(content=b"junk-receipt-bytes", filename="receipt.txt", mime_type="text/plain")
    w2 = InputDocument(content=b"w2-bytes", filename="w2.txt", mime_type="text/plain")
    _prime(junk.content, _JUNK_TEXT)
    _prime(w2.content, _W2_TEXT)

    # Doc 0 (receipt) was unsupported; only the W-2 (doc index 1) classified.
    state = GraphState(
        raw_docs=[junk, w2],
        tax_year=2024,
        classifications=[
            FormClassification(
                form_code="W-2",
                jurisdiction="US",
                confidence="high",
                filename="w2.txt",
                source_doc_index=1,
            )
        ],
        unsupported_forms=[UnsupportedForm(filename="receipt.txt", reason="not a tax form", suggested_next_step="Manually enter values.")],
    )

    out = extract_forms_node(state)

    assert len(out.extracts) == 1
    e = out.extracts[0]
    assert e.form_code == "W-2"
    # The decisive assertion: fields came from the W-2 text, not the receipt.
    assert e.fields.get("wages") == 60000.0
    assert e.fields.get("federal_income_tax_withheld") == 9000.0


def test_missing_source_index_falls_back_to_positional():
    """Manually-built classifications (no source_doc_index) keep working via
    the positional fallback when classifications and raw_docs are aligned."""
    w2 = InputDocument(content=b"w2-only-bytes", filename="w2.txt", mime_type="text/plain")
    _prime(w2.content, _W2_TEXT)

    state = GraphState(
        raw_docs=[w2],
        tax_year=2024,
        classifications=[
            FormClassification(
                form_code="W-2",
                jurisdiction="US",
                confidence="high",
                filename="w2.txt",
                source_doc_index=None,
            )
        ],
    )

    out = extract_forms_node(state)
    assert len(out.extracts) == 1
    assert out.extracts[0].fields.get("wages") == 60000.0
