"""End-to-end test that drives EVERY supported form through the full
multi-country pipeline and asserts the resulting artifacts are valid.

For each form we:
  1. Stub OCR + LLM (no network) so it's deterministic.
  2. Feed one ``raw_doc`` whose text matches the fixture for that form.
  3. Invoke the compiled new graph with the right jurisdiction + plausible
     clarifying answers so the pipeline doesn't pause.
  4. Assert: the form was classified correctly, an extract was produced,
     a draft return was computed, and the jurisdiction's filing artifacts
     (PDF + XML/JSON) are present and *parseable*.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

import wealthtax_agent.classify_forms as classify_forms
import wealthtax_agent.explain_return as explain_return
import wealthtax_agent.extract_forms as extract_forms
import wealthtax_agent.optimize as optimize
import wealthtax_agent.parse_docs as parse_docs
from wealthtax_agent.graph import build_graph
from wealthtax_agent.state import GraphState, InputDocument


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "forms"


class _StubMsg:
    def __init__(self, content): self.content = content
class _StubChoice:
    def __init__(self, content): self.message = _StubMsg(content)
class _StubResp:
    def __init__(self, content): self.choices = [_StubChoice(content)]
class _StubCompletions:
    def create(self, **kwargs):
        return _StubResp('{"lines": {"total_income": "from your forms", "estimated_tax": "approx"}}')
class _StubChat:
    def __init__(self): self.completions = _StubCompletions()
class _StubClient:
    def __init__(self): self.chat = _StubChat()


CA_ANSWERS = {
    "marital_status": "single",
    "province_of_residence": "ON",
    "foreign_property_over_100k": "no",
}
US_ANSWERS = {
    "filing_status": "single",
    "num_dependents": "0",
    "state_of_residence": "CA",
    "foreign_accounts_over_10k": "no",
}


# (form_code, fixture-path-relative-to-tests/fixtures/forms, jurisdiction)
EVERY_FORM = [
    # Canada
    ("T4",     "ca/t4_sample.txt",     "CA"),
    ("T5",     "ca/t5_sample.txt",     "CA"),
    ("T3",     "ca/t3_sample.txt",     "CA"),
    ("T5008",  "ca/t5008_sample.txt",  "CA"),
    ("T2202",  "ca/t2202_sample.txt",  "CA"),
    ("T4A",    "ca/t4a_sample.txt",    "CA"),
    ("RRSP",   "ca/rrsp_sample.txt",   "CA"),
    ("T776",   "ca/t776_sample.txt",   "CA"),
    ("T2125",  "ca/t2125_sample.txt",  "CA"),
    ("T2200",  "ca/t2200_sample.txt",  "CA"),
    ("T4RSP",  "ca/t4rsp_sample.txt",  "CA"),
    ("T4RIF",  "ca/t4rif_sample.txt",  "CA"),
    ("T5013",  "ca/t5013_sample.txt",  "CA"),

    # United States
    ("W-2",       "us/w2_sample.txt",        "US"),
    ("1099-INT",  "us/1099_int_sample.txt",  "US"),
    ("1099-DIV",  "us/1099_div_sample.txt",  "US"),
    ("1099-B",    "us/1099_b_sample.txt",    "US"),
    ("1099-NEC",  "us/1099_nec_sample.txt",  "US"),
    ("1099-MISC", "us/1099_misc_sample.txt", "US"),
    ("1099-R",    "us/1099_r_sample.txt",    "US"),
    ("1099-K",    "us/1099_k_sample.txt",    "US"),
    ("1099-G",    "us/1099_g_sample.txt",    "US"),
    ("1098",      "us/1098_sample.txt",      "US"),
    ("1098-E",    "us/1098_e_sample.txt",    "US"),
    ("1098-T",    "us/1098_t_sample.txt",    "US"),
    ("SSA-1099",  "us/ssa_1099_sample.txt",  "US"),
    ("K-1",       "us/k1_sample.txt",        "US"),
    ("SCH-A",     "us/sch_a_sample.txt",     "US"),
    ("SCH-B",     "us/sch_b_sample.txt",     "US"),
    ("SCH-C",     "us/sch_c_sample.txt",     "US"),
    ("SCH-D",     "us/sch_d_sample.txt",     "US"),
    ("SCH-E",     "us/sch_e_sample.txt",     "US"),
    ("SCH-SE",    "us/sch_se_sample.txt",    "US"),
    ("8949",      "us/8949_sample.txt",      "US"),
    ("8889",      "us/8889_sample.txt",      "US"),
    ("1099-SA",   "us/1099_sa_sample.txt",   "US"),
    ("1099-Q",    "us/1099_q_sample.txt",    "US"),
    ("5498",      "us/5498_sample.txt",      "US"),
    ("1095-A",    "us/1095_a_sample.txt",    "US"),
    ("W-2G",      "us/w2g_sample.txt",       "US"),
    ("2555",      "us/2555_sample.txt",      "US"),

    # CA additions
    ("T1135",     "ca/t1135_sample.txt",     "CA"),
    ("T2222",     "ca/t2222_sample.txt",     "CA"),
]


@pytest.fixture(autouse=True)
def _isolate_llm(monkeypatch):
    """Stub OCR + LLM endpoints so the pipeline is deterministic and offline."""
    stub_client = _StubClient()
    monkeypatch.setattr(parse_docs, "_get_client", lambda: stub_client)
    monkeypatch.setattr(parse_docs, "client", stub_client)
    monkeypatch.setattr(explain_return, "_get_client", lambda: stub_client)
    monkeypatch.setattr(explain_return, "client", stub_client)
    monkeypatch.setattr(classify_forms, "get_client", lambda *a, **k: stub_client)
    monkeypatch.setattr(extract_forms, "get_client", lambda *a, **k: stub_client)
    monkeypatch.setattr(optimize, "get_client", lambda *a, **k: stub_client)
    monkeypatch.setattr(classify_forms, "_llm_classify", lambda text: None)
    monkeypatch.setattr(extract_forms, "_llm_extract", lambda text, form_code: {})
    monkeypatch.setattr(optimize, "_llm_rerank", lambda x: x)


@pytest.mark.parametrize("form_code, fixture, jurisdiction", EVERY_FORM)
def test_each_form_drives_pipeline_to_filing_artifacts(monkeypatch, form_code, fixture, jurisdiction):
    text = (FIXTURES / fixture).read_text(encoding="utf-8")
    raw_bytes = f"FAKE-{form_code}".encode("utf-8")

    # OCR mock: any document body returns this fixture's text.
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda data, mime: text)
    monkeypatch.setattr(classify_forms, "ocr_bytes_to_text", lambda data, mime: text)
    monkeypatch.setattr(extract_forms, "ocr_bytes_to_text", lambda data, mime: text)

    answers = dict(CA_ANSWERS if jurisdiction == "CA" else US_ANSWERS)
    state = GraphState(
        raw_docs=[InputDocument(content=raw_bytes, filename=fixture.split("/")[-1], mime_type="application/pdf")],
        filing_year=2024,
        jurisdictions=[jurisdiction],
        user_answers=answers,
    )

    graph = build_graph()
    final = GraphState.model_validate(graph.invoke(state))

    # 1) Classification + extraction
    assert any(c.form_code == form_code and c.jurisdiction == jurisdiction for c in final.classifications), \
        f"{form_code}: classifier missed it (classifications={[(c.form_code, c.jurisdiction) for c in final.classifications]})"
    assert any(e.form_code == form_code and e.jurisdiction == jurisdiction for e in final.extracts), \
        f"{form_code}: extractor produced nothing"

    # 2) Draft return computed (not paused)
    assert not final.awaiting_clarification, f"{form_code}: pipeline paused at clarifications"
    assert jurisdiction in final.draft_returns, f"{form_code}: no {jurisdiction} draft return"

    # 3) Jurisdiction filing artifacts present and parseable
    if jurisdiction == "CA":
        assert "ca_t1_pdf" in final.filing_artifacts
        assert "ca_netfile_xml" in final.filing_artifacts
        pdf_bytes = base64.b64decode(final.filing_artifacts["ca_t1_pdf"].content_b64)
        # synthetic fallback PDFs from reportlab start with %PDF too
        assert pdf_bytes.startswith(b"%PDF"), f"{form_code}: CA PDF malformed"
        xml_text = base64.b64decode(final.filing_artifacts["ca_netfile_xml"].content_b64).decode("utf-8")
        root = ET.fromstring(xml_text)
        assert root.tag == "T1Return"
        assert root.get("transmissible") == "false"
    else:
        assert "us_1040_pdf" in final.filing_artifacts
        assert "us_mef_json" in final.filing_artifacts
        pdf_bytes = base64.b64decode(final.filing_artifacts["us_1040_pdf"].content_b64)
        assert pdf_bytes.startswith(b"%PDF"), f"{form_code}: US PDF malformed"
        mef = json.loads(base64.b64decode(final.filing_artifacts["us_mef_json"].content_b64))
        assert mef["transmissible"] is False
        assert mef["ReturnData"]["IRS1040"]["line9_total_income"] >= 0

    # 4) YoY planning artifact always present once a draft exists
    assert "yoy_planning" in final.filing_artifacts
