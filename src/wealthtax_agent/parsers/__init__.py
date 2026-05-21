"""Canonical parser layer for multi-jurisdiction tax documents.

Every parser returns a ``ParsedSlip`` — a jurisdiction-normalised envelope
that the rest of the pipeline consumes.  Parsers live in:

  parsers/us/   — 1099-B, 1099-DIV, 1099-INT, W-2, K-1
  parsers/ca/   — T4, T5, RRSP/T4RSP

PDF text extraction uses ``pdfplumber`` when available; falls back to
``pypdf`` then raw bytes decode.  Unstructured fallback uses ClaudeCLILLM.
"""

from wealthtax_agent.parsers.base import ParsedSlip, parse_pdf_text

__all__ = ["ParsedSlip", "parse_pdf_text"]
