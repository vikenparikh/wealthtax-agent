"""Tests for _infer_mime_type (parse_docs.py) — the content/magic-byte sniffer
that decides how every uploaded document is parsed.

A whitelisted provided mime is trusted; anything else falls back to magic-byte
sniffing (PDF / PNG / JPEG / XLSX-zip) then a CSV heuristic, defaulting to PDF.
Getting this wrong routes a file to the wrong parser, so every branch is pinned.
"""

from wealthtax_agent.parse_docs import _CSV_MIME, _XLSX_MIME, _infer_mime_type


def test_whitelisted_provided_mime_is_trusted_case_insensitively():
    assert _infer_mime_type(b"anything", "application/pdf") == "application/pdf"
    assert _infer_mime_type(b"x", "IMAGE/PNG") == "image/png"     # lower-cased
    assert _infer_mime_type(b"x", "  text/csv  ") == "text/csv"   # stripped


def test_non_whitelisted_provided_mime_falls_back_to_sniffing():
    # application/zip isn't trusted; the %PDF magic wins instead.
    assert _infer_mime_type(b"%PDF-1.7 trailing", "application/zip") == "application/pdf"


def test_pdf_magic_bytes():
    assert _infer_mime_type(b"%PDF-1.4\nbody", None) == "application/pdf"


def test_png_magic_bytes():
    assert _infer_mime_type(b"\x89PNG\r\n\x1a\nIHDR", None) == "image/png"


def test_jpeg_magic_bytes():
    assert _infer_mime_type(b"\xff\xd8\xff\xe0JFIF", None) == "image/jpeg"


def test_xlsx_is_a_zip_containing_an_xl_path():
    blob = b"PK\x03\x04" + b"\x00" * 20 + b"xl/workbook.xml" + b"\x00" * 10
    assert _infer_mime_type(blob, None) == _XLSX_MIME


def test_zip_without_xl_path_is_not_xlsx():
    assert _infer_mime_type(b"PK\x03\x04" + b"\x00" * 100, None) == "application/pdf"


def test_csv_heuristic_matches_commas_and_newline():
    csv = b"name,amount,year\nJane,1000,2024\nJohn,2000,2024\n"
    assert _infer_mime_type(csv, None) == _CSV_MIME


def test_commas_without_newline_are_not_csv():
    assert _infer_mime_type(b"a,b,c,d,e", None) == "application/pdf"


def test_non_utf8_payload_with_commas_is_not_csv():
    blob = b"a,b,c\n\xff\xfe\xff,,,"
    assert _infer_mime_type(blob, None) == "application/pdf"


def test_unknown_bytes_default_to_pdf():
    assert _infer_mime_type(b"just some random text bytes", None) == "application/pdf"
