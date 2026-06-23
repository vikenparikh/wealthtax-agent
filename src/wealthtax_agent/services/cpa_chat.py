"""LLM CPA chat service (C5).

``ask()`` is the single entry point.  It builds a context-enriched prompt
from a ``TaxYearContext`` (slips, draft return totals, active jurisdictions),
calls the ClaudeCLILLM, and returns a structured ``Answer``.

LEGAL DISCLAIMER
----------------
This service does NOT provide professional tax advice and is NOT a substitute
for a licensed CPA.  Every ``Answer`` includes a ``disclaimer`` field that
MUST be surfaced to the user.  The LLM never files a return and never claims
to be a licensed professional.

Citations
---------
The LLM is instructed to cite:
  - IRS Publications (e.g. Pub 550, Pub 334, Pub 17)
  - CRA Guides (e.g. T4015, RC4111)
  - IRC/ITA section numbers
The ``citations`` list in ``Answer`` is parsed from the response.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from wealthtax_agent.llm import sanitize_runtime_error

log = logging.getLogger(__name__)

_DISCLAIMER = (
    "DISCLAIMER: This is an AI-generated response for informational purposes only. "
    "It is NOT professional tax advice and does NOT constitute legal or accounting advice. "
    "You should consult a licensed CPA or tax attorney before taking any action. "
    "This tool does not file returns on your behalf."
)

_SYSTEM_CONTEXT = """\
You are a tax research assistant with expertise in US federal taxes (IRC), Canadian taxes (ITA/CRA guides), and cross-border issues.

Rules you must follow:
1. Always include a disclaimer that you are not a licensed professional.
2. Cite specific IRS Publications, CRA Guides, or IRC/ITA section numbers when relevant.
3. Never claim to file a return or take action on behalf of the user.
4. If you are uncertain, say so explicitly and recommend professional consultation.
5. Keep answers factual, clear, and concise (under 400 words unless the question requires more detail).
"""


@dataclass
class TaxYearContext:
    """Snapshot of a user's tax year data passed to the CPA chat."""

    tax_year: int
    jurisdictions: List[str] = field(default_factory=list)  # ["US", "CA"]
    draft_totals: Dict[str, float] = field(default_factory=dict)
    form_types_present: List[str] = field(default_factory=list)
    # Free-form notes (e.g. "has wash sales", "QQQ day trader")
    notes: List[str] = field(default_factory=list)

    def to_context_string(self) -> str:
        lines = [
            f"Tax Year: {self.tax_year}",
            f"Jurisdictions: {', '.join(self.jurisdictions) or 'not specified'}",
            f"Forms present: {', '.join(self.form_types_present) or 'none'}",
        ]
        if self.draft_totals:
            lines.append("Draft return totals:")
            for k, v in self.draft_totals.items():
                lines.append(f"  {k}: ${v:,.2f}")
        if self.notes:
            lines.append("Additional context: " + "; ".join(self.notes))
        return "\n".join(lines)


@dataclass
class Answer:
    question: str
    answer_text: str
    citations: List[str] = field(default_factory=list)
    disclaimer: str = _DISCLAIMER
    confidence: str = "medium"   # "low" | "medium" | "high"
    model_used: str = "claude-sonnet-4-6"
    raw_response: Optional[str] = None


def _parse_citations(text: str) -> List[str]:
    """Extract IRS Pub / CRA / IRC / ITA references from text."""
    patterns = [
        r"(?:IRS\s+)?(?:Publication|Pub\.?)\s+\d+",
        r"IRC\s+[§Ss]ection\s+\d+\w*",
        r"IRC\s+§\s*\d+\w*",
        r"§\s*\d{3,4}\w*",
        r"CRA\s+[A-Z]\d{4,5}",
        r"(?:Income\s+Tax\s+Folio\s+S\d+-[CF]\d+-[A-Z]\d+)",
        r"(?:T\d{1,4}(?:RSP|RIF|[A-Z]{0,4})?\s+Guide)",
        r"Form\s+\d{4}(?:-[A-Z]+)?",
    ]
    found: list = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            cit = m.group(0).strip()
            if cit not in found:
                found.append(cit)
    return found


def ask(
    question: str,
    context: TaxYearContext,
    llm: Any = None,  # ClaudeCLILLM | StubLLM — injected for tests
) -> Answer:
    """Ask the LLM CPA assistant a tax question.

    Parameters
    ----------
    question:
        The user's tax question (free-form text).
    context:
        Snapshot of the user's current tax year data — anchors the LLM.
    llm:
        Optional LLM instance (defaults to singleton ClaudeCLILLM).
        Pass a ``StubLLM`` in tests.

    Returns
    -------
    Answer
        Structured answer with ``answer_text``, ``citations``, and
        mandatory ``disclaimer``.
    """
    if llm is None:
        try:
            from wealthtax_agent.services.claude_llm import get_tax_llm
            llm = get_tax_llm()
        except RuntimeError as exc:
            # Graceful degradation: return a stub answer if claude is not available
            log.warning("ClaudeCLILLM unavailable: %s — returning offline stub", exc)
            return Answer(
                question=question,
                answer_text=(
                    "The tax assistant is currently unavailable (claude CLI not found). "
                    "Please consult a licensed CPA."
                ),
                disclaimer=_DISCLAIMER,
                confidence="low",
            )

    context_str = context.to_context_string()
    prompt = (
        f"{_SYSTEM_CONTEXT}\n\n"
        f"--- USER'S TAX CONTEXT ---\n{context_str}\n\n"
        f"--- QUESTION ---\n{question}\n\n"
        "Please answer the question above, citing relevant IRS publications, "
        "CRA guides, or IRC/ITA sections. Include the standard disclaimer at the end."
    )

    try:
        resp = llm.complete(prompt)
        raw = resp.text
    except Exception as exc:
        log.error("CPA chat LLM call failed: %s", exc)
        safe = sanitize_runtime_error(str(exc))
        return Answer(
            question=question,
            answer_text=f"Unable to process your question due to an error: {safe}",
            disclaimer=_DISCLAIMER,
            confidence="low",
            raw_response=safe,
        )

    citations = _parse_citations(raw)
    # Ensure disclaimer is appended if the model didn't include it
    if "disclaimer" not in raw.lower() and "not a licensed" not in raw.lower():
        raw = raw + "\n\n" + _DISCLAIMER

    return Answer(
        question=question,
        answer_text=raw,
        citations=citations,
        disclaimer=_DISCLAIMER,
        confidence="medium",
        model_used=getattr(llm, "_model", "stub"),
        raw_response=raw,
    )
