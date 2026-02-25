import base64
import json
import os
import re
from typing import List, Optional, Union

import fitz

from wealthtax_agent.llm import call_with_retry, get_client, load_runtime_config, sanitize_runtime_error
from wealthtax_agent.state import GraphState, InputDocument, Slip


client = None
_client_config = None


def _get_client():
    global client
    global _client_config
    if client is not None and _client_config is None:
        return client
    runtime = load_runtime_config()
    signature = (runtime.base_url, runtime.api_key)
    if client is None or _client_config != signature:
        client = get_client(runtime)
        _client_config = signature
    return client


SYSTEM_PROMPT = """You are a Canadian tax slip parser.
You receive OCR text of slips (T4, T5, RRSP receipt).
Return a JSON object: {"slips": [...]} where each slip has:
- type: "T4" | "T5" | "RRSP"
- fields: numeric fields you find, using these names when possible:
  - employment_income
  - interest_income
  - dividends
  - capital_gains
  - rrsp_contributions
If something is not present, omit the field.
"""

RELEVANT_CONTEXT_KEYWORDS = (
    "employment income",
    "interest",
    "dividends",
    "rrsp",
    "contribution",
    "box",
    "tax year",
    "statement",
    "receipt",
)


def _normalize_ocr_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized_lines = []
    for raw_line in normalized.split("\n"):
        line = re.sub(r"[^\x09\x20-\x7E]", " ", raw_line)
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            normalized_lines.append(line)

    compact = "\n".join(normalized_lines)
    compact = re.sub(r"([0-9]),([0-9]{3}(?:\.[0-9]{2})?)", r"\1\2", compact)
    return compact.strip()


def _is_low_quality_ocr_text(text: str) -> bool:
    if not text:
        return True
    if len(text.strip()) < 8:
        return True
    alnum_count = sum(1 for char in text if char.isalnum())
    return alnum_count < 6


def _build_minimal_llm_context(text: str, max_chars: int = 4000) -> str:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    selected = []
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in RELEVANT_CONTEXT_KEYWORDS):
            selected.append(line)

    context = "\n".join(selected if selected else lines)
    if len(context) > max_chars:
        context = context[:max_chars]
    return context


def _extract_amount(text: str, pattern: str) -> Optional[float]:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _extract_amount_from_matching_line(text: str, keyword_pattern: str) -> Optional[float]:
    for line in text.split("\n"):
        if not re.search(keyword_pattern, line, flags=re.IGNORECASE):
            continue
        matches = re.findall(r"[0-9][0-9,]*(?:\.[0-9]+)?", line)
        if not matches:
            continue
        try:
            return float(matches[-1].replace(",", ""))
        except ValueError:
            continue
    return None


def _rule_based_parse(text: str) -> dict:
    slips = []

    employment_income = _extract_amount_from_matching_line(text, r"employment\s*income")
    if employment_income is not None:
        slips.append({"type": "T4", "fields": {"employment_income": employment_income}})

    interest_income = _extract_amount_from_matching_line(text, r"interest\s+from\s+canadian\s+sources")
    dividends = _extract_amount_from_matching_line(text, r"eligible\s+dividends")
    if interest_income is not None or dividends is not None:
        fields = {}
        if interest_income is not None:
            fields["interest_income"] = interest_income
        if dividends is not None:
            fields["dividends"] = dividends
        slips.append({"type": "T5", "fields": fields})

    rrsp_contributions = _extract_amount_from_matching_line(text, r"rrsp\s+contributions")
    if rrsp_contributions is not None:
        slips.append({"type": "RRSP", "fields": {"rrsp_contributions": rrsp_contributions}})

    return {"slips": slips}


def _sanitize_error_message(message: str) -> str:
    return sanitize_runtime_error(message)


def _sanitize_text_for_llm(text: str) -> str:
    sanitized = re.sub(r"gsk_[A-Za-z0-9_\-]+", "[REDACTED_TOKEN]", text)
    sanitized = re.sub(r"sk-[A-Za-z0-9_\-]+", "[REDACTED_TOKEN]", sanitized)
    sanitized = re.sub(r"api[_-]?key\s*[:=]\s*\S+", "api_key=[REDACTED]", sanitized, flags=re.IGNORECASE)
    return sanitized


def _infer_mime_type(doc_bytes: bytes, provided_mime_type: Optional[str]) -> str:
    if provided_mime_type:
        lowered = provided_mime_type.lower().strip()
        if lowered in {"application/pdf", "image/png", "image/jpeg"}:
            return lowered

    if doc_bytes.startswith(b"%PDF"):
        return "application/pdf"
    if doc_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if doc_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return "application/pdf"


def _coerce_input_document(doc: Union[InputDocument, bytes]) -> InputDocument:
    if isinstance(doc, InputDocument):
        mime_type = _infer_mime_type(doc.content, doc.mime_type)
        return InputDocument(content=doc.content, filename=doc.filename, mime_type=mime_type)

    mime_type = _infer_mime_type(doc, None)
    return InputDocument(content=doc, mime_type=mime_type)


