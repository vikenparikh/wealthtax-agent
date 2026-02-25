from wealthtax_agent.state import DraftReturn, GraphState


def reason_tax_node(state: GraphState) -> GraphState:
	total_income = 0.0
	rrsp_contribs = 0.0

	for slip in state.slips:
		fields = slip.fields
		if slip.type == "T4":
			total_income += fields.get("employment_income", 0.0)
		if slip.type == "T5":
			total_income += fields.get("interest_income", 0.0)
			total_income += fields.get("dividends", 0.0)
		if slip.type == "RRSP":
			rrsp_contribs += fields.get("rrsp_contributions", 0.0)

	rrsp_deduction = rrsp_contribs
	taxable_income = max(total_income - rrsp_deduction, 0.0)
	estimated_tax = taxable_income * 0.25

	state.draft_return = DraftReturn(
		total_income=total_income,
		rrsp_deduction=rrsp_deduction,
		taxable_income=taxable_income,
		estimated_tax=estimated_tax,
		estimated_refund=0.0,
	)
	return state
