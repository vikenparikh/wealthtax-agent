"""US education credits — AOTC + Lifetime Learning (Form 8863)."""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _edu(box1=0.0, box5=0.0, wages=50000.0, **answers):
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages}),
    ]
    if box1 or box5:
        extracts.append(FormExtract(form_code="1098-T", jurisdiction="US", fields={
            "qualified_tuition_payments": box1,
            "scholarships_or_grants": box5,
        }))
    ua = {"filing_status": "single", "num_dependents": "0"}
    ua.update(answers)
    return compute_us_return(extracts, year=2024, user_answers=ua)


def test_aotc_full_credit_low_magi():
    # single, MAGI ~$50k, 1 student, $4,000 tuition, no scholarship.
    # AOTC = 2000 + 0.25*2000 = $2,500; 40% refundable = $1,000.
    d = _edu(box1=4000.0, wages=50000.0)
    li = d.line_items
    assert li["qualified_education_expense"] == 4000.0
    assert li["education_credit_aotc"] == 2500.0
    assert li["education_credit_chosen"] == 2500.0
    assert li["education_credit_refundable"] == 1000.0
    assert li["education_credit_nonrefundable"] == 1500.0


def test_aotc_phaseout_half():
    # single, MAGI ~$85k → phaseout factor 0.5 → chosen $1,250.
    d = _edu(box1=4000.0, wages=85000.0)
    li = d.line_items
    assert li["education_credit_chosen"] == 1250.0
    assert li["education_credit_refundable"] == 500.0
    assert li["education_credit_nonrefundable"] == 750.0


def test_aotc_net_of_scholarship():
    # box1 $4,000 less box5 $1,500 = $2,500 net.
    # AOTC = 2000 + 0.25*500 = $2,125; 40% refundable = $850.
    d = _edu(box1=4000.0, box5=1500.0, wages=50000.0)
    li = d.line_items
    assert li["qualified_education_expense"] == 2500.0
    assert li["education_credit_aotc"] == 2125.0
    assert li["education_credit_chosen"] == 2125.0
    assert li["education_credit_refundable"] == 850.0
    assert li["education_credit_nonrefundable"] == 1275.0


def test_llc_chosen_when_not_aotc_eligible():
    # aotc_eligible=False → only Lifetime Learning (20% of expense, non-refundable).
    d = _edu(box1=4000.0, wages=50000.0, aotc_eligible=False)
    li = d.line_items
    assert li["education_credit_llc"] == 800.0  # 20% * 4000
    assert li["education_credit_chosen"] == 800.0
    assert li["education_credit_refundable"] == 0.0
    assert li["education_credit_nonrefundable"] == 800.0


def test_llc_expense_cap():
    # LLC caps qualified expense at $10,000 → max $2,000.
    d = _edu(box1=20000.0, wages=50000.0, aotc_eligible=False)
    assert d.line_items["education_credit_llc"] == 2000.0


def test_nl_intake_tuition_spelling_still_credits():
    # NL intake / manual entry uses "qualified_education_expense"; must still credit.
    extracts = [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 50000.0})]
    d = compute_us_return(extracts, year=2024, user_answers={
        "filing_status": "single", "num_dependents": "0",
        "qualified_education_expense": 4000.0,
    })
    assert d.line_items["education_credit_chosen"] == 2500.0


def test_no_expense_zero_credit():
    d = _edu(wages=50000.0)
    assert d.line_items["education_credit_chosen"] == 0.0
    assert d.line_items["qualified_education_expense"] == 0.0


def test_full_magi_phaseout_zero():
    # single, MAGI >= $90k → credit fully phased out.
    d = _edu(box1=4000.0, wages=95000.0)
    assert d.line_items["education_credit_chosen"] == 0.0


def test_refundable_increases_refund():
    # The refundable AOTC should flow into the balance as a payment. With
    # withholding covering the tax, a refund materializes; the delta vs the
    # no-credit baseline is the full credit (nonrefundable + refundable).
    def _run(box1):
        extracts = [FormExtract(form_code="W-2", jurisdiction="US", fields={
            "wages": 50000.0, "federal_income_tax_withheld": 8000.0})]
        if box1:
            extracts.append(FormExtract(form_code="1098-T", jurisdiction="US",
                                        fields={"qualified_tuition_payments": box1}))
        return compute_us_return(extracts, year=2024,
                                 user_answers={"filing_status": "single", "num_dependents": "0"})
    delta = _run(4000.0).estimated_refund - _run(0.0).estimated_refund
    assert delta >= 1000.0 - 0.01
