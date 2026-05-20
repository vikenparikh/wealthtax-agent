"""Dedupe by content hash and by form fingerprint."""

from wealthtax_agent.ingest.dedupe import (
    content_fingerprint,
    dedupe_extracts,
    dedupe_input_docs,
    form_fingerprint,
)
from wealthtax_agent.state import FormExtract, InputDocument


def test_content_fingerprint_same_bytes_same_hash():
    a = content_fingerprint(b"hello world")
    b = content_fingerprint(b"hello world")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_dedupe_input_docs_drops_duplicate_bytes():
    docs = [
        InputDocument(content=b"%PDF abc", filename="t4.pdf"),
        InputDocument(content=b"%PDF abc", filename="t4-copy.pdf"),
        InputDocument(content=b"%PDF other", filename="t5.pdf"),
    ]
    kept, warnings = dedupe_input_docs(docs)
    assert len(kept) == 2
    assert kept[0].filename == "t4.pdf"
    assert any("Duplicate upload" in w for w in warnings)


def test_form_fingerprint_includes_jurisdiction_form_payer_sum():
    extract = FormExtract(
        form_code="W-2", jurisdiction="US",
        fields={"wages": 80000.0},
        text_fields={"payer_name": "Initech"},
    )
    fp = form_fingerprint(extract)
    assert "US:W-2:initech:80000.00" == fp


def test_dedupe_extracts_drops_same_form_same_payer_same_amount():
    a = FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": 50000.0},
                    text_fields={"payer_name": "Acme"},
                    source_filename="a.pdf")
    b = FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": 50000.0},
                    text_fields={"payer_name": "Acme"},
                    source_filename="b.csv")
    c = FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": 75000.0},
                    text_fields={"payer_name": "Acme"},
                    source_filename="c.pdf")
    kept, warnings = dedupe_extracts([a, b, c])
    assert len(kept) == 2
    assert kept[0].source_filename == "a.pdf"
    assert kept[1].source_filename == "c.pdf"
    assert any("Duplicate form skipped" in w for w in warnings)


def test_dedupe_extracts_keeps_different_payers_for_same_form():
    a = FormExtract(form_code="1099-INT", jurisdiction="US",
                    fields={"interest_income": 500.0},
                    text_fields={"payer_name": "Chase"})
    b = FormExtract(form_code="1099-INT", jurisdiction="US",
                    fields={"interest_income": 500.0},
                    text_fields={"payer_name": "Wells Fargo"})
    kept, warnings = dedupe_extracts([a, b])
    assert len(kept) == 2
    assert warnings == []