def _pdf_to_png_bytes(pdf_bytes: bytes) -> bytes:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if document.page_count == 0:
            raise ValueError("PDF has no pages")
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def _local_ocr_only_enabled() -> bool:
    return os.getenv("LOCAL_OCR_ONLY", "false").strip().lower() in {"1", "true", "yes", "on"}


def _extract_text_from_pdf_locally(pdf_bytes: bytes) -> str:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        parts = []
        for page in document:
            parts.append(page.get_text("text") or "")
        text = "\n".join(parts).strip()
        if not _is_low_quality_ocr_text(_normalize_ocr_text(text)):
            return text

        try:
            from io import BytesIO

            import pytesseract
            from PIL import Image
        except Exception:
            return text

        ocr_parts = []
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            ocr_parts.append(pytesseract.image_to_string(image) or "")
        return "\n".join(ocr_parts).strip()
    finally:
        document.close()


def _extract_text_from_image_locally(image_bytes: bytes) -> str:
    try:
        from io import BytesIO

        import pytesseract
        from PIL import Image
    except Exception:
        return ""

    try:
        image = Image.open(BytesIO(image_bytes))
        return pytesseract.image_to_string(image).strip()
    except Exception:
        return ""


def _extract_text_locally(doc_bytes: bytes, mime_type: str) -> str:
    if mime_type == "application/pdf":
        return _extract_text_from_pdf_locally(doc_bytes)
    if mime_type in {"image/png", "image/jpeg"}:
        return _extract_text_from_image_locally(doc_bytes)
    return ""


def _ocr_bytes_with_vision_model(doc_bytes: bytes, mime_type: str) -> str:
    runtime = load_runtime_config()
    active_client = _get_client()
    normalized_bytes = doc_bytes
    normalized_mime = mime_type
    if mime_type == "application/pdf":
        normalized_bytes = _pdf_to_png_bytes(doc_bytes)
        normalized_mime = "image/png"
    b64 = base64.b64encode(normalized_bytes).decode("utf-8")

    def _call():
        return active_client.chat.completions.create(
            model=runtime.ocr_model,
            messages=[
                {"role": "system", "content": "You transcribe images and PDFs to text."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe this slip into text."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{normalized_mime};base64,{b64}"},
                        },
                    ],
                },
            ],
        )

    response = call_with_retry(_call)
    return response.choices[0].message.content or ""


def ocr_bytes_to_text(doc_bytes: bytes, mime_type: str) -> str:
    local_text = _extract_text_locally(doc_bytes, mime_type)
    if not _is_low_quality_ocr_text(_normalize_ocr_text(local_text)):
        return local_text

    if _local_ocr_only_enabled():
        raise ValueError("Local OCR output quality too low and LOCAL_OCR_ONLY is enabled")

    return _ocr_bytes_with_vision_model(doc_bytes, mime_type)


def llm_parse(text: str) -> dict:
    runtime = load_runtime_config()
    active_client = _get_client()

    def _call():
        return active_client.chat.completions.create(
            model=runtime.parse_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
        )

    response = call_with_retry(_call)
    content = response.choices[0].message.content
    return json.loads(content)


def parse_docs_node(state: GraphState) -> GraphState:
    runtime = load_runtime_config()
    state.llm_provider = runtime.provider

    slips: List[Slip] = []
    for index, doc in enumerate(state.raw_docs, start=1):
        try:
            input_doc = _coerce_input_document(doc)
            if input_doc.mime_type not in {"application/pdf", "image/png", "image/jpeg"}:
                raise ValueError(f"Unsupported file format: {input_doc.mime_type}")

            text = ocr_bytes_to_text(input_doc.content, input_doc.mime_type)
            normalized_text = _normalize_ocr_text(text)
            sanitized_text = _sanitize_text_for_llm(normalized_text)
            if _is_low_quality_ocr_text(sanitized_text):
                raise ValueError("OCR output quality too low to parse reliably")

            parsed = _rule_based_parse(sanitized_text)
            if not parsed.get("slips"):
                llm_context = _build_minimal_llm_context(sanitized_text)
                parsed = llm_parse(llm_context)
            for slip in parsed.get("slips", []):
                if not isinstance(slip, dict):
                    continue
                slip_type = str(slip.get("type", "")).strip()
                fields_raw = slip.get("fields", {})
                if not slip_type or not isinstance(fields_raw, dict):
                    continue
                normalized_fields = {}
                for key, value in fields_raw.items():
                    try:
                        normalized_fields[str(key)] = float(value)
                    except (TypeError, ValueError):
                        continue
                slips.append(Slip(type=slip_type, fields=normalized_fields))
        except Exception as exc:
            state.warnings.append(f"Document {index} parsing failed: {_sanitize_error_message(str(exc))}")

    if state.raw_docs and not slips:
        state.warnings.append("No slips were parsed from uploaded documents.")

    state.slips = slips
    return state
