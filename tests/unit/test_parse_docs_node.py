import wealthtax_agent.parse_docs as parse_docs
from wealthtax_agent.state import GraphState


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = 0

    def create(self, **kwargs):
        output = self.outputs[self.calls]
        self.calls += 1
        return _Resp(output)


class _Chat:
    def __init__(self, outputs):
        self.completions = _Completions(outputs)


class _Client:
    def __init__(self, outputs):
        self.chat = _Chat(outputs)


def test_llm_parse_parses_json(monkeypatch):
    monkeypatch.setattr(parse_docs, "client", _Client(['{"slips": [{"type": "T4", "fields": {"employment_income": 123.0}}]}']))

    result = parse_docs.llm_parse("dummy")

    assert result["slips"][0]["type"] == "T4"
    assert result["slips"][0]["fields"]["employment_income"] == 123.0


def test_parse_docs_node_builds_state_slips(monkeypatch):
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda _doc, _mime: "transcribed text")
    monkeypatch.setattr(
        parse_docs,
        "llm_parse",
        lambda _text: {
            "slips": [
                {"type": "T4", "fields": {"employment_income": 80000.0}},
                {"type": "RRSP", "fields": {"rrsp_contributions": 5000.0}},
            ]
        },
    )

    state = GraphState(raw_docs=[b"doc-a"])
    result = parse_docs.parse_docs_node(state)

    assert len(result.slips) == 2
    assert result.slips[0].type == "T4"
    assert result.slips[1].fields["rrsp_contributions"] == 5000.0


def test_parse_docs_node_adds_warning_on_failure(monkeypatch):
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda _doc, _mime: "bad text")

    def _raise(_text):
        raise ValueError("parse failed")

    monkeypatch.setattr(parse_docs, "llm_parse", _raise)

    state = GraphState(raw_docs=[b"doc-a"])
    result = parse_docs.parse_docs_node(state)

    assert result.slips == []
    assert len(result.warnings) >= 1


def test_parse_docs_node_ignores_invalid_slip_shapes(monkeypatch):
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda _doc, _mime: "mixed slip transcription data")
    monkeypatch.setattr(
        parse_docs,
        "llm_parse",
        lambda _text: {
            "slips": [
                "not-a-dict",
                {"type": "", "fields": {"employment_income": 100}},
                {"type": "T4", "fields": "not-a-dict"},
                {"type": "T4", "fields": {"employment_income": "80000", "bad": "abc"}},
            ]
        },
    )

    state = GraphState(raw_docs=[b"doc-a"])
    result = parse_docs.parse_docs_node(state)

    assert len(result.slips) == 1
    assert result.slips[0].type == "T4"
    assert result.slips[0].fields == {"employment_income": 80000.0}


def test_parse_docs_node_redacts_sensitive_error(monkeypatch):
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda _doc, _mime: "transcribed content")

    def _raise(_text):
        raise ValueError("invalid api_key gsk_secret")

    monkeypatch.setattr(parse_docs, "llm_parse", _raise)

    state = GraphState(raw_docs=[b"doc-a"])
    result = parse_docs.parse_docs_node(state)

    assert any("Model provider authentication failed. Verify GROQ_API_KEY and endpoint settings." in warning for warning in result.warnings)


def test_rule_based_parse_extracts_known_fields():
    text = (
        "Employment income (Box 14): 80000.00\n"
        "Interest from Canadian sources (Box 13): 1200.50\n"
        "Taxable amount of eligible dividends (Box 24): 500.00\n"
        "Total RRSP contributions: 7000.00\n"
    )

    parsed = parse_docs._rule_based_parse(text)

    assert len(parsed["slips"]) == 3
    t4 = next(item for item in parsed["slips"] if item["type"] == "T4")
    t5 = next(item for item in parsed["slips"] if item["type"] == "T5")
    rrsp = next(item for item in parsed["slips"] if item["type"] == "RRSP")
    assert t4["fields"]["employment_income"] == 80000.0
    assert t5["fields"]["interest_income"] == 1200.5
    assert t5["fields"]["dividends"] == 500.0
    assert rrsp["fields"]["rrsp_contributions"] == 7000.0


def test_parse_docs_node_uses_rule_based_before_llm(monkeypatch):
    text = "Employment income (Box 14): 81000.00"
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda _doc, _mime: text)

    def _llm_should_not_run(_text):
        raise AssertionError("llm_parse should not be called for rule-based match")

    monkeypatch.setattr(parse_docs, "llm_parse", _llm_should_not_run)

    state = GraphState(raw_docs=[b"doc-a"])
    result = parse_docs.parse_docs_node(state)

    assert len(result.slips) == 1
    assert result.slips[0].type == "T4"
    assert result.slips[0].fields["employment_income"] == 81000.0


