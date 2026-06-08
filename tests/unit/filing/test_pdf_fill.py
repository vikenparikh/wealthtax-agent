"""Tests for the PDF form filler (filing/pdf_fill.py).

The key guarantee is robustness: fill_form must ALWAYS return downloadable
bytes — a real %PDF when reportlab is present, and never crash even when a
template is missing or unfillable. Also pins the path sanitisation, the
YAML loader, and the reportlab-absent text-stub fallback.
"""

import sys
from pathlib import Path

import wealthtax_agent.filing.pdf_fill as pdf_fill
from wealthtax_agent.filing.pdf_fill import _load_yaml, _synthetic_pdf, _template_paths, fill_form


def test_template_paths_sanitizes_form_code_and_structure():
    paths = _template_paths("CA", 2025, "T1/General")
    assert paths["pdf"].name == "T1_General.pdf"
    assert paths["fieldmap"].name == "T1_General.fieldmap.yaml"
    assert paths["coordmap"].name == "T1_General.coordmap.yaml"
    assert "ca/2025" in str(paths["pdf"]).replace("\\", "/").lower()


def test_load_yaml_missing_returns_empty_dict():
    assert _load_yaml(Path("/no/such/file.yaml")) == {}


def test_load_yaml_reads_mapping(tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("a: 1\nb: two\n", encoding="utf-8")
    assert _load_yaml(f) == {"a": 1, "b": "two"}


def test_fill_form_without_template_emits_valid_synthetic_pdf():
    data = fill_form("CA", 2025, "T4", {"employment_income": 84500})
    assert isinstance(data, bytes)
    assert data[:4] == b"%PDF"


def test_synthetic_pdf_is_valid_pdf():
    data = _synthetic_pdf("US", 2025, "1040", {"wages": 84000})
    assert data[:4] == b"%PDF"
    assert b"%%EOF" in data


def test_synthetic_pdf_falls_back_to_text_stub_without_reportlab(monkeypatch):
    # Simulate reportlab being unavailable: the import inside _synthetic_pdf
    # raises, and the function emits a minimal text stub instead of crashing.
    monkeypatch.setitem(sys.modules, "reportlab.pdfgen", None)
    data = _synthetic_pdf("CA", 2025, "T5", {"interest": 100})
    assert data.startswith(b"% DRAFT CA/2025/T5")
    assert b"interest: 100" in data


def test_fill_form_falls_back_to_synthetic_when_template_unfillable(tmp_path, monkeypatch):
    # A present-but-invalid template + fieldmap must not crash fill_form;
    # the acroform path returns None and it falls through to the synthetic draft.
    monkeypatch.setattr(pdf_fill, "TEMPLATES_ROOT", tmp_path)
    base = tmp_path / "ca" / "2025"
    base.mkdir(parents=True)
    (base / "T4.pdf").write_bytes(b"not a real pdf")
    (base / "T4.fieldmap.yaml").write_text("employment_income: f1_01\n", encoding="utf-8")
    data = fill_form("CA", 2025, "T4", {"employment_income": 84500})
    assert data[:4] == b"%PDF"
