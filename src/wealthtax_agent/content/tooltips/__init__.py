"""File-based tooltip loader for the intake wizard.

Tooltips live as H2 sections inside per-jurisdiction markdown files in this
directory (``ca.md``, ``us.md``, ``in.md``). There is no LLM call, no network
IO, and no environment variable required — the wizard MUST render even when no
provider keys are configured.

Public API:

    load_tooltip(jurisdiction, field_key) -> str
        Returns the trimmed body text for ``## field_key`` in the
        jurisdiction's markdown file. Raises ``KeyError`` if either the file
        or the field section is missing.

    available_tooltips(jurisdiction) -> list[str]
        Lists field_keys available for a jurisdiction (useful for tests and
        the wizard's hint discovery).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

# Map external jurisdiction codes ("CA", "US", "IN") to the on-disk file stem.
_JURISDICTION_FILES = {
    "CA": "ca.md",
    "US": "us.md",
    "IN": "in.md",
}

_TOOLTIPS_DIR = Path(__file__).resolve().parent

# Capture every H2 ("## key") and the text that follows up to the next H2
# (or end-of-file). Keys are lowercase, may include underscores or hyphens.
_SECTION_RE = re.compile(
    r"^##\s+(?P<key>[a-z0-9][a-z0-9_\-]*)\s*\n(?P<body>.*?)(?=^##\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _normalise_jurisdiction(jurisdiction: str) -> str:
    code = (jurisdiction or "").strip().upper()
    if code not in _JURISDICTION_FILES:
        raise KeyError(
            f"Unknown jurisdiction '{jurisdiction}'. Expected one of {sorted(_JURISDICTION_FILES)}."
        )
    return code


@lru_cache(maxsize=8)
def _parse_jurisdiction_file(code: str) -> Dict[str, str]:
    """Parse the markdown file for ``code`` into a {field_key: body} dict.

    Cached because the wizard re-renders on every step click and the file
    contents never change at runtime.
    """
    path = _TOOLTIPS_DIR / _JURISDICTION_FILES[code]
    if not path.exists():
        raise KeyError(f"Tooltip file missing: {path}")
    text = path.read_text(encoding="utf-8")
    sections: Dict[str, str] = {}
    for match in _SECTION_RE.finditer(text):
        key = match.group("key").lower()
        body = match.group("body").strip()
        if body:
            sections[key] = body
    return sections


def load_tooltip(jurisdiction: str, field_key: str) -> str:
    """Return the tooltip body for ``field_key`` in ``jurisdiction``.

    ``jurisdiction`` may be uppercase or lowercase. ``field_key`` is matched
    case-insensitively. Raises ``KeyError`` when either the jurisdiction or
    the key is unknown so callers fail loudly — the wizard should not render
    an empty popover.
    """
    code = _normalise_jurisdiction(jurisdiction)
    sections = _parse_jurisdiction_file(code)
    key = (field_key or "").strip().lower()
    if key not in sections:
        raise KeyError(
            f"No tooltip for '{field_key}' in jurisdiction {code}. "
            f"Available: {sorted(sections)[:5]}{'...' if len(sections) > 5 else ''}"
        )
    return sections[key]


def available_tooltips(jurisdiction: str) -> List[str]:
    """Return the sorted list of field_keys defined for ``jurisdiction``."""
    code = _normalise_jurisdiction(jurisdiction)
    return sorted(_parse_jurisdiction_file(code))


def clear_cache() -> None:
    """Drop the parsed-file cache. Useful in tests that mutate the markdown."""
    _parse_jurisdiction_file.cache_clear()


__all__ = ["load_tooltip", "available_tooltips", "clear_cache"]
