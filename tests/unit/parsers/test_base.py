"""Characterization tests for ``wealthtax_agent.parsers.base``.

Locks the CURRENT behaviour of ``ParsedSlip`` and ``parse_pdf_text`` —
these are not behaviour changes, just coverage of what exists today.
"""

from __future__ import annotations

import sys

from wealthtax_agent.parsers.base import ParsedSlip, parse_pdf_text


# --------------------------------------------------------------------------- #
# ParsedSlip.to_form_extract_dict()
# --------------------------------------------------------------------------- #
def test_to_form_extract_dict_maps_form_type_to_form_code_and_passes_through():
    slip = ParsedSlip(
        jurisdiction="US",
        form_type="1099-B",
        tax_year=2024,
        fields={"box_1a": 100.0},
        text_fields={"payer_ein": "12-3456789"},
        source_filename="broker.pdf",
        extractor="llm",
        confidence="high",
        raw_text="some raw text",
    )

    d = slip.to_form_extract_dict()

    # form_type -> form_code rename
    assert d["form_code"] == "1099-B"
    assert "form_type" not in d

    # verbatim pass-through
    assert d["jurisdiction"] == "US"
    assert d["tax_year"] == 2024
    assert d["fields"] == {"box_1a": 100.0}
    assert d["text_fields"] == {"payer_ein": "12-3456789"}
    assert d["source_filename"] == "broker.pdf"
    assert d["extractor"] == "llm"
    assert d["confidence"] == "high"

    # raw_text is intentionally NOT bridged
    assert "raw_text" not in d


def test_to_form_extract_dict_exact_keyset():
    slip = ParsedSlip(jurisdiction="CA", form_type="T4", tax_year=2023)
    assert set(slip.to_form_extract_dict().keys()) == {
        "form_code",
        "jurisdiction",
        "tax_year",
        "fields",
        "text_fields",
        "source_filename",
        "extractor",
        "confidence",
    }


# --------------------------------------------------------------------------- #
# ParsedSlip dataclass defaults
# --------------------------------------------------------------------------- #
def test_parsed_slip_defaults():
    slip = ParsedSlip(jurisdiction="CA", form_type="T4", tax_year=2023)
    assert slip.fields == {}
    assert slip.text_fields == {}
    assert slip.extractor == "rule"
    assert slip.confidence == "medium"
    assert slip.source_filename is None
    assert slip.raw_text is None


def test_default_factory_independence():
    a = ParsedSlip(jurisdiction="CA", form_type="T4", tax_year=2023)
    b = ParsedSlip(jurisdiction="US", form_type="W-2", tax_year=2023)

    a.fields["box"] = 1.0
    a.text_fields["sin"] = "x"

    # mutating a's dicts must not leak into b's independent defaults
    assert b.fields == {}
    assert b.text_fields == {}


# --------------------------------------------------------------------------- #
# parse_pdf_text raw-decode fallback (env-independent via import forcing)
# --------------------------------------------------------------------------- #
def _force_no_pdf_libs(monkeypatch):
    # Setting a module to None makes ``import x`` raise ImportError, so both
    # the pdfplumber and pypdf branches fail and the raw-decode branch runs.
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    monkeypatch.setitem(sys.modules, "pypdf", None)


def test_parse_pdf_text_raw_decode_ascii(monkeypatch):
    _force_no_pdf_libs(monkeypatch)
    assert parse_pdf_text(b"hello world", "x.pdf") == "hello world"


def test_parse_pdf_text_invalid_utf8_replaced(monkeypatch):
    _force_no_pdf_libs(monkeypatch)
    out = parse_pdf_text(b"\xff\xfe\x00ab", "x.pdf")
    assert isinstance(out, str)  # errors="replace" -> no raise
    assert "ab" in out


def test_parse_pdf_text_empty_bytes(monkeypatch):
    _force_no_pdf_libs(monkeypatch)
    assert parse_pdf_text(b"") == ""


def test_parse_pdf_text_filename_optional(monkeypatch):
    _force_no_pdf_libs(monkeypatch)
    # filename defaults to None per the signature
    assert parse_pdf_text(b"plain") == "plain"
