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
        """Return a confidence in [0, 1] if this looks like the form, else None."""
        lowered = text.lower()
        for pattern in self.classification_patterns:
            if pattern.lower() in lowered:
                return 0.9
        return None

    @abstractmethod
    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        """Pull structured fields from OCR text."""
        ...
