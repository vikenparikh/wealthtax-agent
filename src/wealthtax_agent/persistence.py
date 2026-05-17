"""Save and load ``GraphState`` to/from JSON files.

Lets the user keep a year's draft + answers around between sessions, and
provides multi-year history for the projection module.

Bytes (``raw_docs[].content``) are dropped on save to keep the file small and
to avoid persisting raw PDFs to disk. The structured ``extracts`` already
capture everything the engines need.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from wealthtax_agent.state import GraphState


_DEFAULT_ROOT = Path.home() / ".wealthtax"


def _state_dict_without_bytes(state: GraphState) -> Dict[str, Any]:
    data = state.model_dump(mode="json")
    # Drop raw byte blobs to keep file small + portable. ``content`` is
    # required on ``InputDocument`` so we substitute an empty placeholder
    # rather than removing the field.
    cleaned = []
    for doc in data.get("raw_docs", []):
        if isinstance(doc, dict):
            cleaned.append({**doc, "content": ""})
    data["raw_docs"] = cleaned
    return data


def save_state(state: GraphState, root: Path | None = None) -> Path:
    """Write a snapshot named ``{filing_year}.json`` under the storage root.

    Returns the path written. Creates the root directory if missing.
    """
    root = root or _DEFAULT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    year = state.filing_year or 0
    out = root / f"{year}.json"
    out.write_text(json.dumps(_state_dict_without_bytes(state), indent=2), encoding="utf-8")
    return out


def load_state(year: int, root: Path | None = None) -> GraphState:
    """Reconstruct a ``GraphState`` previously written by ``save_state``."""
    root = root or _DEFAULT_ROOT
    path = root / f"{year}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return GraphState.model_validate(data)


def list_saved_years(root: Path | None = None) -> List[int]:
    root = root or _DEFAULT_ROOT
    if not root.exists():
        return []
    years = []
    for p in root.iterdir():
        if p.suffix == ".json":
            try:
                years.append(int(p.stem))
            except ValueError:
                continue
    return sorted(years)


def load_all_prior_returns(latest_year: int, root: Path | None = None) -> Dict[int, GraphState]:
    """Load every saved year strictly before ``latest_year``."""
    out: Dict[int, GraphState] = {}
    for y in list_saved_years(root):
        if y < latest_year:
            try:
                out[y] = load_state(y, root)
            except Exception:
                continue
    return out
