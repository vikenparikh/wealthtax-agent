import streamlit as st
from pydantic import ValidationError

from wealthtax_agent.graph import build_graph
from wealthtax_agent.llm import sanitize_runtime_error
from wealthtax_agent.state import GraphState, InputDocument
import os


MAX_FILES = int(os.getenv("MAX_UPLOAD_FILES", "20"))
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
APPROVAL_CHECK_KEYS = (
	"approve_check_slips",
	"approve_check_explanations",
	"approve_check_responsibility",
)


def _validate_uploads(uploaded_files) -> list[str]:
	warnings = []
	if uploaded_files and len(uploaded_files) > MAX_FILES:
		warnings.append(f"Please upload at most {MAX_FILES} files.")

	for file in uploaded_files or []:
		if file.size > MAX_FILE_SIZE_BYTES:
			warnings.append(f"File '{file.name}' exceeds 5MB size limit.")
	return warnings


def _format_bytes(size: int) -> str:
	units = ["B", "KB", "MB", "GB"]
	size_float = float(size)
	for unit in units:
		if size_float < 1024 or unit == units[-1]:
			return f"{size_float:.1f} {unit}"
		size_float /= 1024
	return f"{size} B"


def _sanitize_error_message(message: str) -> str:
	return sanitize_runtime_error(message)


def _approval_ready(values: list[bool]) -> bool:
	return all(values)


def _reset_approval_checks() -> None:
	for key in APPROVAL_CHECK_KEYS:
		st.session_state[key] = False


def _coerce_graph_state(raw_state) -> GraphState:
	return GraphState.model_validate(raw_state)


def _step_label(done: bool, text: str) -> str:
	return f"✅ {text}" if done else f"⏳ {text}"


def _build_review_report(state: GraphState, reviewer_name: str) -> str:
	draft = state.draft_return
	if draft is None:
		return "No draft return available."

	reviewer = reviewer_name.strip() or "Not provided"
	warnings = state.warnings or []
	warning_block = "\n".join(f"- {warning}" for warning in warnings) or "- None"

	return (
		"WealthTax Agent Review Report\n"
		"=============================\n"
		f"Reviewer: {reviewer}\n"
		f"LLM provider: {state.llm_provider or 'unknown'}\n"
		f"Parsed slips: {len(state.slips)}\n"
		f"Human approved: {'Yes' if state.human_approved else 'No'}\n\n"
		"Draft Summary\n"
		"-------------\n"
		f"Total income: {draft.total_income:,.2f}\n"
		f"RRSP deduction: {draft.rrsp_deduction:,.2f}\n"
		f"Taxable income: {draft.taxable_income:,.2f}\n"
		f"Estimated tax: {draft.estimated_tax:,.2f}\n\n"
		"Warnings\n"
		"--------\n"
		f"{warning_block}\n"
	)


