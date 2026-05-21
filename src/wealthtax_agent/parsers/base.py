"""Base types and PDF-text extraction utilities shared by all parsers."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


@dataclass
class ParsedSlip:
    """Canonical, jurisdiction-normalised output of every parser.

    ``fields`` mirrors the form's box/line numbering — numeric values only.
    ``text_fields`` holds non-numeric fields (SIN, EIN, payer name, etc.).
    """

    jurisdiction: str          # "US" | "CA"
    form_type: str             # "1099-B", "W-2", "T4", etc.
    tax_year: Optional[int]
    fields: Dict[str, float] = field(default_factory=dict)
    text_fields: Dict[str, str] = field(default_factory=dict)
    source_filename: Optional[str] = None
    extractor: str = "rule"    # "rule" | "llm"
    confidence: str = "medium" # "low" | "medium" | "high"
    raw_text: Optional[str] = None

    def to_form_extract_dict(self) -> Dict[str, Any]:
        """Bridge to the existing FormExtract / pipeline shape."""
        return {
            "form_code": self.form_type,
            "jurisdiction": self.jurisdiction,
            "tax_year": self.tax_year,
            "fields": self.fields,
            "text_fields": self.text_fields,
            "source_filename": self.source_filename,
            "extractor": self.extractor,
            "confidence": self.confidence,
        }


def parse_pdf_text(data: bytes, filename: Optional[str] = None) -> str:
    """Extract plain text from PDF bytes.

    Tries pdfplumber first (best layout fidelity), falls back to pypdf,
    then decodes raw bytes as a last resort.
    """
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        text = "\n".join(pages).strip()
        if text:
            return text
    except Exception as exc:
        log.debug("pdfplumber failed for %s: %s", filename, exc)

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        if text:
            return text
    except Exception as exc:
        log.debug("pypdf failed for %s: %s", filename, exc)

    # Raw decode — at least returns something for ASCII-heavy PDFs
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""
