import base64
import os
from datetime import datetime
from typing import Iterable, List, Optional

import streamlit as st
from pydantic import ValidationError

from wealthtax_agent.auth import (
    CurrentUser,
    current_user_from_session,
    ensure_self_hosted_user,
    login,
    logout,
    signup,
)
from wealthtax_agent.config.tax_tables import available_years
from wealthtax_agent.config import get_settings
from wealthtax_agent.corrections import compute_correction_diff, parse_correction_prompt, revert_correction
from wealthtax_agent.corrections.intake import parse_intake_narrative
from wealthtax_agent.db import create_all_for_tests, get_session
from wealthtax_agent.db.models import ReturnRevision
from wealthtax_agent.db.repo import (
    consume_rate_token,
    find_return_for_year,
    list_revisions,
    list_user_returns,
    revert_to_revision,
    save_revision,
    start_return,
    write_audit,
)
from wealthtax_agent.graph import build_graph
from wealthtax_agent.intake import SUPPORTED_INTAKE_FORMS, field_spec_for, manual_extract
from wealthtax_agent.intake.wizard import (
    WIZARD_STEP_COUNT,
    WIZARD_STEPS,
    WizardState,
    load_wizard_draft,
    save_wizard_draft,
)
from wealthtax_agent.llm import sanitize_runtime_error
from wealthtax_agent.state import Correction, FieldChange, GraphState, InputDocument


MAX_FILES = int(os.getenv("MAX_UPLOAD_FILES", "20"))
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
APPROVAL_CHECK_KEYS = (
    "approve_check_slips",
    "approve_check_explanations",
    "approve_check_responsibility",
)

# Wizard step labels shown in the step indicator.
_WIZARD_STEP_LABELS = [
    "Jurisdiction & Year",
    "Residency Days",
    "Income Sources",
    "Deductions & Credits",
    "Review & Submit",
]


# ---------- small utilities ----------

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


def _build_review_report(state: GraphState, reviewer_name: str) -> str:
    reviewer = reviewer_name.strip() or "Not provided"
    warnings = state.warnings or []
    warning_block = "\n".join(f"- {warning}" for warning in warnings) or "- None"

    lines = [
        "WealthTax Agent Review Report",
        "=============================",
        f"Reviewer: {reviewer}",
        f"LLM provider: {state.llm_provider or 'unknown'}",
        f"Parsed slips: {len(state.slips)}",
        f"Human approved: {'Yes' if state.human_approved else 'No'}",
        "",
    ]

    if state.draft_returns:
        for jurisdiction, draft in state.draft_returns.items():
            lines += [
                f"{jurisdiction} Draft Summary",
                "-" * (len(jurisdiction) + 15),
                f"  Total income:   {draft.totals.get('total_income', draft.total_income):>14,.2f}",
                f"  Taxable income: {draft.totals.get('taxable_income', draft.taxable_income):>14,.2f}",
                f"  Total tax:      {draft.totals.get('total_tax', draft.estimated_tax):>14,.2f}",
                f"  Refund:         {draft.totals.get('refund', draft.estimated_refund):>14,.2f}",
                f"  Balance owing:  {draft.totals.get('balance_owing', 0.0):>14,.2f}",
            ]
            if jurisdiction == "CA":
                rrsp = draft.line_items.get("rrsp_deduction", getattr(draft, "rrsp_deduction", 0.0))
                lines.append(f"  RRSP deduction: {rrsp:>14,.2f}")
            elif jurisdiction == "US":
                se_tax = draft.line_items.get("self_employment_tax", 0.0)
                lines.append(f"  SE tax:         {se_tax:>14,.2f}")
            elif jurisdiction == "IN":
                regime = draft.line_items.get("india_regime", draft.notes[0] if draft.notes else "")
                lines.append(f"  Regime:         {regime}")
            lines.append("")
    elif state.draft_return is not None:
        draft = state.draft_return
        lines += [
            "Draft Summary",
            "-------------",
            f"  Total income:   {draft.total_income:>14,.2f}",
            f"  Taxable income: {draft.taxable_income:>14,.2f}",
            f"  Estimated tax:  {draft.estimated_tax:>14,.2f}",
            "",
        ]
    else:
        lines.append("No draft return available.")
        lines.append("")

    lines += [
        "Warnings",
        "--------",
        warning_block,
    ]
    return "\n".join(lines) + "\n"


def _available_years_combined() -> List[int]:
    years = set(available_years("ca")) | set(available_years("us")) | set(available_years("in"))
    if not years:
        return [datetime.now().year - 1]
    return sorted(years)


