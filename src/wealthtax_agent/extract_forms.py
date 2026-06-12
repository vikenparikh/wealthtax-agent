"""Pull structured fields out of each classified document.

Pipeline: for each ``FormClassification``, look up the matching extractor
in ``forms.registry`` and call ``extract(text)``. Falls back to an LLM JSON
extraction when the rule-based extractor returns an empty record.
"""

from __future__ import annotations

import json
from typing import List, Optional

from wealthtax_agent.classify_forms import get_cached_text_for
from wealthtax_agent.forms.registry import get as get_extractor
from wealthtax_agent.llm import call_with_retry, get_client, load_runtime_config, sanitize_runtime_error
from wealthtax_agent.parse_docs import (
    _coerce_input_document,
    _normalize_ocr_text,
    _sanitize_text_for_llm,
    ocr_bytes_to_text,
)
from wealthtax_agent.state import FormExtract, GraphState, Slip


_LLM_EXTRACT_SYSTEM_PROMPT = (
    "You extract structured fields from one tax form's OCR text.\n"
    "Return JSON: {\"fields\": {<field_name>: <number>, ...}, \"tax_year\": <int or null>}.\n"
    "Only emit numeric fields you are confident about; omit unknown fields."
)


def _llm_extract(text: str, form_code: str) -> dict:
    try:
        runtime = load_runtime_config()
        client = get_client(runtime)
    except Exception:
        return {}

    user_prompt = f"Form code: {form_code}\n\nOCR text:\n{text[:6000]}"

    def _call():
        return client.chat.completions.create(
            model=runtime.parse_model,
            messages=[
                {"role": "system", "content": _LLM_EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )

    try:
        response = call_with_retry(_call)
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:
        return {}

    fields = data.get("fields", {}) or {}
    cleaned = {}
    for key, value in fields.items():
        try:
            cleaned[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    tax_year = data.get("tax_year")
    return {"fields": cleaned, "tax_year": tax_year if isinstance(tax_year, int) else None}


def _text_for_doc(doc) -> Optional[str]:
    input_doc = _coerce_input_document(doc)
    cached = get_cached_text_for(input_doc.content)
    if cached is not None:
        return cached
    try:
        text = ocr_bytes_to_text(input_doc.content, input_doc.mime_type or "application/pdf")
    except Exception:
        return None
    return _sanitize_text_for_llm(_normalize_ocr_text(text))


def extract_forms_node(state: GraphState) -> GraphState:
    # Preserve manually-entered extracts (intake wizard) that don't have a
    # matching classification — those came in pre-built and should pass through.
    manual_extracts = [e for e in state.extracts if not any(
        c.form_code == e.form_code and c.jurisdiction == e.jurisdiction for c in state.classifications
    )]
    extracts: List[FormExtract] = list(manual_extracts)
    legacy_slips: List[Slip] = [Slip(type=e.form_code, fields=e.fields) for e in manual_extracts]

    for index, classification in enumerate(state.classifications):
        try:
            if classification.form_code is None or classification.jurisdiction is None:
                continue
            extractor = get_extractor(classification.form_code)
            if extractor is None:
                continue

            doc_index = classification.source_doc_index
            if doc_index is None:
                doc_index = index
            doc = state.raw_docs[doc_index] if 0 <= doc_index < len(state.raw_docs) else None
            text = _text_for_doc(doc) if doc is not None else None
            if not text:
                continue

            extract = extractor.extract(text, source_filename=classification.filename)

            if not extract.fields:
                fallback = _llm_extract(text, classification.form_code)
                if fallback.get("fields"):
                    extract.fields = fallback["fields"]
                    extract.extractor = "llm"
                    extract.confidence = "medium"
                if fallback.get("tax_year") and not extract.tax_year:
                    extract.tax_year = fallback["tax_year"]

            extracts.append(extract)
            legacy_slips.append(Slip(type=extract.form_code, fields=extract.fields))
        except Exception as exc:
            state.warnings.append(f"Document {index + 1} extraction failed: {sanitize_runtime_error(str(exc))}")

    if state.raw_docs and not extracts and not state.unsupported_forms:
        state.warnings.append("No tax forms were successfully extracted from uploaded documents.")

    state.extracts = extracts
    state.slips = legacy_slips
    return state
