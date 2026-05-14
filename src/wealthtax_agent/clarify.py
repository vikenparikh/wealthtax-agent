"""Generate clarifying questions and pause the graph until the user answers.

Question templates live in ``config/clarifying_questions/<jurisdiction>.yaml``.
For each unanswered high-priority question we surface a ``ClarifyingQuestion``;
the graph router pauses on ``awaiting_clarification = True`` and re-enters
``reason_tax`` once the UI populates ``state.user_answers``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from wealthtax_agent.state import ClarifyingQuestion, GraphState, Jurisdiction


_QUESTIONS_ROOT = Path(__file__).resolve().parent / "config" / "clarifying_questions"


def _load_questions(jurisdiction: Jurisdiction) -> List[Dict]:
    path = _QUESTIONS_ROOT / f"{jurisdiction.lower()}.yaml"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return list(data.get("questions", []))


def _is_answered(question_id: str, answers: Dict[str, str]) -> bool:
    raw = answers.get(question_id)
    if raw is None:
        return False
    return str(raw).strip() != ""


def ask_clarifications_node(state: GraphState) -> GraphState:
    jurisdictions = state.jurisdictions or []
    answers = state.user_answers or {}

    pending: List[ClarifyingQuestion] = []
    high_priority_pending = False

    for jurisdiction in jurisdictions:
        for q in _load_questions(jurisdiction):
            qid = str(q.get("id", "")).strip()
            if not qid or _is_answered(qid, answers):
                continue
            priority = str(q.get("priority", "medium")).lower()
            pending.append(ClarifyingQuestion(
                id=qid,
                jurisdiction=jurisdiction,
                prompt=str(q.get("prompt", "")),
                why_it_matters=str(q.get("why_it_matters", "")),
                answer_type=str(q.get("answer_type", "text")),  # type: ignore[arg-type]
                options=list(q.get("options", []) or []),
                priority=priority,  # type: ignore[arg-type]
            ))
            if priority == "high":
                high_priority_pending = True

    state.clarifying_questions = pending
    state.awaiting_clarification = high_priority_pending and not bool(answers)
    return state


def has_outstanding_clarifications(state: GraphState) -> bool:
    return state.awaiting_clarification
