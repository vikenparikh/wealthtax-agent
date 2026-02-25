from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field


class InputDocument(BaseModel):
	content: bytes
	filename: Optional[str] = None
	mime_type: Optional[str] = None


class Slip(BaseModel):
	type: str
	fields: Dict[str, float]


class DraftReturn(BaseModel):
	total_income: float = 0.0
	rrsp_deduction: float = 0.0
	taxable_income: float = 0.0
	estimated_tax: float = 0.0
	estimated_refund: float = 0.0


class Explanation(BaseModel):
	lines: Dict[str, str] = Field(default_factory=dict)


class GraphState(BaseModel):
	raw_docs: List[Union[InputDocument, bytes]] = Field(default_factory=list)
	slips: List[Slip] = Field(default_factory=list)
	draft_return: Optional[DraftReturn] = None
	explanation: Optional[Explanation] = None
	draft_summary_text: Optional[str] = None
	draft_pseudo_xml: Optional[str] = None
	human_approved: bool = False
	warnings: List[str] = Field(default_factory=list)
	llm_provider: Optional[str] = None
