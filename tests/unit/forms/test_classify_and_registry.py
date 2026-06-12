"""Tests for the form-classification scoring (forms/base.py) and the extractor
registry (forms/registry.py) — the routing backbone of the extraction pipeline.

classify() returns the length of the longest matching pattern so the registry
can pick the most specific form (e.g. 1098-E over 1098). The registry keys on
an upper-cased form_code and supports jurisdiction-filtered listing.
"""

import pytest

import wealthtax_agent.forms  # noqa: F401 - populate the registry
import wealthtax_agent.forms.registry as registry
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


def _extractor(patterns, *, jurisdiction="US", form_code="FAKE"):
    class _E(FormExtractor):
        def extract(self, text, source_filename=None):
            return FormExtract(form_code=form_code, jurisdiction=jurisdiction)

    e = _E()
    e.classification_patterns = tuple(patterns)
    e.jurisdiction = jurisdiction
    e.form_code = form_code
    return e


# --- classify scoring --------------------------------------------------------


def test_classify_returns_none_when_no_pattern_matches():
    assert _extractor(["1098-E"]).classify("an unrelated W-2 form") is None


def test_classify_is_case_insensitive_and_scores_pattern_length():
    score = _extractor(["Form 16"]).classify("CERTIFICATE — FORM 16 — ISSUED")
    assert score == float(len("Form 16"))  # 7.0


def test_classify_picks_the_longest_matching_pattern():
    e = _extractor(["1098", "1098-E"])
    assert e.classify("this is a 1098-E student loan doc") == float(len("1098-E"))  # 6.0


def test_classify_scores_only_the_pattern_actually_present():
    e = _extractor(["1098", "1098-E"])
    # only the short pattern is present (no "-E"), so the score is len("1098")
    assert e.classify("a 1098-T tuition statement that also says 1098") == 4.0


def test_classify_always_returns_float_on_match():
    assert isinstance(_extractor(["W-2"]).classify("my w-2 wages"), float)


# --- registry ----------------------------------------------------------------


@pytest.fixture
def restore_registry():
    snapshot = dict(registry._REGISTRY)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(snapshot)


def test_register_and_get_are_case_insensitive(restore_registry):
    @register
    class _Zed(FormExtractor):
        jurisdiction = "US"
        form_code = "ZED"

        def extract(self, text, source_filename=None):
            return FormExtract(form_code="ZED", jurisdiction="US")

    assert registry.get("ZED") is not None
    assert registry.get("zed") is not None  # lookup upper-cases the key


def test_register_raises_without_form_code(restore_registry):
    with pytest.raises(ValueError, match="no form_code"):

        @register
        class _NoCode(FormExtractor):
            form_code = ""

            def extract(self, text, source_filename=None):
                return FormExtract(form_code="x", jurisdiction="US")


def test_get_unknown_form_code_returns_none():
    assert registry.get("NO-SUCH-FORM") is None


def test_supported_form_codes_filtered_by_jurisdiction_and_sorted():
    ca = registry.supported_form_codes("CA")
    assert "T4" in ca
    assert ca == sorted(ca)
    assert all(registry.get(code).jurisdiction == "CA" for code in ca)
    # jurisdictions are disjoint
    assert "T4" not in registry.supported_form_codes("US")
    assert "FORM-16" in registry.supported_form_codes("IN")


def test_supported_form_codes_all_when_no_jurisdiction():
    allcodes = registry.supported_form_codes()
    assert allcodes == sorted(allcodes)
    assert "T4" in allcodes and "FORM-16" in allcodes


def test_all_extractors_returns_form_extractor_instances():
    exts = registry.all_extractors()
    assert exts and all(isinstance(e, FormExtractor) for e in exts)