def _ensure_session_defaults() -> None:
    st.session_state.setdefault("last_state", None)
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("session_id", None)
    st.session_state.setdefault("manual_extracts", [])
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("staged_changes", [])
    st.session_state.setdefault("active_return_id", None)
    st.session_state.setdefault("active_revision_number", 0)
    st.session_state.setdefault("auth_mode", "login")
    # Wizard state
    st.session_state.setdefault("wizard", None)       # WizardState or None
    st.session_state.setdefault("wizard_return_id", None)
    st.session_state.setdefault("llm_consent_given", False)
    # Approval state — persisted in wizard data across reruns
    for key in APPROVAL_CHECK_KEYS:
        st.session_state.setdefault(key, False)


def _ensure_db_ready() -> None:
    """Create tables on first run for SQLite. Production deploys run Alembic."""
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        create_all_for_tests()


def _previous_drafts(state: GraphState) -> dict:
    """Snapshot of draft_returns before re-running the graph, for diffing."""
    return {j: d.model_copy(deep=True) for j, d in (state.draft_returns or {}).items()}


# ---------- auth sidebar ----------

def _render_auth_sidebar() -> Optional[CurrentUser]:
    """Returns the signed-in user, or None when not yet authenticated.

    In ``self_hosted`` mode we auto-sign-in a single owner. In ``saas`` mode
    we render sign-up / sign-in forms.
    """
    settings = get_settings()

    if settings.mode == "self_hosted":
        if not st.session_state.session_id:
            st.session_state.session_id = ensure_self_hosted_user()
        return current_user_from_session(st.session_state.session_id)

    user = current_user_from_session(st.session_state.session_id)
    if user:
        st.sidebar.success(f"Signed in as **{user.email}**")
        if st.sidebar.button("Sign out", key="sidebar_signout"):
            logout(st.session_state.session_id)
            st.session_state.session_id = None
            st.session_state.last_state = None
            st.session_state.active_return_id = None
            st.rerun()
        return user

    st.sidebar.header("Account")
    mode = st.sidebar.radio(
        "Auth", ["Sign in", "Sign up"],
        horizontal=True,
        index=0 if st.session_state.auth_mode == "login" else 1,
        key="auth_mode_radio",
    )
    st.session_state.auth_mode = "login" if mode == "Sign in" else "signup"

    with st.sidebar.form("auth_form", clear_on_submit=False):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        full_name = st.text_input("Full name", value="") if mode == "Sign up" else ""
        submitted = st.form_submit_button(mode)

    if submitted:
        if mode == "Sign in":
            result = login(email, password)
        else:
            result = signup(email, password, full_name=full_name or None)
        if result.success:
            st.session_state.session_id = result.session_id
            st.rerun()
        else:
            st.sidebar.error(result.error or "Authentication failed.")
    return None


# ---------- landing (unauthenticated) ----------

def _render_landing() -> None:
    """Landing page shown to unauthenticated / pre-login visitors."""
    st.title("WealthTax Agent")
    st.subheader("Multi-country personal tax drafting — CA · US · IN")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Upload your slips**\nDrop PDFs, images, or Excel. We extract the numbers.")
    with col2:
        st.markdown("**Get a draft return**\nOld + new India regime, FTC, FEIE, 80C — computed in seconds.")
    with col3:
        st.markdown("**Plain-English edits**\nTell us what changed; we update the draft. No arithmetic from the AI.")
    st.info("Sign in or sign up on the left to get started.")


# ---------- top navigation ----------

_NAV_PAGES = ["Home", "New Return", "My Returns", "Settings"]


def _render_top_nav() -> str:
    """Render a top-navigation bar; returns the selected page name."""
    cols = st.columns(len(_NAV_PAGES))
    selected = st.session_state.get("nav_page", "Home")
    for col, page in zip(cols, _NAV_PAGES):
        if col.button(page, key=f"nav_{page}", use_container_width=True):
            st.session_state["nav_page"] = page
            selected = page
    return selected


# ---------- dashboard ----------

def _render_dashboard(user: CurrentUser) -> None:
    """Dashboard: return count, most-recent return summary, CPA disclaimer.

    Each saved return gets an ``Edit`` button that pre-populates the wizard
    from the encrypted ``TaxReturn.fields`` payload via ``load_wizard_draft``
    so the user can resume an in-progress draft without re-typing.
    """
    st.subheader("Dashboard")
    with get_session() as session:
        returns = list_user_returns(session, user.id)
    count = len(returns)
    st.metric("Saved returns", count)
    if returns:
        latest = returns[0]
        jurisdictions = ", ".join(latest.jurisdictions_json or [])
        st.write(f"Most recent: **{latest.filing_year}** — {jurisdictions} ({latest.status})")

        st.markdown("##### Saved returns")
        for ret in returns:
            label = (
                f"{ret.filing_year} · "
                f"{', '.join(ret.jurisdictions_json or []) or '—'} "
                f"({ret.status})"
            )
            cols = st.columns([4, 1])
            cols[0].write(label)
            if cols[1].button("Edit", key=f"dash_edit_{ret.id}"):
                with get_session() as session:
                    loaded = load_wizard_draft(
                        session, return_id=ret.id, user_id=user.id
                    )
                st.session_state.wizard = loaded or WizardState()
                st.session_state.wizard_return_id = ret.id
                st.rerun()
    else:
        st.write("No returns yet. Start one using 'New Return' above.")
    st.caption(
        "WealthTax Agent produces draft returns for review purposes only. "
        "Always verify with a qualified CPA or tax professional before filing."
    )


