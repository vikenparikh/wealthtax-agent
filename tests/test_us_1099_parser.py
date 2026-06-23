"""tests/test_us_1099_parser.py — unit tests for US form parsers."""

from __future__ import annotations

import pytest

from wealthtax_agent.parsers.base import ParsedSlip
from wealthtax_agent.parsers.us.form_1099_b import parse_1099b
from wealthtax_agent.parsers.us.form_1099_div import parse_1099div
from wealthtax_agent.parsers.us.form_1099_int import parse_1099int
from wealthtax_agent.parsers.us.form_w2 import parse_w2
from wealthtax_agent.parsers.us.form_k1 import parse_k1


# ---------------------------------------------------------------------------
# Fixtures — realistic but synthetic form text
# ---------------------------------------------------------------------------

_1099B_TEXT = """
CORRECTED (if checked)
1099-B                          2024
Proceeds from Broker and Barter Exchange Transactions

Payer: Fidelity Investments
1d. Proceeds:   $48,250.00
1e. Cost Basis: $45,000.00
Box 2: Short-term (covered)
Box 1g. Wash Sale Loss Disallowed: $0.00
Description: QQQ 1/5/2024 - 100 shares
"""

_1099B_WASH_TEXT = """
1099-B 2024
Proceeds from Broker
1d. Proceeds: $9,500.00
1e. Cost Basis: $10,000.00
Long-term
Wash sale loss disallowed: $500.00
Description: AAPL 100 shares
"""

_1099DIV_TEXT = """
1099-DIV  Tax Year: 2024
Box 1a. Total Ordinary Dividends: $3,200.00
Box 1b. Qualified Dividends: $2,800.00
Box 2a. Total Capital Gain Distributions: $1,500.00
Box 4. Federal Income Tax Withheld: $640.00
"""

_1099INT_TEXT = """
1099-INT  2024
Interest Income
Box 1. Interest Income: $1,250.75
Box 3. Interest on U.S. Savings Bonds: $300.00
Box 4. Federal Income Tax Withheld: $125.00
"""

_W2_TEXT = """
W-2 Wage and Tax Statement
2024
Box 1. Wages, Tips, Other Compensation: $95,000.00
Box 2. Federal Income Tax Withheld: $18,050.00
Box 3. Social Security Wages: $95,000.00
Box 4. Social Security Tax Withheld: $5,890.00
Box 5. Medicare Wages: $95,000.00
Box 6. Medicare Tax Withheld: $1,377.50
Box 16. State Wages: $95,000.00
Box 17. State Income Tax: $7,125.00
Employer's Name: Acme Corporation Inc
"""

_K1_PARTNER_TEXT = """
Schedule K-1 (Form 1065) 2024
Partnership Name: Parikh Family LP
Box 1. Ordinary Business Income (Loss): $25,000.00
Box 5. Interest Income: $1,200.00
Box 6a. Ordinary Dividends: $800.00
Box 8. Net Short-Term Capital Gain (Loss): -$500.00
Box 9a. Net Long-Term Capital Gain (Loss): $4,200.00
"""


# ---------------------------------------------------------------------------
# 1099-B tests
# ---------------------------------------------------------------------------

