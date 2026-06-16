"""Excess CPP/EI contributions from multiple employers are a refundable
overpayment (T1 lines 44800/45000), not a 15% non-refundable credit.

When a Canadian works for 2+ employers, each withholds CPP and EI independently,
so combined withholding routinely exceeds the annual employee maximum. The excess
is refunded in full (CA analog of the US excess-Social-Security feature, PR #74).
Single-employer over-withholding is the employer's to correct, so this requires
2+ T4 slips.
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract

# 2024 federal employee maxima (config/tax_tables/ca/2024.yaml):
#   cpp.max_contribution = 3867.50 ; ei.max_contribution = 1049.12
CPP_MAX_2024 = 3867.50
EI_MAX_2024 = 1049.12


def _t4(emp_income, cpp, ei, withheld):
    return FormExtract(
        form_code="T4",
        jurisdiction="CA",
        fields={
            "employment_income": emp_income,
            "income_tax_deducted": withheld,
            "cpp_contributions": cpp,
            "ei_premiums": ei,
        },
    )


def test_two_employers_over_max_refunds_the_excess():
    # Combined CPP 2500+2000 = 4500 (> 3867.50); EI 700+500 = 1200 (> 1049.12)
    extracts = [
        _t4(45000, 2500.0, 700.0, 8000.0),
        _t4(40000, 2000.0, 500.0, 7000.0),
    ]
    d = compute_ca_return(extracts, year=2024, province="ON")
    assert d.line_items["cpp_overpayment"] == round(4500.0 - CPP_MAX_2024, 2)  # 632.50
    assert d.line_items["ei_overpayment"] == round(1200.0 - EI_MAX_2024, 2)    # 150.88
    assert d.line_items["cpp_ei_overpayment"] == 783.38


def test_single_employer_over_max_is_not_refunded():
    # One T4 over the max: the employer corrects it, so no overpayment refund.
    extracts = [_t4(120000, 4500.0, 1200.0, 25000.0)]
    d = compute_ca_return(extracts, year=2024, province="ON")
    assert d.line_items["cpp_ei_overpayment"] == 0.0


def test_two_employers_under_max_no_overpayment_full_credit_retained():
    # Combined CPP 1500+1000 = 2500 (< max); EI 400+300 = 700 (< max).
    extracts = [
        _t4(30000, 1500.0, 400.0, 4000.0),
        _t4(25000, 1000.0, 300.0, 3000.0),
    ]
    d = compute_ca_return(extracts, year=2024, province="ON")
    assert d.line_items["cpp_ei_overpayment"] == 0.0
    # Full contributions still earn the non-refundable credit (no regression):
    # creditable base = 2500 + 700 = 3200, federal lowest rate.
    assert d.line_items["cpp_ei_credit"] > 0.0


def test_overpayment_increases_refund_vs_single_employer_baseline():
    # Same total contributions/withholding; only the employer count differs.
    # Withholding is set high enough that both filers are in a refund position,
    # so the refunded overpayment surfaces as a refund delta (not just less owing).
    two = [
        _t4(45000, 2500.0, 700.0, 12000.0),
        _t4(40000, 2000.0, 500.0, 11000.0),
    ]
    one = [_t4(85000, 4500.0, 1200.0, 23000.0)]
    d_two = compute_ca_return(two, year=2024, province="ON")
    d_one = compute_ca_return(one, year=2024, province="ON")
    # The refunded overpayment ($783.38) dominates the small credit reduction,
    # so the multi-employer filer ends up with a strictly larger refund.
    assert d_two.estimated_refund > d_one.estimated_refund
