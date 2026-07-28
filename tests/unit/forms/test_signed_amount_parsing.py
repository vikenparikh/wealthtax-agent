"""Signed monetary-amount parsing in forms._helpers.

The two parser functions (`find_box_amount`, `extract_amount_from_matching_line`)
are the SINGLE sign source for the tax engines. A loss must parse NEGATIVE:
- a positive-parsed loss inflates taxable gains, and
- it is invisible to wash-sale detection.

Two negative notations must be honoured (positives stay byte-identical):
1. Leading minus: `-1,000.00`, `$-1,000.00`.
2. Accounting parentheses (balanced): `(1,500.00)`, `($1,500.00)`.
"""
from wealthtax_agent.forms._helpers import (
    extract_amount_from_matching_line,
    find_box_amount,
)
from wealthtax_agent.forms.us.i8949 import Form8949Extractor
from wealthtax_agent.forms.us.sch_d import ScheduleDExtractor


# --- find_box_amount: signed ------------------------------------------------

def test_find_box_amount_leading_minus():
    assert find_box_amount("Box 1e Cost basis -1,000.00", "1e") == -1000.0


def test_find_box_amount_parentheses():
    assert find_box_amount("Box 2 (1,500.00)", "2") == -1500.0


def test_find_box_amount_positive_unchanged():
    assert find_box_amount("Box 1 1,000.00", "1") == 1000.0


# --- extract_amount_from_matching_line: signed ------------------------------

def test_extract_line_parentheses():
    assert (
        extract_amount_from_matching_line("Total gain/loss: (1,500.00)", r"total\s+gain")
        == -1500.0
    )


def test_extract_line_leading_minus():
    assert (
        extract_amount_from_matching_line(
            "Net short-term capital gain: -2,000.00", r"net\s+short"
        )
        == -2000.0
    )


def test_extract_line_positive_unchanged():
    assert (
        extract_amount_from_matching_line("Interest income: 1,000.00", r"interest")
        == 1000.0
    )


# --- EDGES (pinned behaviour) -----------------------------------------------

def test_dollar_sign_with_leading_minus():
    assert find_box_amount("Box 1 $-1,000.00", "1") == -1000.0
    assert (
        extract_amount_from_matching_line("Amount: $-1,000.00", r"amount") == -1000.0
    )


def test_dollar_sign_inside_parentheses():
    assert find_box_amount("Box 1 ($1,500.00)", "1") == -1500.0
    assert (
        extract_amount_from_matching_line("Amount: ($1,500.00)", r"amount") == -1500.0
    )


def test_bare_minus_returns_none():
    # A bare "-" with no following magnitude is not a number → None.
    assert find_box_amount("Box 1 -", "1") is None
    assert extract_amount_from_matching_line("Net loss: -", r"net\s+loss") is None
    assert extract_amount_from_matching_line("-", r"-") is None


def test_empty_and_no_match_return_none():
    assert find_box_amount("", "1") is None
    assert extract_amount_from_matching_line("", r"interest") is None
    assert extract_amount_from_matching_line("nothing here", r"interest") is None


def test_unbalanced_paren_not_negated():
    # PINNED RULE: an unbalanced "(" does NOT negate; the magnitude is read positive.
    assert find_box_amount("Box 1 (1,000.00", "1") == 1000.0
    assert (
        extract_amount_from_matching_line("Amount: (1,000.00", r"amount") == 1000.0
    )


def test_large_parenthesised_amount():
    assert find_box_amount("Box 1 (1,234,567.89)", "1") == -1234567.89
    assert (
        extract_amount_from_matching_line("Amount: (1,234,567.89)", r"amount")
        == -1234567.89
    )


def test_trailing_minus_not_negated():
    # PINNED RULE: a TRAILING minus (e.g. "1,000.00-") is NOT treated as negative.
    assert find_box_amount("Box 1 1,000.00-", "1") == 1000.0
    assert (
        extract_amount_from_matching_line("Amount: 1,000.00-", r"amount") == 1000.0
    )


# --- §199A digit-collision guard must survive (regression) ------------------

def test_199a_digit_collision_still_protected():
    assert find_box_amount("Box 5 Section 199A dividends 4000.00", "5") == 4000.0
    assert find_box_amount("Box 5 Section 199A dividends -4000.00", "5") == -4000.0


# --- MONEY-PATH REGRESSION: sign reaches the computed field -----------------

def test_i8949_extract_preserves_loss_sign():
    text = "Form 8949\nTotal gain/loss: (1,500.00)\n"
    extract = Form8949Extractor().extract(text)
    assert extract.fields["gain_loss"] == -1500.0


def test_sch_d_extract_preserves_loss_sign():
    text = "Schedule D\nNet short-term capital gain -2,000.00\n"
    extract = ScheduleDExtractor().extract(text)
    assert extract.fields["net_short_term_capital_gain"] == -2000.0


# --- LABEL-SEPARATOR REGRESSIONS (Fable-5 audit, PR #185 refinement) ---------
# The original `_gap` excluded "-" and "(" wholesale, so a dash used as a
# label separator or a parenthetical annotation between the box marker and its
# amount silently KILLED the field (returned None → income vanished with
# confidence="high"). The refined `_gap` treats a "-"/"(" that does NOT
# introduce a number as a gap character, so the amount is still captured.

def test_dash_label_separator_not_swallowed():
    # "Box N - Label amount" is a common broker/CRA rendering. The dash before
    # a WORD is a separator, not a sign — the amount must survive.
    assert find_box_amount("Box 14 - Employment income 84,500.00", "14") == 84500.0


def test_parenthetical_annotation_not_swallowed():
    # "(see note)" between label and amount is an annotation, not an accounting
    # negative — the trailing amount must survive.
    assert find_box_amount("Box 22 (see note) 19,250.00", "22") == 19250.0


def test_dash_separator_before_signed_amount_still_reads_sign():
    # A dash separator followed by a genuinely negative amount must still parse
    # negative (the "-" that DOES introduce the number is the sign).
    assert find_box_amount("Box 14 - Adjustment -1,000.00", "14") == -1000.0
    # And a parenthetical annotation before a genuine accounting-negative:
    assert find_box_amount("Box 3 (adj) (2,500.00)", "3") == -2500.0


def test_dash_before_bare_number_is_documented_negative():
    # DOCUMENTED IRREDUCIBLE CHOICE: "Box 1 - 5,000.00" (dash directly before a
    # bare number, no intervening word) is indistinguishable from a real minus
    # sign without layout information, so it parses as -5000.0. Pinned so any
    # future change to this behaviour is a deliberate, reviewed decision.
    assert find_box_amount("Box 1 - 5,000.00", "1") == -5000.0


def test_midline_trailing_minus_last_match_is_documented():
    # DOCUMENTED IRREDUCIBLE CHOICE: extract_amount_from_matching_line uses
    # last-match (`matches[-1]`) semantics, so a mid-line "- N" subtraction such
    # as "Adjustment: 500 - 200 fee" reads the LAST number (" - 200") and its
    # leading minus → -200.0. There is no clean regex fix (the sign-aware number
    # regex legitimately captures the "-"), so the minimum bar per the audit is
    # to PIN the behaviour, not silently ship a surprise. find_box_amount (which
    # anchors on a box label) is unaffected by this line-level heuristic.
    assert (
        extract_amount_from_matching_line("Adjustment: 500 - 200 fee", r"adjustment")
        == -200.0
    )
