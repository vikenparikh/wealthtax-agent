"""Tests for the PDF form filler (filing/pdf_fill.py).

The key guarantee is robustness: fill_form must ALWAYS return downloadable
bytes — a real %PDF when reportlab is present, and never crash even when a
template is missing or unfillable. Also pins the path sanitisation, the
YAML loader, and the reportlab-absent text-stub fallback.
"""

import sys
from io import BytesIO
from pathlib import Path

import pypdf
import wealthtax_agent.filing.pdf_fill as pdf_fill
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from wealthtax_agent.filing.pdf_fill import (
    _acroform_fill,
    _load_yaml,
    _synthetic_pdf,
    _template_paths,
    _text_overlay_fill,
    fill_form,
)


def _write_acroform_pdf(path: Path, field_name: str = "f1_01") -> None:
    """Build a minimal fillable AcroForm PDF with a single text field.

    NOTE: c.showPage() MUST be called before c.save() or reportlab raises
    KeyError 'Page1' when emitting the AcroForm.
    """
    c = canvas.Canvas(str(path), pagesize=letter)
    c.acroForm.textfield(name=field_name, x=72, y=700, width=200, height=20)
    c.showPage()
    c.save()


def _write_plain_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawString(72, 700, "plain template")
    c.showPage()
    c.save()


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


# --- _acroform_fill (covers 45-46, 49-60) ---------------------------------


def test_acroform_fill_writes_field_value(tmp_path):
    pdf = tmp_path / "T1.pdf"
    _write_acroform_pdf(pdf)
    out = _acroform_fill(pdf, {"employment_income": "f1_01"}, {"employment_income": 84500})
    assert out is not None
    assert out.startswith(b"%PDF")
    fields = pypdf.PdfReader(BytesIO(out)).get_fields()
    assert fields["f1_01"]["/V"] == "84500"


def test_acroform_fill_empty_mapping_returns_none(tmp_path):
    # The fieldmap key is absent from the values dict -> nothing mapped -> None.
    pdf = tmp_path / "T1.pdf"
    _write_acroform_pdf(pdf)
    assert _acroform_fill(pdf, {"employment_income": "f1_01"}, {"other": 1}) is None


def test_acroform_fill_import_error_returns_none(tmp_path, monkeypatch):
    pdf = tmp_path / "T1.pdf"
    _write_acroform_pdf(pdf)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    assert _acroform_fill(pdf, {"employment_income": "f1_01"}, {"employment_income": 84500}) is None


# --- _text_overlay_fill (covers 66-96) ------------------------------------


def test_text_overlay_fill_merges_overlay(tmp_path):
    pdf = tmp_path / "T1.pdf"
    _write_plain_pdf(pdf)
    out = _text_overlay_fill(pdf, {"wages": {"x": 100, "y": 700}}, {"wages": 84000})
    assert out is not None
    assert out.startswith(b"%PDF")


def test_text_overlay_fill_import_error_returns_none(tmp_path, monkeypatch):
    pdf = tmp_path / "T1.pdf"
    _write_plain_pdf(pdf)
    monkeypatch.setitem(sys.modules, "reportlab.pdfgen", None)
    assert _text_overlay_fill(pdf, {"wages": {"x": 100, "y": 700}}, {"wages": 84000}) is None


# --- fill_form template dispatch (covers 141-144, 146-149) -----------------


def test_fill_form_uses_acroform_when_template_present(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_fill, "TEMPLATES_ROOT", tmp_path)
    base = tmp_path / "ca" / "2025"
    base.mkdir(parents=True)
    _write_acroform_pdf(base / "T1.pdf")
    (base / "T1.fieldmap.yaml").write_text("employment_income: f1_01\n", encoding="utf-8")
    data = fill_form("CA", 2025, "T1", {"employment_income": 84500})
    assert data.startswith(b"%PDF")
    fields = pypdf.PdfReader(BytesIO(data)).get_fields()
    assert fields["f1_01"]["/V"] == "84500"


def test_fill_form_uses_overlay_when_only_coordmap(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_fill, "TEMPLATES_ROOT", tmp_path)
    base = tmp_path / "ca" / "2025"
    base.mkdir(parents=True)
    _write_plain_pdf(base / "T1.pdf")
    # No fieldmap -> acroform branch skipped; coordmap drives the overlay path.
    (base / "T1.coordmap.yaml").write_text("wages:\n  x: 100\n  y: 700\n", encoding="utf-8")
    data = fill_form("CA", 2025, "T1", {"wages": 84000})
    assert data.startswith(b"%PDF")


# --- _synthetic_pdf pagination (covers 127-128) ----------------------------


def test_synthetic_pdf_paginates_long_value_dict():
    # y starts at 650, decrements 16 per item; showPage() fires once y < 72.
    # (650 - 72) / 16 ~= 36.1, so ~37 items are needed; pass 60 to be safe.
    values = {f"key_{i}": i for i in range(60)}
    data = _synthetic_pdf("CA", 2025, "T1", values)
    assert data.startswith(b"%PDF")
    # A multi-page PDF: confirm pagination actually produced >1 page.
    assert len(pypdf.PdfReader(BytesIO(data)).pages) >= 2
