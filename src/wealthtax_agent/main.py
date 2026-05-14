import base64
import os
from datetime import datetime
from typing import Iterable, List

import streamlit as st
from pydantic import ValidationError

from wealthtax_agent.config.tax_tables import available_years
from wealthtax_agent.graph import build_graph
from wealthtax_agent.llm import sanitize_runtime_error
from wealthtax_agent.state import GraphState, InputDocument


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


def _approval_ready(values: Iterable[bool]) -> bool:
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


def _available_years_combined() -> List[int]:
    years = set(available_years("ca")) | set(available_years("us"))
    if not years:
        return [datetime.now().year - 1]
    return sorted(years)


def _ensure_session_defaults() -> None:
    st.session_state.setdefault("last_state", None)
    st.session_state.setdefault("answers", {})


def _render_unsupported_section(state: GraphState) -> None:
    if not state.unsupported_forms:
        return
    st.subheader("Unsupported forms")
    for item in state.unsupported_forms:
        with st.container():
            st.warning(
                f"**{item.filename or 'document'}** — {item.reason}\n\n"
                f"_Next step:_ {item.suggested_next_step}"
            )


def _render_clarifying_questions(state: GraphState) -> None:
    if not state.clarifying_questions:
        return

    st.subheader("A few questions to sharpen your return")
    st.caption("High-priority items shape eligibility for credits and deductions. Answer what you can; skip the rest.")

    with st.form("clarifying_questions_form", clear_on_submit=False):
        new_answers: dict[str, str] = dict(st.session_state.get("answers", {}))
        for q in state.clarifying_questions:
            label = f"{q.prompt}  \n_{q.why_it_matters}_"
            key = f"answer_{q.id}"
            current = new_answers.get(q.id, "")
            if q.answer_type == "yes_no":
                opts = ["", "yes", "no"]
                index = opts.index(current) if current in opts else 0
                new_answers[q.id] = st.selectbox(label, opts, index=index, key=key)
            elif q.answer_type == "choice" and q.options:
                opts = [""] + list(q.options)
                index = opts.index(current) if current in opts else 0
                new_answers[q.id] = st.selectbox(label, opts, index=index, key=key)
            elif q.answer_type == "number":
                new_answers[q.id] = st.text_input(label, value=current, key=key)
            else:
                new_answers[q.id] = st.text_input(label, value=current, key=key)
        submitted = st.form_submit_button("Save answers and recompute")
        if submitted:
            st.session_state.answers = {k: v for k, v in new_answers.items() if v}
            st.session_state.run_again = True


def _render_optimizations(state: GraphState) -> None:
    if not state.optimization_suggestions:
        st.caption("No optimization suggestions generated.")
        return
    for suggestion in state.optimization_suggestions:
        with st.container(border=True):
            badge = "Now" if suggestion.horizon == "now" else "Future"
            st.markdown(f"**[{badge}] {suggestion.title}** — _{suggestion.jurisdiction}_")
            if suggestion.est_savings:
                st.caption(f"Estimated savings: ~${suggestion.est_savings:,.0f}")
            st.write(suggestion.rationale)
            if suggestion.action_steps:
                st.markdown("Action steps:")
                for step in suggestion.action_steps:
                    st.markdown(f"- {step}")


def _render_artifacts(state: GraphState) -> None:
    if not state.filing_artifacts:
        st.caption("No filing artifacts available. Generate a draft first.")
        return
    st.caption("Drafts only — every artifact is stamped `transmissible=false`. You must file via CRA / IRS yourself.")
    for key, artifact in state.filing_artifacts.items():
        content = base64.b64decode(artifact.content_b64)
        st.download_button(
            label=f"Download {artifact.filename}  ({artifact.form_code})",
            data=content,
            file_name=artifact.filename,
            mime=artifact.mime_type,
            key=f"download_{key}",
        )


def _render_draft_returns(state: GraphState) -> None:
    if not state.draft_returns:
        return
    for jurisdiction, draft in state.draft_returns.items():
        with st.expander(f"{jurisdiction} draft return", expanded=True):
            cols = st.columns(3)
            cols[0].metric("Total income", f"${draft.totals.get('total_income', draft.total_income):,.2f}")
            cols[1].metric("Taxable income", f"${draft.totals.get('taxable_income', draft.taxable_income):,.2f}")
            cols[2].metric("Total tax", f"${draft.totals.get('total_tax', draft.estimated_tax):,.2f}")
            cols2 = st.columns(2)
            cols2[0].metric("Refund", f"${draft.totals.get('refund', draft.estimated_refund):,.2f}")
            cols2[1].metric("Balance owing", f"${draft.totals.get('balance_owing', 0.0):,.2f}")
            if draft.notes:
                with st.expander("Engine notes", expanded=False):
                    for note in draft.notes:
                        st.markdown(f"- {note}")
            if draft.line_items:
                with st.expander("Line items", expanded=False):
                    for k, v in draft.line_items.items():
                        st.markdown(f"- **{k}**: ${v:,.2f}")