# ---------- return history sidebar ----------

def _render_return_history(user: CurrentUser) -> None:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Your returns")
    with get_session() as session:
        returns = list_user_returns(session, user.id)
        if not returns:
            st.sidebar.caption("No saved returns yet.")
            return
        for ret in returns:
            label = f"{ret.filing_year} · {', '.join(ret.jurisdictions_json or [])}"
            if st.sidebar.button(label, key=f"load_return_{ret.id}"):
                # Load latest revision into the working session.
                revs = list_revisions(session, user_id=user.id, return_id=ret.id)
                if revs:
                    latest = revs[-1]
                    st.session_state.last_state = GraphState.model_validate(latest.state_json)
                    st.session_state.active_return_id = ret.id
                    st.session_state.active_revision_number = latest.revision_number
                    st.success(f"Loaded {label} (revision {latest.revision_number}).")
                    st.rerun()


# ---------- intake wizard ----------

def _render_manual_intake() -> None:
    """A simple form so the user can share details without uploading a PDF."""
    with st.expander("➕ Add a slip by typing the numbers (no upload needed)", expanded=False):
        codes = sorted(SUPPORTED_INTAKE_FORMS.keys())
        chosen = st.selectbox("Which form?", codes, key="manual_intake_choice")
        spec = field_spec_for(chosen)

        values: dict = {}
        with st.form(f"manual_intake_form_{chosen}"):
            for field in spec:
                label = field["label"] + (" *" if field.get("required") else "")
                values[field["name"]] = st.text_input(label, key=f"mi_{chosen}_{field['name']}")
            submitted = st.form_submit_button(f"Add this {chosen}")
        if submitted:
            try:
                extract = manual_extract(chosen, values)
                if not extract.fields:
                    st.warning("No values were captured. Fill at least one field.")
                else:
                    st.session_state.manual_extracts.append(extract)
                    st.success(f"Added {chosen} with {len(extract.fields)} field(s).")
            except ValueError as exc:
                st.error(str(exc))

    if st.session_state.manual_extracts:
        st.caption(f"Pending manual entries: {len(st.session_state.manual_extracts)}")
        for idx, e in enumerate(st.session_state.manual_extracts):
            with st.expander(f"Manual entry {idx + 1}: {e.form_code} ({e.jurisdiction})", expanded=False):
                for k, v in e.fields.items():
                    st.markdown(f"- **{k}**: {v:,.2f}")
                if st.button("Remove", key=f"remove_manual_{idx}"):
                    st.session_state.manual_extracts.pop(idx)
                    st.rerun()


# ---------- existing display helpers (unchanged) ----------

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


# ---------- correction loop ----------

def _stage_change(change: FieldChange) -> None:
    st.session_state.staged_changes.append(change)


