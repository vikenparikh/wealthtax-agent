"""Registry of available form extractors."""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from wealthtax_agent.forms.base import FormExtractor


_REGISTRY: Dict[str, FormExtractor] = {}


def register(extractor_cls: Type[FormExtractor]) -> Type[FormExtractor]:
    """Decorator / function: register an extractor under its ``form_code``."""
    instance = extractor_cls()
    key = instance.form_code.upper()
    if not key:
        raise ValueError(f"Extractor {extractor_cls.__name__} has no form_code")
    _REGISTRY[key] = instance
    return extractor_cls


def get(form_code: str) -> Optional[FormExtractor]:
    return _REGISTRY.get(form_code.upper())


def supported_form_codes(jurisdiction: Optional[str] = None) -> List[str]:
    if jurisdiction is None:
        return sorted(_REGISTRY.keys())
    j = jurisdiction.upper()
    return sorted(code for code, ext in _REGISTRY.items() if ext.jurisdiction == j)


def all_extractors() -> List[FormExtractor]:
    return list(_REGISTRY.values())
