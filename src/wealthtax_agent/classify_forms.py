"""Identify each uploaded document by jurisdiction + form code.

OCR text comes from the helpers in ``parse_docs`` (reused as-is). Heuristic
regex passes try every registered extractor's ``classify`` method first;
if no extractor scores above the floor, an LLM tie-breaker is asked to pick
one of the supported codes (or report that none apply).
"""

from __future__ import annotations

import json
from typing import List, Optional

from wealthtax_agent.forms import registry  # noqa: F401 - ensure registry is populated
from wealthtax_agent.forms.registry import all_extractors, supported_form_codes
from wealthtax_agent.llm import call_with_retry, get_client, load_runtime_config, sanitize_runtime_error
from wealthtax_agent.parse_docs import (
    _coerce_input_document,
    _is_low_quality_ocr_text,
    _normalize_ocr_text,
    _sanitize_text_for_llm,
    ocr_bytes_to_text,
)
from wealthtax_agent.state import FormClassification, GraphState, UnsupportedForm
# Trigger extractor registration on import.
import wealthtax_agent.forms  # noqa: F401


_DOC_TEXT_CACHE: dict = {}


_CLASSIFIER_SYSTEM_PROMPT = (
    "You are a tax form classifier for Canada and the United States.\n"
    "Given OCR text of a single document, identify which official tax form it is.\n"
    "Reply with a JSON object: {\"jurisdiction\": \"CA\"|\"US\"|\"unknown\", "
    "\"form_code\": \"<code>\"|\"unknown\", \"reason\": \"<short>\"}.\n"
    "Use one of these supported form codes verbatim where possible: {codes}.\n"
    "If the document does not match any supported form, return form_code=\"unknown\"."
)


def _heuristic_classify(text: str) -> Optional[FormClassification]:
    best: Optional[tuple] = None
    for extractor in all_extractors():
        confidence = extractor.classify(text)
        if confidence is None:
            continue
        if best is None or confidence > best[0]:
            best = (confidence, extractor)
    if best is None:
        return None
    confidence, extractor = best
    return FormClassification(
        jurisdiction=extractor.jurisdiction,
        form_code=extractor.form_code,
        confidence="high" if confidence >= 0.85 else "medium",
        reason="Matched extractor heuristic patterns",
    )


def _llm_classify(text: str) -> Optional[FormClassification]:
    try:
        runtime = load_runtime_config()
        client = get_client(runtime)
    except Exception:
        return None

    codes = ", ".join(supported_form_codes())
    system_prompt = _CLASSIFIER_SYSTEM_PROMPT.format(codes=codes)

    def _call():
        return client.chat.completions.create(
            model=runtime.parse_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text[:6000]},
            ],
            response_format={"type": "json_object"},
        )

    try:
        response = call_with_retry(_call)
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:
        return None

    code = str(data.get("form_code", "")).strip().upper()
    jurisdiction = str(data.get("jurisdiction", "")).strip().upper()
    if code in {"UNKNOWN", ""} or jurisdiction not in {"CA", "US"}:
        return None
    if code not in supported_form_codes(jurisdiction):
        return None
    return FormClassification(
        jurisdiction=jurisdiction,  # type: ignore[arg-type]
        form_code=code,
        confidence="medium",
        reason=str(data.get("reason", "LLM classification")),
    )


def _doc_text_key(doc_bytes: bytes) -> str:
    return f"{len(doc_bytes)}:{hash(doc_bytes[:1024])}"


def classify_forms_node(state: GraphState) -> GraphState:
    classifications: List[FormClassification] = []
    unsupported: List[UnsupportedForm] = list(state.unsupported_forms)

    try:
        runtime = load_runtime_config()
        state.llm_provider = runtime.provider
    except Exception:
        pass

    for index, doc in enumerate(state.raw_docs, start=1):
        try:
            input_doc = _coerce_input_document(doc)
            filename = input_doc.filename
            if input_doc.mime_type not in {"application/pdf", "image/png", "image/jpeg"}:
                unsupported.append(UnsupportedForm(
                    filename=filename,
                    detected_label=None,
                    reason=f"File format {input_doc.mime_type} is not supported",
                    suggested_next_step="Re-upload as PDF, PNG, or JPEG.",
                ))
                continue

            text = ocr_bytes_to_text(input_doc.content, input_doc.mime_type)
            normalized = _normalize_ocr_text(text)
            sanitized = _sanitize_text_for_llm(normalized)
            if _is_low_quality_ocr_text(sanitized):
                unsupported.append(UnsupportedForm(
                    filename=filename,
                    detected_label=None,
                    reason="OCR confidence too low to identify the form",
                    suggested_next_step="Try a clearer scan or re-upload as a PDF with embedded text.",
                ))
                continue

            classification = _heuristic_classify(sanitized) or _llm_classify(sanitized)
            if classification is None:
                unsupported.append(UnsupportedForm(
                    filename=filename,
                    detected_label=None,
                    reason="Form not recognised as a supported tax form for this v1.",
                    suggested_next_step=f"Supported v1 forms: {', '.join(supported_form_codes())}. Manually enter values or wait for broader support.",
                ))
                continue

            classification.filename = filename
            classifications.append(classification)
            _DOC_TEXT_CACHE[_doc_text_key(input_doc.content)] = sanitized
        except Exception as exc:
            state.warnings.append(f"Document {index} classification failed: {sanitize_runtime_error(str(exc))}")

    state.classifications = classifications
    state.unsupported_forms = unsupported
    return state


def get_cached_text_for(doc_bytes: bytes) -> Optional[str]:
    return _DOC_TEXT_CACHE.get(_doc_text_key(doc_bytes))