def run_app() -> None:
	graph = build_graph()

	st.set_page_config(page_title="WealthTax Agent", page_icon="💸")

	st.title("WealthTax Agent – Canadian Tax Draft Assistant")
	st.write(
		"Upload your Canadian tax slips (T4/T5/RRSP). "
		"The system drafts a return summary and explains each key number. "
		"You remain responsible for reviewing and deciding whether to use it."
	)

	st.subheader("Trust & Responsibility")
	st.markdown(
		"- **System assists with:** parsing slips, drafting totals, and plain-English explanations\n"
		"- **Human decides:** whether the draft is accurate and safe to use\n"
		"- **Never automated:** legal/tax advice and CRA filing"
	)

	with st.expander("Why human approval is required", expanded=False):
		st.markdown(
			"**Critical human-only decision:** whether to approve and use this draft for filing actions. "
			"This stays human because filing carries legal and financial responsibility."
		)
	st.caption("Workflow: Upload slips → Generate draft → Review warnings and totals → Approve if accurate")

	state = st.session_state.last_state if "last_state" in st.session_state else None
	step_upload_done = False
	step_draft_done = bool(state and state.draft_return)
	step_approved_done = bool(state and state.human_approved)

	st.subheader("1) Upload slips")
	reviewer_name = st.text_input("Reviewer name (optional)", placeholder="e.g., Alex Chen")
	uploaded_files = st.file_uploader(
		"Upload slips (PDF/images)",
		type=["pdf", "png", "jpg", "jpeg"],
		accept_multiple_files=True,
	)

	step_upload_done = bool(uploaded_files)
	status_cols = st.columns(3)
	status_cols[0].caption(_step_label(step_upload_done, "Upload slips"))
	status_cols[1].caption(_step_label(step_draft_done, "Generate draft"))
	status_cols[2].caption(_step_label(step_approved_done, "Human approval"))

	if st.button("Clear current draft"):
		st.session_state.last_state = None
		_reset_approval_checks()
		st.rerun()

	if uploaded_files:
		st.caption(f"Selected {len(uploaded_files)} file(s).")
		with st.expander("Selected files", expanded=False):
			for uploaded_file in uploaded_files:
				st.markdown(f"- {uploaded_file.name} ({_format_bytes(uploaded_file.size)})")
	else:
		st.caption("No files uploaded yet.")

	if "last_state" not in st.session_state:
		st.session_state.last_state = None

	validation_warnings = _validate_uploads(uploaded_files)
	for warning in validation_warnings:
		st.warning(warning)

	with st.expander("Pre-run validation", expanded=not bool(uploaded_files)):
		has_files = bool(uploaded_files)
		within_file_limit = not (uploaded_files and len(uploaded_files) > MAX_FILES)
		within_size_limit = not any(file.size > MAX_FILE_SIZE_BYTES for file in (uploaded_files or []))
		st.markdown(f"- {_step_label(has_files, 'At least one file uploaded')}")
		st.markdown(f"- {_step_label(within_file_limit, f'No more than {MAX_FILES} files')}")
		st.markdown(f"- {_step_label(within_size_limit, 'Each file is 5MB or less')}")
		st.caption("Results appear in section 2 below after generation.")

	generate_disabled = (not uploaded_files) or bool(validation_warnings)

	if st.button("Generate draft return", disabled=generate_disabled):
		if not uploaded_files:
			st.error("Please upload at least one slip before generating a draft.")
		elif validation_warnings:
			st.error("Resolve upload warnings before generating a draft.")
		else:
			with st.spinner("Parsing slips and generating your draft..."):
				try:
					raw_docs = [
						InputDocument(content=f.read(), filename=f.name, mime_type=getattr(f, "type", None))
						for f in uploaded_files
					]
					initial_state = GraphState(raw_docs=raw_docs)
					final_state = _coerce_graph_state(graph.invoke(initial_state))
					st.session_state.last_state = final_state
					_reset_approval_checks()
					st.success("Draft generated. Review details below.")
				except (ValidationError, TypeError, ValueError, RuntimeError) as exc:
					message = _sanitize_error_message(str(exc))
					st.session_state.last_state = GraphState(
						raw_docs=[],
						warnings=[f"Draft generation failed: {message}"],
					)
					_reset_approval_checks()
					st.error("Draft generation failed. Review the warning details and try again.")

	state = st.session_state.last_state

	if state and state.llm_provider:
		st.caption(f"LLM provider: {state.llm_provider}")

	if state and state.warnings:
		st.subheader("Review flags")
		for warning in state.warnings:
			st.warning(warning)

	if state and state.draft_return:
		st.subheader("2) Draft Return Summary (Simplified)")
		st.caption("Check these values against your source slips before approving.")
		draft_return = state.draft_return
		col1, col2 = st.columns(2)
		with col1:
			st.metric("Total income", f"${draft_return.total_income:,.2f}")
			st.metric("Taxable income", f"${draft_return.taxable_income:,.2f}")
		with col2:
			st.metric("RRSP deduction", f"${draft_return.rrsp_deduction:,.2f}")
			st.metric("Estimated tax", f"${draft_return.estimated_tax:,.2f}")

		result_tab_summary, result_tab_slips, result_tab_data = st.tabs(["Explanations", "Parsed slips", "Draft data"])

		with result_tab_summary:
			if state.explanation:
				for key, text in state.explanation.lines.items():
					st.markdown(f"**{key}**: {text}")
			else:
				st.info("No explanation text was generated. Review numeric values carefully.")

		with result_tab_slips:
			if state.slips:
				for index, slip in enumerate(state.slips, start=1):
					with st.expander(f"Slip {index}: {slip.type}", expanded=False):
						if slip.fields:
							for field_name, field_value in slip.fields.items():
								st.markdown(f"- **{field_name}**: {field_value:,.2f}")
						else:
							st.caption("No numeric fields extracted.")
			else:
				st.caption("No parsed slips available.")

		with result_tab_data:
			payload = state.draft_return.model_dump_json(indent=2)
			report = _build_review_report(state, reviewer_name)
			summary_text = state.draft_summary_text or ""
			pseudo_xml = state.draft_pseudo_xml or ""
			st.code(payload, language="json")
			download_col1, download_col2 = st.columns(2)
			with download_col1:
				st.download_button(
					"Download draft JSON",
					data=payload,
					file_name="wealthtax_draft_return.json",
					mime="application/json",
				)
			with download_col2:
				st.download_button(
					"Download review report (TXT)",
					data=report,
					file_name="wealthtax_review_report.txt",
					mime="text/plain",
				)

			download_col3, download_col4 = st.columns(2)
			with download_col3:
				st.download_button(
					"Download draft summary (TXT)",
					data=summary_text,
					file_name="wealthtax_draft_summary.txt",
					mime="text/plain",
					disabled=not bool(summary_text),
				)
			with download_col4:
				st.download_button(
					"Download pseudo-XML (XML)",
					data=pseudo_xml,
					file_name="wealthtax_draft_return.xml",
					mime="application/xml",
					disabled=not bool(pseudo_xml),
				)

		st.markdown("---")
		st.subheader("3) Human decision")
		st.caption("This is the explicit control boundary: the system can draft, but only you can approve use.")
		st.markdown(
			"Only approve when totals match your slips and you are comfortable taking responsibility for filing decisions."
		)

		check_slips = st.checkbox(
			"I verified all summary totals against my source slips.",
			key="approve_check_slips",
		)
		check_explanations = st.checkbox(
			"I reviewed the explanations and warning flags.",
			key="approve_check_explanations",
		)
		check_responsibility = st.checkbox(
			"I understand this tool does not file with CRA and I remain responsible.",
			key="approve_check_responsibility",
		)
		can_approve = _approval_ready([check_slips, check_explanations, check_responsibility])

		if not state.human_approved:
			if st.button("Approve this draft (I take responsibility)", disabled=not can_approve):
				state.human_approved = True
				st.session_state.last_state = state
				st.rerun()
			if not can_approve:
				st.caption("Complete all review checks to enable approval.")
		else:
			st.success(
				"You approved this draft. The system will NOT file with CRA; "
				"you must do that yourself if you choose to use it."
			)
			with st.expander("What to do next", expanded=True):
				st.markdown("1. Compare all fields against your slips and prior records.")
				st.markdown("2. Resolve warnings or missing values before filing.")
				st.markdown("3. Use your filing software/portal to submit manually.")
	else:
		st.info("Upload slips and click 'Generate draft return'. Your results will appear in section 2 with downloadable outputs.")


def main() -> None:
	run_app()


if __name__ == "__main__":
	main()
