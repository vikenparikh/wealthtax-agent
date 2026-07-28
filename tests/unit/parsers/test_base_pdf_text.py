"""Branch coverage for ``wealthtax_agent.parsers.base.parse_pdf_text``.

Complements ``test_base.py`` (which locks the raw-decode fallback) by driving
the two library-backed branches that don't run naturally in this environment:

* pdfplumber success path (base.py lines 54-58) — pdfplumber is NOT installed
  here, so ``import pdfplumber`` raises. We inject a *fake* pdfplumber module
  into ``sys.modules`` so the success path executes and returns its text.
* pypdf fallback path (base.py lines 65-69) — exercised with a REAL one-page
  PDF built by reportlab, so genuine pypdf text extraction runs.

``parse_pdf_text`` extracts plain TEXT only; no dollar amounts / tax math here.
"""

from __future__ import annotations

import io
import sys
import types

import pytest

from wealthtax_agent.parsers.base import parse_pdf_text


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_fake_pdfplumber(page_texts):
    """Build a stand-in ``pdfplumber`` module.

    ``pdfplumber.open(BytesIO)`` returns a context manager whose ``.pages`` is a
    list of objects each exposing ``.extract_text()`` -> the given page string.
    """

    class _FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _FakePdf:
        def __init__(self, pages):
            self.pages = pages

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    module = types.ModuleType("pdfplumber")

    def _open(_stream):  # signature mirrors pdfplumber.open(io.BytesIO(...))
        return _FakePdf([_FakePage(t) for t in page_texts])

    module.open = _open
    return module


def _real_pdf_bytes(text: str) -> bytes:
    """A real single-page PDF containing ``text``, via reportlab."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, text)
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# pdfplumber success path (lines 54-58)
# --------------------------------------------------------------------------- #
def test_pdfplumber_path_returns_joined_page_text(monkeypatch):
    fake = _make_fake_pdfplumber(["PDFPLUMBER_PAGE_ONE", "PDFPLUMBER_PAGE_TWO"])
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)

    out = parse_pdf_text(b"ignored-by-fake", "slip.pdf")

    # pages are "\n".join-ed then .strip()-ed
    assert out == "PDFPLUMBER_PAGE_ONE\nPDFPLUMBER_PAGE_TWO"


def test_pdfplumber_path_none_page_text_becomes_empty_string(monkeypatch):
    # ``p.extract_text() or ""`` — a page yielding None must not crash the join.
    fake = _make_fake_pdfplumber([None, "SECOND"])
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)

    out = parse_pdf_text(b"ignored")

    assert out == "SECOND"  # leading "" + "\n" + "SECOND", stripped


def test_pdfplumber_empty_text_falls_through_to_next_branch(monkeypatch):
    # When pdfplumber yields only whitespace, ``if text:`` is falsy so the
    # function must NOT return there — it falls through to pypdf, which fails
    # on non-PDF bytes, then to the raw-decode last resort.
    fake = _make_fake_pdfplumber(["   ", ""])
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)

    out = parse_pdf_text(b"raw fallthrough text", "x.pdf")

    assert out == "raw fallthrough text"


# --------------------------------------------------------------------------- #
# pypdf fallback path (lines 65-69) — pdfplumber unavailable, real PDF
# --------------------------------------------------------------------------- #
def test_pypdf_path_extracts_real_pdf_text(monkeypatch):
    # Force pdfplumber absent so this test provably exercises the pypdf branch
    # even if pdfplumber is ever added to the deps (otherwise it would silently
    # start hitting the pdfplumber path and quietly void its stated intent).
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    pdf = _real_pdf_bytes("PYPDF_EXTRACTED_TEXT")

    out = parse_pdf_text(pdf, "real.pdf")

    assert "PYPDF_EXTRACTED_TEXT" in out


def test_pypdf_preferred_when_pdfplumber_absent(monkeypatch):
    # Make the preference explicit: force pdfplumber import to fail (set to
    # None) and confirm the real pypdf branch still extracts the text.
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    pdf = _real_pdf_bytes("ONLY_PYPDF_CAN_READ_ME")

    out = parse_pdf_text(pdf, "real.pdf")

    assert "ONLY_PYPDF_CAN_READ_ME" in out


# --------------------------------------------------------------------------- #
# raw-decode last resort (line 75) — both libs decline
# --------------------------------------------------------------------------- #
def test_raw_decode_when_both_libs_decline(monkeypatch):
    # pdfplumber import fails (None); pypdf raises on non-PDF bytes; so the
    # raw-decode branch returns the decoded string.
    monkeypatch.setitem(sys.modules, "pdfplumber", None)

    out = parse_pdf_text(b"just plain ascii text", "notapdf.txt")

    assert "plain ascii" in out


# Lines 76-77 (``except Exception: return ""``) are unreachable: the only
# statement in that try is ``data.decode("utf-8", errors="replace")``, and
# bytes.decode with errors="replace" never raises for any bytes input. There is
# no ordinary ``bytes`` value that triggers the except, so we do not attempt to
# force it (would require passing a non-bytes object, which misrepresents the
# contract).
@pytest.mark.skip(reason="lines 76-77 unreachable: bytes.decode(errors='replace') never raises")
def test_raw_decode_exception_unreachable():
    pass
