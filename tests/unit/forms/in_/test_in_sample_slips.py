"""The India demo slips in sample_tax_slips/ must parse like the CA ones.

sample_tax_slips/ ships realistic Form 16 / Form 16A demo documents for the
UI "try a sample" flow — parity with the existing CA T4/T5/RRSP demos. These
tests pin the slip *content* (shared with the image/PDF generator) so the demo
slips stay extractable by the FORM-16 / FORM-16A rule extractors, and confirm
the rendered artifacts exist in every supported upload format.
"""

import importlib.util
from pathlib import Path

import wealthtax_agent.forms  # noqa: F401 - populate the extractor registry
from wealthtax_agent.forms.registry import get

_GEN = Path(__file__).resolve().parents[4] / "sample_tax_slips" / "generate_realistic_samples.py"


def _sample_lines(name: str):
    spec = importlib.util.spec_from_file_location("sample_gen", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SAMPLES[name]


def test_form16_demo_slip_extracts_salary_and_deductions():
    extract = get("FORM-16").extract("\n".join(_sample_lines("form16_sample_2025")))
    assert extract.jurisdiction == "IN"
    assert extract.form_code == "FORM-16"
    assert extract.confidence == "high"
    assert extract.fields["gross_salary"] == 1800000.0
    assert extract.fields["basic_salary"] == 900000.0
    assert extract.fields["hra_received"] == 360000.0
    assert extract.fields["standard_deduction_salary"] == 50000.0
    assert extract.fields["section_80c_declared"] == 150000.0
    assert extract.fields["section_80d_declared"] == 25000.0
    assert extract.fields["tds_deducted"] == 184000.0


def test_form16a_demo_slip_extracts_interest_and_tds():
    extract = get("FORM-16A").extract("\n".join(_sample_lines("form16a_sample_2025")))
    assert extract.jurisdiction == "IN"
    assert extract.form_code == "FORM-16A"
    assert extract.fields["interest_income"] == 45000.0
    assert extract.fields["dividend_income"] == 8000.0
    assert extract.fields["tds_deducted"] == 5300.0


def test_demo_slip_artifacts_exist_in_all_upload_formats():
    base = _GEN.parent
    for stem in ("form16_sample_2025", "form16a_sample_2025"):
        for ext in (".png", ".jpg", ".jpeg", ".pdf"):
            assert (base / f"{stem}{ext}").exists(), f"missing {stem}{ext}"
