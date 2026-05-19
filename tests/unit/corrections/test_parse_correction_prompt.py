from unittest.mock import patch

from wealthtax_agent.corrections import _local_fallback_parse, parse_correction_prompt


def test_local_fallback_parses_set_t4_box_14():
    changes = _local_fallback_parse("Set my T4 box 14 to 92,300")
    assert len(changes) == 1
    c = changes[0]
    assert c.op == "set" and c.target == "extract"
    assert c.form_code == "T4" and c.field == "employment_income"
    assert c.new_value == 92300.0


def test_local_fallback_parses_add_1099_int():
    changes = _local_fallback_parse("Add a 1099-INT for $400 from Chase")
    assert len(changes) == 1
    c = changes[0]
    assert c.op == "add" and c.target == "form"
    assert c.form_code == "1099-INT" and c.field == "interest_income"
    assert c.new_value == 400.0


def test_local_fallback_parses_remove_1099_misc():
    changes = _local_fallback_parse("Please remove the 1099-MISC")
    assert len(changes) == 1
    assert changes[0].op == "remove"
    assert changes[0].form_code == "1099-MISC"


def test_local_fallback_parses_filing_status():
    changes = _local_fallback_parse("Set my filing status to married filing jointly")
    assert changes and changes[0].target == "user_answer"
    assert changes[0].field == "filing_status"
    assert changes[0].new_value == "married_filing_jointly"


def test_parse_uses_llm_when_available(monkeypatch):
    """When the Groq client responds with structured JSON, use it directly."""
    class _Msg:
        def __init__(self, content): self.content = content
    class _Choice:
        def __init__(self, content): self.message = _Msg(content)
    class _Resp:
        def __init__(self, content): self.choices = [_Choice(content)]
    class _Comp:
        def create(self, **kwargs):
            return _Resp('{"changes":[{"op":"set","target":"extract","form_code":"W-2","field":"wages","new_value":100000,"reason":"LLM said so"}]}')
    class _Chat:
        def __init__(self): self.completions = _Comp()
    class _Client:
        def __init__(self): self.chat = _Chat()

    with patch("wealthtax_agent.corrections.get_client", return_value=_Client()):
        changes = parse_correction_prompt("set wages to 100000")
    assert len(changes) == 1
    assert changes[0].form_code == "W-2"
    assert changes[0].new_value == 100000


def test_parse_empty_prompt_returns_empty():
    assert parse_correction_prompt("") == []
    assert parse_correction_prompt("   ") == []
