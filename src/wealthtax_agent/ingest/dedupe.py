"""Document and extract deduplication.

Two fingerprint flavors:

- ``content_fingerprint`` — SHA-256 of the raw bytes. Catches the same file
  uploaded twice (even under different filenames).
- ``form_fingerprint`` — ``"{jurisdiction}:{form_code}:{payer}:{rounded_sum}"``.
  Catches the case where the same logical slip arrives via two paths (a PDF
  scan and a CSV export from the same brokerage).

``dedupe_extracts`` and ``dedupe_input_docs`` preserve order, keep the first
occurrence, and emit warning strings the caller can append to ``state.warnings``.
"""

from __future__ import annotations

import hashlib
from typing import List, Tuple

from wealthtax_agent.state import FormExtract, GraphState, InputDocument


def content_fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _payer_of(extract: FormExtract) -> str:
    return (
        extract.text_fields.get("payer_name", "")
        or extract.text_fields.get("employer_name", "")
        or extract.source_filename
        or ""
    )[:60].strip().lower()


_KEY_AMOUNT_FIELDS = {
    "T4": ["employment_income"],
    "T5": ["interest_income", "taxable_eligible_dividends"],
    "T3": ["capital_gains", "taxable_eligible_dividends"],
    "T5008": ["capital_gain"],
    "W-2": ["wages"],
    "1099-INT": ["interest_income"],
    "1099-DIV": ["ordinary_dividends"],
    "1099-B": ["gain_loss"],
    "1099-NEC": ["nonemployee_compensation"],
    "1099-MISC": ["rents", "other_income"],
    "1099-R": ["taxable_amount"],
    "FORM-16": ["gross_salary"],
    "FORM-16A": ["tds_deducted"],
    "FORM-26AS": ["total_tds"],
    "AIS": ["interest_income", "dividend_income"],
}


def _key_sum(extract: FormExtract) -> float:
    fields_to_sum = _KEY_AMOUNT_FIELDS.get(extract.form_code)
    if fields_to_sum:
        return round(sum(float(extract.fields.get(f, 0.0)) for f in fields_to_sum), 2)
    return round(sum(float(v) for v in extract.fields.values()), 2)


def form_fingerprint(extract: FormExtract) -> str:
    return f"{extract.jurisdiction}:{extract.form_code}:{_payer_of(extract)}:{_key_sum(extract):.2f}"


def dedupe_input_docs(docs: List[InputDocument]) -> Tuple[List[InputDocument], List[str]]:
    """Drop documents whose bytes hash matches an earlier document."""
    seen: set[str] = set()
    kept: List[InputDocument] = []
    warnings: List[str] = []
    for doc in docs:
        fp = content_fingerprint(doc.content)
        if fp in seen:
            warnings.append(
                f"Duplicate upload skipped: '{doc.filename or fp[:10]}' has the same "
                "bytes as an earlier file. Only the first copy is kept."
            )
            continue
        seen.add(fp)
        kept.append(doc)
    return kept, warnings


def dedupe_extracts(extracts: List[FormExtract]) -> Tuple[List[FormExtract], List[str]]:
    """Drop extracts whose ``form_fingerprint`` matches an earlier extract."""
    seen: dict[str, FormExtract] = {}
    kept: List[FormExtract] = []
    warnings: List[str] = []
    for extract in extracts:
        fp = form_fingerprint(extract)
        if fp in seen:
            warnings.append(
                f"Duplicate form skipped: {extract.form_code} ({extract.jurisdiction}) "
                f"from '{extract.source_filename or 'unknown'}' matches "
                f"'{seen[fp].source_filename or 'earlier entry'}'. Only the first copy is kept."
            )
            continue
        seen[fp] = extract
        kept.append(extract)
    return kept, warnings


def dedupe_extracts_node(state: GraphState) -> GraphState:
    """Graph node: dedupe ``state.extracts`` after ``extract_forms`` populated them."""
    if not state.extracts:
        return state
    kept, warnings = dedupe_extracts(state.extracts)
    state.extracts = kept
    for w in warnings:
        if w not in state.warnings:
            state.warnings.append(w)
    return state
