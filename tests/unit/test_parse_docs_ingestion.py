"""Coverage for the live ingestion surface in parse_docs.py.

Targets the local-extraction dispatch (PDF/image/xlsx/csv), the amount-parsing
helpers, the client memoization, the vision-model OCR data-URL boundary, and the
unsupported-format guard in parse_docs_node. Each test asserts a behavior that
would regress if the corresponding code path broke (no line-hitting padding).

Complements:
  - test_parse_docs_node.py        (node orchestration + rule-based parse)
  - test_parse_docs_text_helpers.py (pure text normalization/sanitization)
"""

import fitz
import pytest

import wealthtax_agent.parse_docs as parse_docs
from wealthtax_agent.state import GraphState, InputDocument

# Reuse the fake-client hierarchy from the node test module so the
# completions shim stays in one place.
from tests.unit.test_parse_docs_node import _Client


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# --- fixtures / helpers ------------------------------------------------------


@pytest.fixture
def restore_client_globals():
    """Snapshot and restore the module-level client + config so mutating tests
    don't leak state into the rest of the suite."""
    saved_client = parse_docs.client
    saved_config = parse_docs._client_config
    try:
        yield
    finally:
        parse_docs.client = saved_client
        parse_docs._client_config = saved_config


def _make_pdf_bytes(text: str = "hi") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_png_bytes(text: str = "hi") -> bytes:
    """Render a 1-page PDF to a real PNG via a fitz pixmap."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    pixmap = page.get_pixmap(alpha=False)
    data = pixmap.tobytes("png")
    doc.close()
    return data


def _make_xlsx_bytes(rows):
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Income"
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- R1: _get_client memoization ---------------------------------------------


def test_get_client_memoizes_same_instance(restore_client_globals):
    parse_docs.client = None
    parse_docs._client_config = None

    first = parse_docs._get_client()
    second = parse_docs._get_client()

    assert first is not None
    assert first is second


# --- R2: _extract_amount -----------------------------------------------------


def test_extract_amount_parses_grouped_number():
    assert parse_docs._extract_amount("total: 1,234.50", r"total:\s*([0-9,\.]+)") == 1234.5


def test_extract_amount_returns_none_when_no_match():
    assert parse_docs._extract_amount("nothing here", r"total:\s*([0-9,\.]+)") is None


def test_extract_amount_returns_none_for_non_numeric_group():
    assert parse_docs._extract_amount("total: abc", r"total:\s*([a-z]+)") is None


# --- R3: _extract_amount_from_matching_line ----------------------------------


def test_extract_amount_from_matching_line_no_digits_returns_none():
    assert parse_docs._extract_amount_from_matching_line("interest income only", r"interest") is None


def test_extract_amount_from_matching_line_returns_last_number():
    assert parse_docs._extract_amount_from_matching_line("interest 1,200.50", r"interest") == 1200.5


# --- R4: _pdf_to_png_bytes ---------------------------------------------------


def test_pdf_to_png_bytes_emits_png_magic():
    out = parse_docs._pdf_to_png_bytes(_make_pdf_bytes())
    assert out.startswith(_PNG_MAGIC)


# --- R5: _extract_text_from_pdf_locally --------------------------------------


def test_extract_text_from_pdf_locally_returns_embedded_text():
    pdf = _make_pdf_bytes("Employment income (Box 14): 84500.00")
    text = parse_docs._extract_text_from_pdf_locally(pdf)
    assert "Employment income (Box 14): 84500.00" in text


# --- R6: _extract_text_from_image_locally (tesseract absent -> "") -----------


def test_extract_text_from_image_locally_returns_empty_without_tesseract():
    # pytesseract raises TesseractNotFoundError in this env; caught -> "".
    assert parse_docs._extract_text_from_image_locally(_make_png_bytes()) == ""


# --- R7: _extract_text_from_xlsx_locally -------------------------------------


def test_extract_text_from_xlsx_locally_renders_rows_and_skips_empty():
    xlsx = _make_xlsx_bytes(
        [
            ["Field", "Amount"],
            [None, None],  # fully-empty row BETWEEN data rows (trailing
            # empties are dropped by openpyxl read_only before the filter sees
            # them; an interior empty row actually exercises line 268's guard).
            ["employment_income", "84500"],
        ]
    )
    out = parse_docs._extract_text_from_xlsx_locally(xlsx)

    assert "# Sheet: Income" in out
    assert "Field\tAmount" in out
    assert "employment_income\t84500" in out
    # Load-bearing for the `if any(c.strip()...)` filter: the fully-empty row
    # would serialize to a bare tab-only line ("\t") if the filter were dropped.
    # No emitted line may be composed solely of tabs/whitespace.
    data_lines = [ln for ln in out.split("\n") if not ln.startswith("# Sheet:")]
    assert all(ln.strip("\t ") for ln in data_lines), data_lines
    # Exactly the two non-empty rows survive (header + data), not three.
    assert len(data_lines) == 2


# --- R8: _extract_text_from_csv_locally --------------------------------------


def test_extract_text_from_csv_locally_normalizes_crlf_and_trims_blanks():
    assert parse_docs._extract_text_from_csv_locally(b"a,b\r\nc,d\r\n\r\n") == "a,b\nc,d"


# --- R9: _extract_text_locally dispatch --------------------------------------


def test_extract_text_locally_routes_pdf():
    pdf = _make_pdf_bytes("Employment income (Box 14): 84500.00")
    text = parse_docs._extract_text_locally(pdf, "application/pdf")
    assert "Employment income (Box 14): 84500.00" in text


def test_extract_text_locally_routes_image():
    assert parse_docs._extract_text_locally(_make_png_bytes(), "image/png") == ""


def test_extract_text_locally_routes_xlsx():
    xlsx = _make_xlsx_bytes([["Field", "Amount"], ["interest_income", "1200"]])
    out = parse_docs._extract_text_locally(xlsx, parse_docs._XLSX_MIME)
    assert "interest_income\t1200" in out


def test_extract_text_locally_routes_csv():
    assert parse_docs._extract_text_locally(b"a,b\r\nc,d\r\n", parse_docs._CSV_MIME) == "a,b\nc,d"


def test_extract_text_locally_unknown_mime_returns_empty():
    assert parse_docs._extract_text_locally(b"x", "application/zip") == ""


# --- R10: _ocr_bytes_with_vision_model (data-URL boundary) -------------------


class _AssertingClient:
    """Vision-model fake: asserts the image_url is a base64 PNG data URL and
    records the mime that was sent so PDF->PNG normalization can be verified."""

    def __init__(self):
        self.sent_url = None

        outer = self

        class _Completions:
            def create(self, **kwargs):
                content = kwargs["messages"][1]["content"]
                url = content[1]["image_url"]["url"]
                assert url.startswith("data:image/png;base64,"), url
                outer.sent_url = url
                return _Client(["transcribed!"]).chat.completions.create(**{})

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def test_ocr_vision_model_pdf_branch_sends_png_data_url(restore_client_globals):
    fake = _AssertingClient()
    parse_docs.client = fake
    parse_docs._client_config = None

    result = parse_docs._ocr_bytes_with_vision_model(_make_pdf_bytes(), "application/pdf")

    assert result == "transcribed!"
    assert fake.sent_url.startswith("data:image/png;base64,")


def test_ocr_vision_model_png_branch_skips_pdf_conversion(restore_client_globals):
    fake = _AssertingClient()
    parse_docs.client = fake
    parse_docs._client_config = None

    result = parse_docs._ocr_bytes_with_vision_model(_make_png_bytes(), "image/png")

    assert result == "transcribed!"
    assert fake.sent_url.startswith("data:image/png;base64,")


# --- R11: ocr_bytes_to_text remote path + xlsx/csv early return --------------


def test_ocr_bytes_to_text_falls_back_to_vision_model(monkeypatch, restore_client_globals):
    monkeypatch.setattr(parse_docs, "_extract_text_locally", lambda _b, _m: "")
    parse_docs.client = _Client(["transcribed!"])
    parse_docs._client_config = None

    out = parse_docs.ocr_bytes_to_text(_make_png_bytes(), "image/png")

    assert out == "transcribed!"


def test_ocr_bytes_to_text_csv_returns_local_without_vision(monkeypatch, restore_client_globals):
    monkeypatch.setattr(parse_docs, "_extract_text_locally", lambda _b, _m: "")

    def _no_vision(_b, _m):
        raise AssertionError("vision model must not run for CSV")

    monkeypatch.setattr(parse_docs, "_ocr_bytes_with_vision_model", _no_vision)

    out = parse_docs.ocr_bytes_to_text(b"a,b\nc,d", parse_docs._CSV_MIME)

    assert out == ""


# --- R12: parse_docs_node unsupported-format guard ---------------------------


def test_parse_docs_node_warns_on_unsupported_format(monkeypatch):
    monkeypatch.setattr(
        parse_docs,
        "_coerce_input_document",
        lambda _doc: InputDocument(content=b"x", mime_type="application/zip"),
    )

    state = GraphState(raw_docs=[b"x"])
    result = parse_docs.parse_docs_node(state)

    assert result.slips == []
    assert any("Unsupported file format: application/zip" in w for w in result.warnings)