def _render_correction_chat(user: CurrentUser, state: GraphState) -> None:
    st.caption(
        "Tell me in plain English what to fix. Examples: "
        "_\"Set my T4 box 14 to 92,300\"_, "
        "_\"Add a 1099-INT for $400 from Chase\"_, "
        "_\"Remove the 1099-MISC\"_."
    )
    for entry in st.session_state.chat_history:
        with st.chat_message(entry["role"]):
            st.write(entry["content"])

    prompt = st.chat_input("What should I correct?", key="correction_chat_input")
    if prompt:
        # Rate-limit per user.
        settings = get_settings()
        with get_session() as session:
            ok = consume_rate_token(
                session,
                user_id=user.id,
                bucket="correction",
                max_per_minute=settings.correction_rate_per_minute,
            )
        if not ok:
            st.warning("You're sending corrections too fast. Wait a moment and try again.")
            return

        st.session_state.chat_history.append({"role": "user", "content": prompt})
        changes = parse_correction_prompt(prompt)
        if not changes:
            response = "I couldn't parse that into a change. Try being more explicit (form code + field + value)."
        else:
            preview = "\n".join(
                f"- {c.op} `{c.target}` {c.form_code or ''} {c.field or ''} → {c.new_value}"
                for c in changes
            )
            response = f"Parsed {len(changes)} change(s):\n{preview}\n\nClick **Stage** to add them to the pending corrections."
            st.session_state.pending_parsed = [c.model_dump() for c in changes]
        st.session_state.chat_history.append({"role": "assistant", "content": response})
        st.rerun()

    pending = st.session_state.get("pending_parsed")
    if pending:
        st.markdown("**Pending parsed changes:**")
        for idx, c in enumerate(pending):
            cols = st.columns([4, 1, 1])
            cols[0].write(f"`{c['op']}` {c.get('form_code') or ''} {c.get('field') or ''} → {c.get('new_value')}")
            if cols[1].button("Stage", key=f"stage_change_{idx}"):
                _stage_change(FieldChange(**c))
                st.success(f"Staged change {idx + 1}.")
            if cols[2].button("Reject", key=f"reject_change_{idx}"):
                pending.pop(idx)
                st.rerun()

    if st.session_state.staged_changes:
        st.markdown(f"**{len(st.session_state.staged_changes)} staged change(s).**")
        if st.button("Apply staged corrections", key="apply_staged"):
            correction = Correction(
                kind="chat",
                user_prompt="(staged from chat)",
                changes=list(st.session_state.staged_changes),
            )
            state.corrections.append(correction)
            st.session_state.staged_changes = []
            st.session_state.pending_parsed = []
            st.session_state.run_again = True
            st.rerun()

    if state.applied_corrections:
        st.markdown("**Applied corrections (revert any):**")
        for idx, c in enumerate(state.applied_corrections):
            cols = st.columns([4, 1])
            cols[0].write(f"#{idx + 1}: {c.kind} — {c.user_prompt or ''} ({len(c.changes)} change(s))")
            if cols[1].button("Revert", key=f"revert_{c.id}"):
                new_state, ok = revert_correction(state, c.id)
                if ok:
                    st.session_state.last_state = new_state
                    st.session_state.run_again = True
                    st.rerun()


def _render_inline_edit(state: GraphState) -> None:
    """Pencil-style per-field edit: pick a form + field, type the new value,
    stage as an inline_edit correction. Lower-effort than chat for power users.
    """
    if not state.extracts:
        return
    with st.expander("✎ Edit a specific field", expanded=False):
        options = []
        keys = []
        for extract in state.extracts:
            for field, value in extract.fields.items():
                options.append(f"{extract.form_code}.{field}  (current: ${value:,.2f})")
                keys.append((extract.form_code, extract.jurisdiction, field))
        if not options:
            st.caption("No fields available to edit.")
            return
        idx = st.selectbox("Field to edit", range(len(options)), format_func=lambda i: options[i], key="inline_edit_select")
        new_value = st.number_input("New value", value=0.0, key="inline_edit_value")
        if st.button("Apply inline edit", key="inline_edit_apply"):
            form_code, jurisdiction, field = keys[idx]
            correction = Correction(
                kind="inline_edit",
                user_prompt=f"Inline edit: {form_code}.{field}",
                changes=[FieldChange(
                    op="set", target="extract",
                    form_code=form_code, jurisdiction=jurisdiction,
                    field=field, new_value=float(new_value),
                    reason="Inline numeric edit",
                )],
            )
            state.corrections.append(correction)
            st.session_state.run_again = True
            st.rerun()


def _render_diff(state: GraphState) -> None:
    if not state.correction_diff:
        return
    st.markdown("**Last correction's impact:**")
    for jurisdiction, deltas in state.correction_diff.items():
        rows = [f"{k}: {v:+,.2f}" for k, v in deltas.items() if v]
        if rows:
            st.markdown(f"_{jurisdiction}_: " + " · ".join(rows))


# ---------- DB persistence ----------

def _persist_revision(user: CurrentUser, state: GraphState) -> None:
    """Save the freshly-computed state as a new revision under the user."""
    settings = get_settings()
    summary_totals = {j: d.totals for j, d in state.draft_returns.items()} if state.draft_returns else {}
    with get_session() as session:
        ret_id = st.session_state.active_return_id
        if ret_id is None:
            # Look for an existing return for (user, year); reuse if found.
            existing = find_return_for_year(session, user_id=user.id, filing_year=state.filing_year or 0)
            if existing is not None:
                ret_id = existing.id
            else:
                ret = start_return(
                    session,
                    user_id=user.id,
                    filing_year=state.filing_year or 0,
                    jurisdictions=state.jurisdictions,
                )
                ret_id = ret.id
        revision = save_revision(
            session,
            user_id=user.id,
            return_id=ret_id,
            state_json=state.model_dump(mode="json"),
            summary_totals_json=summary_totals,
            form_snapshots=[
                {"form_code": e.form_code, "jurisdiction": e.jurisdiction,
                 "fields_json": e.fields, "source": "manual" if (e.source_filename or "").startswith("manual-") else "upload",
                 "source_filename": e.source_filename}
                for e in state.extracts
            ],
        )
        st.session_state.active_return_id = ret_id
        st.session_state.active_revision_number = revision.revision_number
        write_audit(session, user_id=user.id, return_id=ret_id, action="revision_saved",
                    payload={"revision": revision.revision_number, "totals": summary_totals})