def run_app() -> None:
    graph = build_graph()
    _ensure_session_defaults()

    st.set_page_config(page_title="WealthTax Agent", page_icon="💸")
    st.title("WealthTax Agent — Multi-Country Tax Filing Assistant")
    st.write(
        "Upload Canadian and US tax forms. The agent identifies each form, computes draft returns, "
        "suggests legal tax-reduction moves, and produces filing-ready artifacts. "
        "You remain responsible for reviewing and filing."
    )

    st.subheader("Trust & Responsibility")
    st.markdown(
        "- **System assists with:** identifying forms, computing draft returns, optimization suggestions\n"
        "- **You decide:** what to file and whether to use the draft as a starting point\n"
        "- **Never automated:** transmission to CRA NETFILE or IRS MeF (not certified)"
    )

    st.subheader("1) Year, jurisdictions, slips")
    year_col, jurisdiction_col = st.columns([1, 2])
    years = _available_years_combined()
    default_year = max(years)
    with year_col:
        filing_year = st.selectbox("Tax year", years, index=years.index(default_year))
    with jurisdiction_col:
        jurisdictions = st.multiselect(
            "Jurisdictions to compute",
            options=["CA", "US"],
            default=["CA"],
            help="Pick one or both. Both selected means a cross-border draft.",
        )

    reviewer_name = st.text_input("Reviewer name (optional)", placeholder="e.g., Alex Chen")
    uploaded_files = st.file_uploader(
        "Upload tax forms (PDF / images)",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        with st.expander("Selected files", expanded=False):
            for f in uploaded_files:
                st.markdown(f"- {f.name} ({_format_bytes(f.size)})")

    validation_warnings = _validate_uploads(uploaded_files)
    for warning in validation_warnings:
        st.warning(warning)

    generate_disabled = (not uploaded_files) or bool(validation_warnings) or not jurisdictions

    run_clicked = st.button("Generate draft return", disabled=generate_disabled)
    run_again = st.session_state.pop("run_again", False)

    if run_clicked or run_again:
        with st.spinner("Classifying forms, computing taxes, building artifacts..."):
            try:
                raw_docs = [
                    InputDocument(content=f.read(), filename=f.name, mime_type=getattr(f, "type", None))
                    for f in uploaded_files or []
                ]
                if not raw_docs and st.session_state.last_state:
                    raw_docs = st.session_state.last_state.raw_docs
                initial_state = GraphState(
                    raw_docs=raw_docs,
                    filing_year=int(filing_year),
                    jurisdictions=list(jurisdictions),
                    user_answers=dict(st.session_state.answers or {}),
                )
                final_state = _coerce_graph_state(graph.invoke(initial_state))
                st.session_state.last_state = final_state
                _reset_approval_checks()
                st.success("Draft generated. Review below.")
            except (ValidationError, TypeError, ValueError, RuntimeError) as exc:
                message = _sanitize_error_message(str(exc))
                st.session_state.last_state = GraphState(
                    raw_docs=[],
                    warnings=[f"Draft generation failed: {message}"],
                )
                _reset_approval_checks()
                st.error("Draft generation failed. Review the warning details and try again.")

    state: GraphState = st.session_state.last_state
    if not state:
        st.info("Upload forms, pick year + jurisdictions, then click 'Generate draft return'.")
        return

    if state.llm_provider:
        st.caption(f"LLM provider: {state.llm_provider}")

    if state.warnings:
        st.subheader("Review flags")
        for warning in state.warnings:
            st.warning(warning)

    _render_unsupported_section(state)

    if state.awaiting_clarification:
        _render_clarifying_questions(state)
        return

    if not state.draft_returns and state.draft_return is None:
        st.info("No draft return computed. Check unsupported-forms list above.")
        return

    st.subheader("2) Draft returns")
    _render_draft_returns(state)

    summary_tab, optim_tab, slips_tab, artifacts_tab = st.tabs([
        "Explanations",
        "Optimization suggestions",
        "Parsed forms",
        "Filing artifacts",
    ])

    with summary_tab:
        if state.explanation and state.explanation.lines:
            for key, text in state.explanation.lines.items():
                st.markdown(f"**{key}**: {text}")
        else:
            st.info("No explanation text was generated.")

    with optim_tab:
        _render_optimizations(state)

    with slips_tab:
        if state.extracts:
            for index, extract in enumerate(state.extracts, start=1):
                with st.expander(f"{index}. {extract.form_code} ({extract.jurisdiction}) — {extract.source_filename or 'unnamed'}", expanded=False):
                    if extract.fields:
                        for k, v in extract.fields.items():
                            st.markdown(f"- **{k}**: {v:,.2f}")
                    else:
                        st.caption("No numeric fields extracted.")
        elif state.slips:
            for index, slip in enumerate(state.slips, start=1):
                with st.expander(f"Slip {index}: {slip.type}", expanded=False):
                    for field_name, field_value in slip.fields.items():
                        st.markdown(f"- **{field_name}**: {field_value:,.2f}")
        else:
            st.caption("No parsed forms available.")

    with artifacts_tab:
        _render_artifacts(state)

    if state.clarifying_questions:
        with st.expander("Refine the return with more answers", expanded=False):
            _render_clarifying_questions(state)

    st.markdown("---")
    st.subheader("3) Human decision")
    st.caption("The agent never transmits to CRA NETFILE or IRS MeF. You must file via official channels.")
    check_slips = st.checkbox(
        "I verified all line items against my source forms.",
        key="approve_check_slips",
    )
    check_explanations = st.checkbox(
        "I reviewed the explanations, warning flags, and optimization suggestions.",
        key="approve_check_explanations",
    )
    check_responsibility = st.checkbox(
        "I understand this tool does not file with CRA/IRS and I remain responsible.",
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
            "You approved this draft. The system will NOT file with CRA/IRS; "
            "use the downloaded artifacts as a starting point for your own filing."
        )

    review_report = _build_review_report(state, reviewer_name)
    st.download_button(
        "Download review report (TXT)",
        data=review_report,
        file_name="wealthtax_review_report.txt",
        mime="text/plain",
    )


def main() -> None:
    run_app()


if __name__ == "__main__":
    main()
