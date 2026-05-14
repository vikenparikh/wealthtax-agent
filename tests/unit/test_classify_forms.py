from wealthtax_agent.classify_forms import _heuristic_classify


def test_t4_heuristic_match():
    text = "T4 Statement of Remuneration Paid\nBox 14 Employment income: 50000"
    classification = _heuristic_classify(text)
    assert classification is not None
    assert classification.form_code == "T4"
    assert classification.jurisdiction == "CA"


def test_w2_heuristic_match():
    text = "Form W-2 Wage and Tax Statement\nBox 1 wages: 70000"
    classification = _heuristic_classify(text)
    assert classification is not None
    assert classification.form_code == "W-2"
    assert classification.jurisdiction == "US"


def test_unrecognised_text_returns_none():
    text = "This is a random document with no form markers."
    assert _heuristic_classify(text) is None
