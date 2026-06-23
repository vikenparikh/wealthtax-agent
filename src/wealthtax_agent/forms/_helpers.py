"""Shared regex/text helpers used by extractors."""

from __future__ import annotations

import re
from typing import Optional


_NUMBER_RE = r"[0-9][0-9,]*(?:\.[0-9]+)?"

# Sign-aware magnitude: an optional leading "(" (accounting), "-" (minus) and/or
# "$" (currency) before the digits, plus an optional trailing ")" to close a
# balanced accounting-negative. This is the SINGLE sign source for the engines —
# a loss MUST parse negative or it inflates taxable gains and hides wash sales.
#
# ASSUMPTION (input-format dependent): a leading "-" or "(...)" before a
# number is read as a SIGN, never as a label/value SEPARATOR. This holds for
# every slip format in this codebase (labels are space/colon-separated; the
# only dash-before-number fixture line is a share-count in a 1099-B
# description, which the box search never reaches). If a future input format
# uses a literal " - " to separate a label from a positive amount, this
# parser MUST be updated or that amount will be silently flipped to a loss.
_NUMBER_SIGNED_RE = r"\(?\s*\$?\s*-?\s*\$?\s*" + _NUMBER_RE + r"\)?"


def _to_float(token: str) -> float:
    """Parse a signed money token. Maps a BALANCED ``(...)`` OR a leading ``-`` to
    negation; strips ``$``, commas and whitespace. Unbalanced parens are NOT
    treated as negative (the lone paren is dropped, magnitude stays positive).
    """
    token = token.strip()
    negative = False
    # Accounting parentheses negate only when balanced.
    if token.startswith("(") and token.endswith(")"):
        negative = True
        token = token[1:-1]
    else:
        # Drop an unbalanced paren without negating.
        token = token.strip("()")
    # Strip currency/whitespace from either side of an optional leading minus so
    # both "-$1,000" and "$-1,000" are recognised.
    token = token.strip().lstrip("$").strip()
    if token.startswith("-"):
        negative = True
        token = token[1:]
    token = token.strip().lstrip("$").strip().replace(",", "")
    value = float(token)
    return -value if negative else value


def extract_amount_from_matching_line(text: str, keyword_pattern: str) -> Optional[float]:
    for line in text.split("\n"):
        if not re.search(keyword_pattern, line, flags=re.IGNORECASE):
            continue
        matches = re.findall(_NUMBER_SIGNED_RE, line)
        if not matches:
            continue
        try:
            return _to_float(matches[-1])
        except ValueError:
            continue
    return None


def extract_amount(text: str, pattern: str) -> Optional[float]:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except (TypeError, ValueError):
        return None


def find_box_amount(text: str, box_label: str) -> Optional[float]:
    """Look for 'Box <label>' or '<label>:' style markers and return the
    nearest number on the same line.
    """
    # Between the box marker and its amount, skip not only non-digits but also
    # digit-runs that are part of a WORD (e.g. the "199" in a "Section 199A
    # dividends" label) — otherwise the amount capture stops on those label
    # digits and returns a stub (199) instead of the real money figure.
    # The gap must NOT swallow a sign/currency marker that belongs to the amount,
    # so "(", "-" and "$" are excluded from the non-digit class.
    _gap = r"(?:[^0-9(\-$]|[0-9]+[A-Za-z])*"
    patterns = [
        rf"box\s*{re.escape(box_label)}\b{_gap}({_NUMBER_SIGNED_RE})",
        rf"\b{re.escape(box_label)}\b{_gap}({_NUMBER_SIGNED_RE})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return _to_float(match.group(1))
            except ValueError:
                continue
    return None


def detect_tax_year(text: str) -> Optional[int]:
    match = re.search(r"\b(?:tax\s+year|for\s+year|year)\s*[:\-]?\s*((?:19|20)\d{2})\b", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\b((?:19|20)\d{2})\b", text)
    if match:
        return int(match.group(1))
    return None
