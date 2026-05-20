from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


Jurisdiction = Literal["CA", "US", "IN"]
Confidence = Literal["low", "medium", "high"]
Horizon = Literal["now", "future"]


class InputDocument(BaseModel):
    content: bytes
    filename: Optional[str] = None
    mime_type: Optional[str] = None


class Slip(BaseModel):
    """Legacy slip representation kept for backwards compatibility.

    New code should prefer ``FormExtract``; ``Slip`` is reconstructed from the
    first matching extract so older tests/UI paths keep working.
    """

    type: str
    fields: Dict[str, float]


class FormClassification(BaseModel):
    filename: Optional[str] = None
    jurisdiction: Optional[Jurisdiction] = None
    form_code: Optional[str] = None
    confidence: Confidence = "low"
    reason: Optional[str] = None


class FormExtract(BaseModel):
    form_code: str
    jurisdiction: Jurisdiction
    tax_year: Optional[int] = None
    fields: Dict[str, float] = Field(default_factory=dict)
    text_fields: Dict[str, str] = Field(default_factory=dict)
    source_filename: Optional[str] = None
    extractor: Literal["rule", "llm"] = "rule"
    confidence: Confidence = "medium"


class UnsupportedForm(BaseModel):
    filename: Optional[str] = None
    detected_label: Optional[str] = None
    reason: str
    suggested_next_step: str


class ClarifyingQuestion(BaseModel):
    id: str
    jurisdiction: Optional[Jurisdiction] = None
    prompt: str
    why_it_matters: str
    answer_type: Literal["yes_no", "number", "text", "choice"] = "yes_no"
    options: List[str] = Field(default_factory=list)
    priority: Literal["high", "medium", "low"] = "medium"


class OptimizationSuggestion(BaseModel):
    id: str
    jurisdiction: Jurisdiction
    title: str
    rationale: str
    est_savings: float = 0.0
    horizon: Horizon = "now"
    action_steps: List[str] = Field(default_factory=list)


class FilingArtifact(BaseModel):
    jurisdiction: Jurisdiction
    form_code: str
    filename: str
    mime_type: str
    content_b64: str
    schema_version: str = "0.1"
    transmissible: bool = False
    note: str = "Draft only. Not transmitted to CRA/IRS."


class DraftReturn(BaseModel):
    """Aggregated draft return.

    Old four fields (``total_income``, ``rrsp_deduction``, ``taxable_income``,
    ``estimated_tax``) are kept at the top level for backwards compatibility
    with existing UI/tests. ``totals``, ``line_items``, and ``credits`` carry
    the richer per-jurisdiction breakdown.
    """

    jurisdiction: Optional[Jurisdiction] = None
    tax_year: Optional[int] = None

    total_income: float = 0.0
    rrsp_deduction: float = 0.0
    taxable_income: float = 0.0
    estimated_tax: float = 0.0
    estimated_refund: float = 0.0

    line_items: Dict[str, float] = Field(default_factory=dict)
    totals: Dict[str, float] = Field(default_factory=dict)
    credits: Dict[str, float] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class Explanation(BaseModel):
    lines: Dict[str, str] = Field(default_factory=dict)


class FieldChange(BaseModel):
    """One atomic edit produced by parsing a correction prompt or inline edit."""

    op: Literal["set", "add", "remove"] = "set"
    target: Literal["extract", "user_answer", "form"] = "extract"
    form_code: Optional[str] = None
    jurisdiction: Optional[Jurisdiction] = None
    field: Optional[str] = None  # field name inside the extract or user_answer key
    new_value: Optional[float | str] = None
    old_value: Optional[float | str] = None
    reason: Optional[str] = None
    low_confidence: bool = False


class Correction(BaseModel):
    """A user-initiated edit: chat prompt, inline edit, or add/remove form."""

    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex)
    kind: Literal["chat", "inline_edit", "add_form", "remove_form"] = "chat"
    user_prompt: Optional[str] = None
    changes: List[FieldChange] = Field(default_factory=list)
    low_confidence: bool = False
    applied: bool = False
    reverted: bool = False


class GraphState(BaseModel):
    raw_docs: List[Union[InputDocument, bytes]] = Field(default_factory=list)
    filing_year: Optional[int] = None
    jurisdictions: List[Jurisdiction] = Field(default_factory=list)
    user_answers: Dict[str, str] = Field(default_factory=dict)
    is_amendment: bool = False
    prior_filed_totals: Dict[str, Dict[str, float]] = Field(default_factory=dict)

    classifications: List[FormClassification] = Field(default_factory=list)
    extracts: List[FormExtract] = Field(default_factory=list)
    unsupported_forms: List[UnsupportedForm] = Field(default_factory=list)

    slips: List[Slip] = Field(default_factory=list)
    draft_return: Optional[DraftReturn] = None
    draft_returns: Dict[str, DraftReturn] = Field(default_factory=dict)

    clarifying_questions: List[ClarifyingQuestion] = Field(default_factory=list)
    awaiting_clarification: bool = False
    optimization_suggestions: List[OptimizationSuggestion] = Field(default_factory=list)

    explanation: Optional[Explanation] = None
    draft_summary_text: Optional[str] = None
    draft_pseudo_xml: Optional[str] = None
    filing_artifacts: Dict[str, FilingArtifact] = Field(default_factory=dict)

    human_approved: bool = False
    warnings: List[str] = Field(default_factory=list)
    llm_provider: Optional[str] = None

    # Correction loop state
    corrections: List[Correction] = Field(default_factory=list)
    applied_corrections: List[Correction] = Field(default_factory=list)
    revision_number: int = 0
    correction_diff: Optional[Dict[str, Dict[str, float]]] = None

    # Residency / cross-border state
    residency_days: Dict[str, int] = Field(default_factory=dict)
    residency_status: Dict[str, str] = Field(default_factory=dict)
    residency_notes: List[str] = Field(default_factory=list)