# ---------- wizard rendering ----------

def _render_wizard_step_indicator(wizard: WizardState) -> None:
    """Render 'Step N of 5 — Label' progress bar."""
    step = wizard.step
    total = WIZARD_STEP_COUNT
    label = _WIZARD_STEP_LABELS[step]
    st.progress((step + 1) / total, text=f"Step {step + 1} of {total} — {label}")


def _wizard_save(user: "CurrentUser", wizard: WizardState) -> None:
    """Persist wizard draft to DB (encrypted via TaxReturn.fields)."""
    data = wizard.data
    filing_year = data.get("filing_year") or datetime.now().year - 1
    jurisdictions = data.get("jurisdictions") or []
    with get_session() as session:
        tr = save_wizard_draft(
            session,
            user_id=user.id,
            return_id=st.session_state.wizard_return_id,
            wizard=wizard,
            filing_year=filing_year,
            jurisdictions=jurisdictions,
        )
        st.session_state.wizard_return_id = tr.id


def _render_wizard_step_1(user: "CurrentUser", wizard: WizardState) -> Optional[WizardState]:
    """Step 1: Jurisdiction + Filing Year. Returns new WizardState if Next clicked."""
    st.subheader("Step 1 — Jurisdiction & Filing Year")
    years = _available_years_combined()
    default_year = wizard.data.get("filing_year", max(years))
    filing_year = st.selectbox(
        "Tax year", years, index=years.index(default_year) if default_year in years else 0,
        key="wiz_filing_year",
    )
    default_jurisdictions = wizard.data.get("jurisdictions", ["CA"])
    jurisdictions = st.multiselect(
        "Jurisdictions to compute",
        options=["CA", "US", "IN"],
        default=[j for j in default_jurisdictions if j in ["CA", "US", "IN"]],
        key="wiz_jurisdictions",
    )
    if st.button("Next", key="wiz_next_1", disabled=not jurisdictions):
        new_wizard = wizard.advance({"filing_year": int(filing_year), "jurisdictions": list(jurisdictions)})
        _wizard_save(user, new_wizard)
        return new_wizard
    if not jurisdictions:
        st.caption("Select at least one jurisdiction to continue.")
    return None


def _render_wizard_step_2(user: "CurrentUser", wizard: WizardState) -> Optional[WizardState]:
    """Step 2: Residency days per country."""
    st.subheader("Step 2 — Residency Days")
    st.caption(
        "Used for IRS Substantial Presence, CRA 183-day, and India Section 6 residency tests. "
        "Leave at 0 if not applicable."
    )
    rd_cols = st.columns(3)
    days_us = rd_cols[0].number_input("Days in US", min_value=0, max_value=366,
                                       value=wizard.data.get("days_us", 0), key="wiz_days_us")
    days_ca = rd_cols[1].number_input("Days in Canada", min_value=0, max_value=366,
                                       value=wizard.data.get("days_ca", 0), key="wiz_days_ca")
    days_in = rd_cols[2].number_input("Days in India", min_value=0, max_value=366,
                                       value=wizard.data.get("days_in", 0), key="wiz_days_in")
    st.caption("Optional: prior-year US days for the weighted Substantial Presence count.")
    prior_cols = st.columns(2)
    prior_us_1 = prior_cols[0].number_input("US days — prior year", min_value=0, max_value=366,
                                              value=wizard.data.get("prior_us_1", 0), key="wiz_prior_us_1")
    prior_us_2 = prior_cols[1].number_input("US days — two years ago", min_value=0, max_value=366,
                                              value=wizard.data.get("prior_us_2", 0), key="wiz_prior_us_2")

    if int(days_us) == 0 and int(days_ca) == 0 and int(days_in) == 0:
        st.warning(
            "All residency-day fields are 0. This will classify you as non-resident in "
            "every jurisdiction and may produce incorrect tax treatment. "
            "Update at least one country's days before proceeding.",
            icon="⚠️",
        )

    nav_cols = st.columns(2)
    if nav_cols[0].button("Back", key="wiz_back_2"):
        new_wizard = wizard.go_back()
        _wizard_save(user, new_wizard)
        return new_wizard
    if nav_cols[1].button("Next", key="wiz_next_2"):
        if int(days_us) == 0 and int(days_ca) == 0 and int(days_in) == 0:
            st.error(
                "Cannot proceed: enter at least one day in any jurisdiction, "
                "or confirm you had no taxable presence anywhere this year."
            )
            return None
        new_wizard = wizard.advance({
            "days_us": int(days_us), "days_ca": int(days_ca), "days_in": int(days_in),
            "prior_us_1": int(prior_us_1), "prior_us_2": int(prior_us_2),
        })
        _wizard_save(user, new_wizard)
        return new_wizard
    return None