def test_sanitize_text_for_llm_masks_sensitive_tokens():
    text = "api_key=secret gsk_abc123 sk-secret"

    sanitized = parse_docs._sanitize_text_for_llm(text)

    assert "gsk_abc123" not in sanitized
    assert "sk-secret" not in sanitized
    assert "api_key=[REDACTED]" in sanitized


def test_infer_mime_type_uses_file_signature_when_missing_metadata():
    assert parse_docs._infer_mime_type(b"%PDF-1.4\n...", None) == "application/pdf"
    assert parse_docs._infer_mime_type(b"\x89PNG\r\n\x1a\n...", None) == "image/png"
    assert parse_docs._infer_mime_type(b"\xff\xd8\xff\xe0...", None) == "image/jpeg"


def test_normalize_ocr_text_flattens_noise_and_number_grouping():
    raw = "Employment\r\nincome (Box 14): 84,500.00\x00\n\nRRSP contributions: 9,000.00"

    normalized = parse_docs._normalize_ocr_text(raw)

    assert "84500.00" in normalized
    assert "9000.00" in normalized
    assert "\x00" not in normalized


def test_is_low_quality_ocr_text_flags_short_or_empty_payloads():
    assert parse_docs._is_low_quality_ocr_text("")
    assert parse_docs._is_low_quality_ocr_text("abc")
    assert not parse_docs._is_low_quality_ocr_text("Employment income Box 14 84500")


def test_build_minimal_llm_context_filters_irrelevant_lines():
    text = "\n".join(
        [
            "random marketing line",
            "Employment income (Box 14): 84500.00",
            "noise footer",
            "RRSP contributions: 9000.00",
        ]
    )

    context = parse_docs._build_minimal_llm_context(text)

    assert "Employment income" in context
    assert "RRSP contributions" in context
    assert "random marketing line" not in context


def test_parse_docs_node_uses_minimal_context_for_llm(monkeypatch):
    captured = {}
    ocr_text = "\n".join(
        [
            "welcome header",
            "T5 Statement of Investment Income",
            "Interest from Canadian sources (Box 13): 1325.40",
            "ad footer",
        ]
    )

    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda _doc, _mime: ocr_text)

    def _capture_llm(text):
        captured["text"] = text
        return {"slips": [{"type": "T5", "fields": {"interest_income": 1325.4}}]}

    monkeypatch.setattr(parse_docs, "llm_parse", _capture_llm)
    monkeypatch.setattr(parse_docs, "_rule_based_parse", lambda _text: {"slips": []})

    state = GraphState(raw_docs=[b"doc-a"])
    result = parse_docs.parse_docs_node(state)

    assert len(result.slips) == 1
    assert "Interest from Canadian sources" in captured["text"]
    assert "ad footer" not in captured["text"]


def test_parse_docs_node_warns_on_low_quality_ocr(monkeypatch):
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda _doc, _mime: "")

    state = GraphState(raw_docs=[b"doc-a"])
    result = parse_docs.parse_docs_node(state)

    assert result.slips == []
    assert any("OCR output quality too low" in warning for warning in result.warnings)


def test_ocr_bytes_to_text_prefers_local_extraction(monkeypatch):
    monkeypatch.setattr(parse_docs, "_extract_text_locally", lambda _doc, _mime: "Employment income (Box 14): 84500.00")

    def _remote_should_not_run(_doc, _mime):
        raise AssertionError("remote OCR should not be called")

    monkeypatch.setattr(parse_docs, "_ocr_bytes_with_vision_model", _remote_should_not_run)

    text = parse_docs.ocr_bytes_to_text(b"doc", "application/pdf")

    assert "Employment income" in text


def test_ocr_bytes_to_text_honors_local_ocr_only(monkeypatch):
    monkeypatch.setattr(parse_docs, "_extract_text_locally", lambda _doc, _mime: "")
    monkeypatch.setenv("LOCAL_OCR_ONLY", "true")

    try:
        parse_docs.ocr_bytes_to_text(b"doc", "application/pdf")
    except ValueError as exc:
        assert "LOCAL_OCR_ONLY" in str(exc)
    else:
        raise AssertionError("Expected LOCAL_OCR_ONLY error")
