"""Base interface for form extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from wealthtax_agent.state import FormExtract, Jurisdiction


class FormExtractor(ABC):
    """One implementation per supported tax form."""

    #: Two-letter jurisdiction code, e.g. ``"CA"``, ``"US"``.
    jurisdiction: Jurisdiction = "CA"
    #: Short code uniquely identifying the form, e.g. ``"T4"``, ``"W-2"``.
    form_code: str = ""
    #: Patterns we look for in raw OCR text to assign this form code.
    classification_patterns: tuple = ()

    def classify(self, text: str) -> Optional[float]:
        """Return a match score if this looks like the form, else None.

        The score is the length of the longest matching pattern. Longer matches
        are more specific, so when several extractors fire on the same text
        the registry picks the one whose matched pattern is longest (e.g.
        ``1098-E`` wins over ``1098`` for a 1098-E document).
        """
        lowered = text.lower()
        best = None
        for pattern in self.classification_patterns:
            if pattern.lower() in lowered:
                score = len(pattern)
                if best is None or score > best:
                    best = score
        return float(best) if best is not None else None

    @abstractmethod
    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        """Pull structured fields from OCR text."""
        ...