def _render_wizard_step_3(user: "CurrentUser", wizard: WizardState) -> Optional[WizardState]:
    """Step 3: Income sources — upload + manual entry + narrative."""
    st.subheader("Step 3 — Income Sources")

    uploaded_files = st.file_uploader(
        "Upload tax slips (PDF / images / Excel / CSV)",
        type=["pdf", "png", "jpg", "jpeg", "xlsx", "csv"],
        accept_multiple_files=True,
        key="wiz_uploads",
    )
    if uploaded_files:
        validation_warnings = _validate_uploads(uploaded_files)
        for w in validation_warnings:
            st.warning(w)

    _render_manual_intake()

    with st.expander("Describe your tax year in plain English", expanded=False):
        narrative = st.text_area("Your story", key="wiz_narrative", height=100)
        if st.button("Stage from narrative", key="wiz_stage_narrative") and narrative.strip():
            intake = parse_intake_narrative(narrative)
            st.session_state.manual_extracts = list(st.session_state.manual_extracts) + list(intake.extracts)
            st.session_state.answers.update(intake.user_answers)
            for country, days in intake.residency_days.items():
                st.session_state[f"days_{country.lower()}"] = days
            st.success(f"Staged {len(intake.extracts)} extract(s) from narrative.")

    # India regime toggle — visible only when IN selected.
    jurisdictions = wizard.data.get("jurisdictions", [])
    india_regime = wizard.data.get("india_regime", "new")
    if "IN" in jurisdictions:
        st.markdown("---")
        st.caption("India tax regime:")
        india_regime = st.radio(
            "India regime",
            options=["new", "old"],
            index=0 if india_regime == "new" else 1,
            horizontal=True,
            key="wiz_india_regime",
            help="New regime: lower rates, no exemptions. Old regime: keep deductions (80C, HRA, etc.).",
        )

    has_input = bool(uploaded_files or st.session_state.manual_extracts)
    nav_cols = st.columns(2)
    if nav_cols[0].button("Back", key="wiz_back_3"):
        new_wizard = wizard.go_back()
        _wizard_save(user, new_wizard)
        return new_wizard
    if nav_cols[1].button("Next", key="wiz_next_3", disabled=not has_input):
        upload_names = [f.name for f in (uploaded_files or [])]
        new_wizard = wizard.advance({
            "upload_names": upload_names,
            "manual_extract_count": len(st.session_state.manual_extracts),
            "india_regime": india_regime,
        })
        _wizard_save(user, new_wizard)
        # Stash uploads in session so step 5 can use them.
        st.session_state["wiz_uploaded_files"] = uploaded_files or []
        return new_wizard
    if not has_input:
        st.caption("Add at least one slip (upload or manual) to continue.")
    return None


def _render_wizard_step_4(user: "CurrentUser", wizard: WizardState) -> Optional[WizardState]:
    """Step 4: Deductions & Credits."""
    st.subheader("Step 4 — Deductions & Credits")
    st.caption(
        "Add any manual deduction / credit slips now (RRSP, 80C, 1098-E, etc.). "
        "Skip if already added in Step 3."
    )
    _render_manual_intake()

    reviewer_name = st.text_input(
        "Reviewer name (optional)", key="wiz_reviewer_name",
        value=wizard.data.get("reviewer_name", ""),
    )
    nav_cols = st.columns(2)
    if nav_cols[0].button("Back", key="wiz_back_4"):
        new_wizard = wizard.go_back()
        _wizard_save(user, new_wizard)
        return new_wizard
    if nav_cols[1].button("Next", key="wiz_next_4"):
        new_wizard = wizard.advance({"reviewer_name": reviewer_name})
        _wizard_save(user, new_wizard)
        return new_wizard
    return None