class TestParse1099B:
    def test_returns_parsed_slip(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        assert isinstance(slip, ParsedSlip)

    def test_jurisdiction_us(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        assert slip.jurisdiction == "US"

    def test_form_type(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        assert slip.form_type == "1099-B"

    def test_tax_year(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        assert slip.tax_year == 2024

    def test_proceeds_extracted(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        assert slip.fields["proceeds"] == pytest.approx(48_250.0)

    def test_cost_basis_extracted(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        assert slip.fields["cost_basis"] == pytest.approx(45_000.0)

    def test_gain_loss_computed(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        assert slip.fields["gain_loss"] == pytest.approx(3_250.0)

    def test_short_term_flag(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        assert slip.fields.get("term") == 0.0

    def test_long_term_flag(self):
        slip = parse_1099b(_1099B_WASH_TEXT, use_llm_fallback=False)
        assert slip.fields.get("term") == 1.0

    def test_wash_sale_amount(self):
        slip = parse_1099b(_1099B_WASH_TEXT, use_llm_fallback=False)
        assert slip.fields.get("wash_sale_loss_disallowed") == pytest.approx(500.0)

    def test_high_confidence_when_both_fields(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        assert slip.confidence == "high"

    def test_source_filename_propagated(self):
        slip = parse_1099b(_1099B_TEXT, source_filename="broker.pdf", use_llm_fallback=False)
        assert slip.source_filename == "broker.pdf"

    def test_empty_text_low_confidence(self):
        slip = parse_1099b("no relevant content here", use_llm_fallback=False)
        assert slip.confidence == "low"

    def test_to_form_extract_dict_shape(self):
        slip = parse_1099b(_1099B_TEXT, use_llm_fallback=False)
        d = slip.to_form_extract_dict()
        assert d["form_code"] == "1099-B"
        assert d["jurisdiction"] == "US"
        assert "proceeds" in d["fields"]


# ---------------------------------------------------------------------------
# 1099-B LLM-fallback tests
# ---------------------------------------------------------------------------

# Low-confidence text: no proceeds / cost / wash-sale / long|short-term tokens,
# so the rule pass produces fields == {} and confidence == "low", which is the
# gate that triggers _llm_fallback when use_llm_fallback=True.
_1099B_LOW_TEXT = "Brokerage statement for 2023. Account summary unavailable."

# Same but with NO year token at all (rule tax_year is None).
_1099B_LOW_NOYEAR_TEXT = "Brokerage statement. Account summary unavailable."


class _FakeLLM:
    """Stub matching the real ClaudeCLILLM.complete_json(prompt, schema_hint) interface.

    ``_llm_fallback`` calls ``llm.complete_json(prompt, schema)`` positionally,
    so this stub accepts the same two positional args.
    """

    def __init__(self, payload, raise_exc=False):
        self._payload = payload
        self._raise = raise_exc
        self.calls = []

    def complete_json(self, prompt, schema_hint, default=None):
        self.calls.append((prompt, schema_hint))
        if self._raise:
            raise RuntimeError("boom")
        return self._payload


def _patch_llm(monkeypatch, payload=None, raise_exc=False):
    fake = _FakeLLM(payload or {}, raise_exc=raise_exc)
    monkeypatch.setattr(
        "wealthtax_agent.services.claude_llm.get_tax_llm",
        lambda: fake,
    )
    return fake


class TestForm1099BLLMFallback:
    def test_low_confidence_triggers_llm_and_marks_extractor_llm(self, monkeypatch):
        # Covers the gate (78-80) + the LLM success path building a ParsedSlip.
        _patch_llm(
            monkeypatch,
            {
                "proceeds": "1000",
                "cost_basis": "750",
                "gain_loss": "250",
                "tax_year": 2022,
                "description": "ACME stock",
            },
        )
        slip = parse_1099b(_1099B_LOW_TEXT, use_llm_fallback=True)
        assert slip.extractor == "llm"
        assert slip.confidence == "medium"
        assert slip.jurisdiction == "US"
        assert slip.form_type == "1099-B"

    def test_numeric_fields_coerced_to_float_meta_excluded(self, monkeypatch):
        # Field-build loop: numeric keys -> float; tax_year/description excluded
        # from fields; tax_year lands on slip.tax_year; description -> text_fields.
        _patch_llm(
            monkeypatch,
            {
                "proceeds": "1000",
                "cost_basis": 750.5,
                "tax_year": 2021,
                "description": "ACME 100sh",
            },
        )
        slip = parse_1099b(_1099B_LOW_TEXT, use_llm_fallback=True)
        assert slip.fields["proceeds"] == pytest.approx(1000.0)
        assert isinstance(slip.fields["proceeds"], float)
        assert slip.fields["cost_basis"] == pytest.approx(750.5)
        assert "tax_year" not in slip.fields
        assert "description" not in slip.fields
        assert slip.tax_year == 2021
        assert slip.text_fields["description"] == "ACME 100sh"

    def test_none_valued_field_excluded_from_fields(self, monkeypatch):
        # v is None -> key dropped by the comprehension's `v is not None` guard.
        _patch_llm(
            monkeypatch,
            {
                "proceeds": 500.0,
                "wash_sale_loss_disallowed": None,
                "tax_year": 2022,
                "description": "X",
            },
        )
        slip = parse_1099b(_1099B_LOW_TEXT, use_llm_fallback=True)
        assert slip.fields["proceeds"] == pytest.approx(500.0)
        assert "wash_sale_loss_disallowed" not in slip.fields

    def test_tax_year_none_falls_back_to_rule_year(self, monkeypatch):
        # LLM tax_year None -> `result.get("tax_year") or tax_year` uses rule year.
        _patch_llm(
            monkeypatch,
            {"proceeds": 100.0, "tax_year": None, "description": ""},
        )
        slip = parse_1099b(_1099B_LOW_TEXT, use_llm_fallback=True)
        # _1099B_LOW_TEXT contains "2023" which the rule pass parses.
        assert slip.tax_year == 2023
        assert slip.extractor == "llm"

    def test_llm_raises_falls_through_to_rule(self, monkeypatch):
        # except path (131-133) returns None -> parse_1099b returns rule slip.
        _patch_llm(monkeypatch, raise_exc=True)
        slip = parse_1099b(_1099B_LOW_TEXT, use_llm_fallback=True)
        assert slip.extractor == "rule"
        assert slip.confidence == "low"
        assert slip.fields == {}

    def test_fallback_disabled_stays_rule(self, monkeypatch):
        # Gate pinned: use_llm_fallback=False -> LLM never consulted.
        fake = _patch_llm(monkeypatch, {"proceeds": 1.0})
        slip = parse_1099b(_1099B_LOW_TEXT, use_llm_fallback=False)
        assert slip.extractor == "rule"
        assert slip.confidence == "low"
        assert fake.calls == []


# ---------------------------------------------------------------------------
# 1099-DIV tests
# ---------------------------------------------------------------------------

class TestParse1099Div:
    def test_ordinary_dividends(self):
        slip = parse_1099div(_1099DIV_TEXT)
        assert slip.fields["ordinary_dividends"] == pytest.approx(3_200.0)

    def test_qualified_dividends(self):
        slip = parse_1099div(_1099DIV_TEXT)
        assert slip.fields["qualified_dividends"] == pytest.approx(2_800.0)

    def test_capital_gain_distributions(self):
        slip = parse_1099div(_1099DIV_TEXT)
        assert slip.fields["total_capital_gain_distr"] == pytest.approx(1_500.0)

    def test_withholding(self):
        slip = parse_1099div(_1099DIV_TEXT)
        assert slip.fields["federal_income_tax_withheld"] == pytest.approx(640.0)

    def test_jurisdiction(self):
        assert parse_1099div(_1099DIV_TEXT).jurisdiction == "US"

    def test_form_type(self):
        assert parse_1099div(_1099DIV_TEXT).form_type == "1099-DIV"

    def test_tax_year(self):
        assert parse_1099div(_1099DIV_TEXT).tax_year == 2024


# ---------------------------------------------------------------------------
# 1099-INT tests
# ---------------------------------------------------------------------------

class TestParse1099Int:
    def test_interest_income(self):
        slip = parse_1099int(_1099INT_TEXT)
        assert slip.fields["interest_income"] == pytest.approx(1_250.75)

    def test_savings_bond_interest(self):
        slip = parse_1099int(_1099INT_TEXT)
        assert slip.fields["us_savings_bond_interest"] == pytest.approx(300.0)

    def test_withholding(self):
        slip = parse_1099int(_1099INT_TEXT)
        assert slip.fields["federal_income_tax_withheld"] == pytest.approx(125.0)

    def test_form_type(self):
        assert parse_1099int(_1099INT_TEXT).form_type == "1099-INT"


# ---------------------------------------------------------------------------
# W-2 tests
# ---------------------------------------------------------------------------

class TestParseW2:
    def test_wages(self):
        slip = parse_w2(_W2_TEXT)
        assert slip.fields["wages_tips_other"] == pytest.approx(95_000.0)

    def test_federal_withholding(self):
        slip = parse_w2(_W2_TEXT)
        assert slip.fields["federal_income_tax_withheld"] == pytest.approx(18_050.0)

    def test_ss_tax(self):
        slip = parse_w2(_W2_TEXT)
        assert slip.fields["social_security_tax_withheld"] == pytest.approx(5_890.0)

    def test_medicare_tax(self):
        slip = parse_w2(_W2_TEXT)
        assert slip.fields["medicare_tax_withheld"] == pytest.approx(1_377.5)

    def test_state_tax(self):
        slip = parse_w2(_W2_TEXT)
        assert slip.fields["state_income_tax"] == pytest.approx(7_125.0)

    def test_employer_name(self):
        slip = parse_w2(_W2_TEXT)
        assert "Acme" in slip.text_fields.get("employer_name", "")

    def test_form_type(self):
        assert parse_w2(_W2_TEXT).form_type == "W-2"

    def test_tax_year(self):
        assert parse_w2(_W2_TEXT).tax_year == 2024

    def test_high_confidence_with_wages(self):
        slip = parse_w2(_W2_TEXT)
        assert slip.confidence == "high"


# ---------------------------------------------------------------------------
# K-1 tests
# ---------------------------------------------------------------------------

class TestParseK1:
    def test_ordinary_income(self):
        slip = parse_k1(_K1_PARTNER_TEXT)
        assert slip.fields["ordinary_business_income_loss"] == pytest.approx(25_000.0)

    def test_interest_income(self):
        slip = parse_k1(_K1_PARTNER_TEXT)
        assert slip.fields["interest_income"] == pytest.approx(1_200.0)

    def test_short_term_cg(self):
        slip = parse_k1(_K1_PARTNER_TEXT)
        assert slip.fields["net_short_term_capital_gain"] == pytest.approx(-500.0)

    def test_long_term_cg(self):
        slip = parse_k1(_K1_PARTNER_TEXT)
        assert slip.fields["net_long_term_capital_gain"] == pytest.approx(4_200.0)

    def test_entity_type_1065(self):
        slip = parse_k1(_K1_PARTNER_TEXT)
        assert slip.text_fields.get("k1_type") == "1065"

    def test_form_type(self):
        assert parse_k1(_K1_PARTNER_TEXT).form_type == "K-1"

    def test_tax_year(self):
        assert parse_k1(_K1_PARTNER_TEXT).tax_year == 2024
