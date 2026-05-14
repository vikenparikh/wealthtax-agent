"""Shared regex/text helpers used by extractors."""

from __future__ import annotations

import re
from typing import Optional


_NUMBER_RE = r"[0-9][0-9,]*(?:\.[0-9]+)?"


def extract_amount_from_matching_line(text: str, keyword_pattern: str) -> Optional[float]:
    for line in text.split("\n"):
        if not re.search(keyword_pattern, line, flags=re.IGNORECASE):
            continue
        matches = re.findall(_NUMBER_RE, line)
        if not matches:
            continue
        try:
            return float(matches[-1].replace(",", ""))
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
    patterns = [
        rf"box\s*{re.escape(box_label)}\b[^0-9]*({_NUMBER_RE})",
        rf"\b{re.escape(box_label)}\b[^0-9]*({_NUMBER_RE})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
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