def _render_wizard_step_5(user: "CurrentUser", wizard: WizardState, graph) -> None:
    """Step 5: Review + Groq consent gate + Generate."""
    st.subheader("Step 5 — Review & Submit")
    data = wizard.data

    st.markdown("**Summary of your inputs:**")
    st.markdown(f"- Tax year: **{data.get('filing_year', '—')}**")
    st.markdown(f"- Jurisdictions: **{', '.join(data.get('jurisdictions', []))}**")
    days_summary = ", ".join(
        f"{k}: {v}" for k, v in [
            ("US", data.get("days_us", 0)), ("CA", data.get("days_ca", 0)), ("IN", data.get("days_in", 0))
        ] if v
    ) or "none entered"
    st.markdown(f"- Residency days: **{days_summary}**")
    st.markdown(f"- Slips: {len(data.get('upload_names', []))} upload(s) + {data.get('manual_extract_count', 0)} manual")
    if "IN" in data.get("jurisdictions", []):
        st.markdown(f"- India regime: **{data.get('india_regime', 'new')}**")

    # ----- Groq LLM consent gate -----
    st.markdown("---")
    st.warning(
        "**Privacy notice — Groq LLM:** Generating a draft sends the following information to "
        "Groq (a third-party LLM provider):\n\n"
        "- Extracted text from your uploaded slips (not raw files)\n"
        "- Manual field values you entered\n"
        "- Residency days and jurisdiction selections\n\n"
        "Groq's [Privacy Policy](https://groq.com/privacy-policy) governs how they handle this data. "
        "All filing artifacts remain `transmissible=false` and stay on your device."
    )
    st.checkbox(
        "I consent to sending the above information to Groq to generate my draft return.",
        key="llm_consent_given",
        value=st.session_state.get("llm_consent_given", False),
    )
    # The checkbox's ``key="llm_consent_given"`` already syncs its value into
    # ``st.session_state``; re-assigning it here is redundant *and* raises a
    # StreamlitAPIException (mutating a widget-bound key after instantiation).

    st.markdown("---")
    nav_cols = st.columns(2)
    if nav_cols[0].button("Back", key="wiz_back_5"):
        new_wizard = wizard.go_back()
        _wizard_save(user, new_wizard)
        st.session_state.wizard = new_wizard
        st.rerun()

    generate_clicked = nav_cols[1].button(
        "Generate draft return",
        key="wiz_generate",
        disabled=not st.session_state.get("llm_consent_given", False),
    )
    if not st.session_state.get("llm_consent_given", False):
        st.caption("Check the consent box above to enable draft generation.")

    if generate_clicked:
        _run_wizard_generation(user, wizard, graph)


def _run_wizard_generation(user: "CurrentUser", wizard: WizardState, graph) -> None:
    """Invoke the LangGraph pipeline from wizard state, persist, display results."""
    data = wizard.data
    with st.spinner("Classifying forms, computing taxes, building artifacts..."):
        try:
            base = st.session_state.last_state or GraphState()
            base.filing_year = int(data.get("filing_year", datetime.now().year - 1))
            base.jurisdictions = list(data.get("jurisdictions", []))
            base.user_answers.update(st.session_state.answers or {})

            # Residency days.
            rd = {}
            if data.get("days_us"):
                rd["US"] = int(data["days_us"])
            if data.get("days_ca"):
                rd["CA"] = int(data["days_ca"])
            if data.get("days_in"):
                rd["IN"] = int(data["days_in"])
            if rd:
                base.residency_days = rd
            if data.get("prior_us_1") or data.get("prior_us_2"):
                base.user_answers.setdefault("prior_year_days_us_prior_1", str(int(data.get("prior_us_1", 0))))
                base.user_answers.setdefault("prior_year_days_us_prior_2", str(int(data.get("prior_us_2", 0))))

            # India regime hint.
            if data.get("india_regime"):
                base.user_answers["india_regime"] = data["india_regime"]

            # Uploaded docs.
            uploaded_files = st.session_state.get("wiz_uploaded_files", [])
            if uploaded_files:
                base.raw_docs = base.raw_docs + [
                    InputDocument(content=f.read(), filename=f.name, mime_type=getattr(f, "type", None))
                    for f in uploaded_files
                ]
            # Manual extracts.
            if st.session_state.manual_extracts:
                base.extracts = list(base.extracts) + list(st.session_state.manual_extracts)
                st.session_state.manual_extracts = []

            previous = _previous_drafts(base)
            final_state = _coerce_graph_state(graph.invoke(base))
            if previous and final_state.draft_returns:
                final_state.correction_diff = compute_correction_diff(previous, final_state.draft_returns)
            st.session_state.last_state = final_state
            # Reset approval state for the new draft.
            _reset_approval_checks()
            _persist_revision(user, final_state)
            st.success(f"Draft saved as revision {st.session_state.active_revision_number}.")
        except (ValidationError, TypeError, ValueError, RuntimeError) as exc:
            message = _sanitize_error_message(str(exc))
            st.session_state.last_state = GraphState(
                raw_docs=[],
                warnings=[f"Draft generation failed: {message}"],
            )
            _reset_approval_checks()
            st.error("Draft generation failed. Review the warning details and try again.")

    # After generation, display results inline in step 5.
    state: GraphState = st.session_state.last_state
    if not state:
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

    if state.residency_status:
        with st.expander("Residency tests", expanded=False):
            cols = st.columns(len(state.residency_status))
            for col, (country, status) in zip(cols, state.residency_status.items()):
                col.metric(country, status)
            if state.residency_notes:
                st.caption("Treaty / threshold notes:")
                for note in state.residency_notes:
                    st.markdown(f"- {note}")

    _render_draft_returns(state)
    _render_diff(state)

    summary_tab, correct_tab, optim_tab, slips_tab, artifacts_tab = st.tabs([
        "Explanations", "Correct return (CPA)", "Optimization suggestions",
        "Parsed forms", "Filing artifacts",
    ])
    with summary_tab:
        if state.explanation and state.explanation.lines:
            for key, text in state.explanation.lines.items():
                st.markdown(f"**{key}**: {text}")
        else:
            st.info("No explanation text was generated.")
    with correct_tab:
        _render_correction_chat(user, state)
        _render_inline_edit(state)
    with optim_tab:
        _render_optimizations(state)
    with slips_tab:
        if state.extracts:
            for index, extract in enumerate(state.extracts, start=1):
                with st.expander(
                    f"{index}. {extract.form_code} ({extract.jurisdiction}) — {extract.source_filename or 'unnamed'}",
                    expanded=False,
                ):
                    for k, v in extract.fields.items():
                        st.markdown(f"- **{k}**: {v:,.2f}")
        else:
            st.caption("No parsed forms available.")
    with artifacts_tab:
        _render_artifacts(state)

    _render_approval_section(user, state, data.get("reviewer_name", ""))


