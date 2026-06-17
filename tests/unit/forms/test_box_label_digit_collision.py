"""Box-label digit collision in find_box_amount.

The 1099-DIV box-5 label is the one supported box label whose descriptive text
contains digits: "Section 199A dividends". The box-5 extractor's `[^0-9]*`
prefix stopped at the first digit it found — the "199" inside "199A" — capturing
$199 instead of the real amount, silently understating the §199A QBI deduction
and overstating tax on every 1099-DIV with REIT/PTP dividends.
"""
from wealthtax_agent.forms._helpers import find_box_amount
from wealthtax_agent.forms.us.i1099_div import Form1099DivExtractor


def test_box5_199a_label_does_not_poison_amount():
    # The "199" in "199A" must NOT be captured as the box-5 amount.
    assert find_box_amount("Box 5 Section 199A dividends 4000.00", "5") == 4000.0


def test_box_amount_with_plain_label_unchanged():
    assert find_box_amount("Box 1 Wages 65000.00", "1") == 65000.0


def test_box_amount_that_is_genuinely_199_still_works():
    # A real $199 amount (no trailing letter) must still be read.
    assert find_box_amount("Box 5 Section 199A dividends 199.00", "5") == 199.0
    assert find_box_amount("Box 3 199", "3") == 199.0


def test_1099_div_extractor_reads_full_box5_amount():
    text = (
        "1099-DIV\n"
        "Box 1a Total ordinary dividends 6000.00\n"
        "Box 1b Qualified dividends 5000.00\n"
        "Box 5 Section 199A dividends 4000.00\n"
    )
    extract = Form1099DivExtractor().extract(text)
    assert extract.fields["section_199A_dividends"] == 4000.0