def _render_approval_section(user: "CurrentUser", state: GraphState, reviewer_name: str) -> None:
    """Approval checkboxes, persisted in session state so refresh doesn't clear them."""
    st.markdown("---")
    st.subheader("Human Decision")
    st.caption("The agent never transmits to CRA NETFILE or IRS MeF. You must file via official channels.")

    # Read persisted values from session state (survive reruns).
    check_slips = st.checkbox(
        "I verified all line items against my source forms.",
        key="approve_check_slips",
        value=st.session_state.get("approve_check_slips", False),
    )
    check_explanations = st.checkbox(
        "I reviewed the explanations, warning flags, and optimization suggestions.",
        key="approve_check_explanations",
        value=st.session_state.get("approve_check_explanations", False),
    )
    check_responsibility = st.checkbox(
        "I understand this tool does not file with CRA/IRS and I remain responsible.",
        key="approve_check_responsibility",
        value=st.session_state.get("approve_check_responsibility", False),
    )
    can_approve = _approval_ready([check_slips, check_explanations, check_responsibility])

    if not state.human_approved:
        if st.button("Approve this draft (I take responsibility)", disabled=not can_approve, key="approve_btn"):
            state.human_approved = True
            st.session_state.last_state = state
            with get_session() as session:
                write_audit(session, user_id=user.id, return_id=st.session_state.active_return_id,
                            action="approved", payload={"revision": st.session_state.active_revision_number})
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
        key="download_review_report",
    )


# ---------- main app ----------

def run_app() -> None:
    _ensure_session_defaults()
    _ensure_db_ready()
    graph = build_graph()

    st.set_page_config(page_title="WealthTax Agent", page_icon="💸")

    user = _render_auth_sidebar()
    if user is None:
        _render_landing()
        return

    _render_return_history(user)

    nav_page = _render_top_nav()

    if nav_page == "My Returns":
        st.title("WealthTax Agent — My Returns")
        _render_dashboard(user)
        return

    if nav_page == "Settings":
        st.title("WealthTax Agent — Settings")
        st.write("Settings will appear here in a future release.")
        return

    st.title("WealthTax Agent — Multi-Country Tax Filing Assistant")

    # ---- Wizard bootstrap ----
    if nav_page == "New Return" or st.session_state.wizard is None:
        if st.session_state.wizard is None or nav_page == "New Return":
            # Start a fresh wizard only when explicitly requested or on first load.
            if nav_page == "New Return" and st.session_state.wizard is not None:
                # User clicked "New Return" — reset.
                st.session_state.wizard = WizardState()
                st.session_state.wizard_return_id = None
                st.session_state.last_state = None
                st.session_state.manual_extracts = []
                st.session_state.llm_consent_given = False
                _reset_approval_checks()
            elif st.session_state.wizard is None:
                st.session_state.wizard = WizardState()

    wizard: WizardState = st.session_state.wizard

    # Step indicator.
    _render_wizard_step_indicator(wizard)

    # Dispatch to the correct step renderer.
    new_wizard: Optional[WizardState] = None
    step = wizard.step

    if step == 0:
        new_wizard = _render_wizard_step_1(user, wizard)
    elif step == 1:
        new_wizard = _render_wizard_step_2(user, wizard)
    elif step == 2:
        new_wizard = _render_wizard_step_3(user, wizard)
    elif step == 3:
        new_wizard = _render_wizard_step_4(user, wizard)
    elif step == 4:
        _render_wizard_step_5(user, wizard, graph)
        new_wizard = None  # Step 5 manages its own navigation.

    if new_wizard is not None:
        st.session_state.wizard = new_wizard
        st.rerun()


def main() -> None:
    run_app()


if __name__ == "__main__":
    main()
