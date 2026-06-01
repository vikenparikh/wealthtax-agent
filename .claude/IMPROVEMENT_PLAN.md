# WealthTax Agent — UI Improvement Plan

**Audit date:** 2026-05-25  
**Auditor:** Claude Sonnet 4.6 (read-only; no code changes)  
**Baseline:** `c3e26cb` — 530 tests passing  

---

## Current State

| Area | Status |
|---|---|
| Auth | Sidebar sign-in/sign-up (SaaS) + self-hosted auto-login. Works. |
| Landing | Renders for unauthenticated users; 3-column value prop; no CTA button. |
| Top nav | 4 buttons: Home, New Return, My Returns, Settings. Settings is a stub. |
| Dashboard | Return count + most-recent summary + CPA disclaimer. Functional. |
| Intake — upload | `st.file_uploader` (20 files, 5 MB each). Works. |
| Intake — manual | Expander → form per form-code. All 3 jurisdictions reachable. |
| Intake — narrative | Single text-area → `parse_intake_narrative`. Works. |
| Draft generation | Single "Generate draft return" button → full LangGraph invocation. |
| Jurisdictions | CA + US + IN all selectable via `st.multiselect`. All three are reachable. |
| Draft display | Per-jurisdiction expander with 5 metrics + line-items + engine notes. |
| Correction chat | Chat-input → `parse_correction_prompt` → stage/reject/apply flow. Works. |
| Inline edit | Field-by-field numeric edit via selectbox + number_input. Works. |
| Revision history | Sidebar button per saved return; loads latest revision. Works. |
| Export | `st.download_button` for filing artifacts (PDF/XML/JSON per jurisdiction) + TXT review report. Works. |
| Approval gate | 3 checkboxes before "Approve this draft" button. Works. |
| LLM disclosure | `st.caption(f"LLM provider: {state.llm_provider}")` shown post-draft only. |
| Persistence | Auto-saved to DB after each successful generation. Return survives restart. |

---

## 5-Step Wizard — Gap Analysis

`WizardState` + `save_wizard_draft` / `load_wizard_draft` exist in  
`src/wealthtax_agent/intake/wizard.py` with full step logic (advance, go_back, to_dict/from_dict).  

**Critical gap:** `WizardState` is never instantiated in `main.py`. No `render_wizard_*` function exists. The wizard is **not wired into the UI at all**. The "5-step wizard" PRD item (S6) produced the state machine code but no Streamlit rendering layer.

Consequence: users cannot complete a guided intake. The current UI is a flat single-page form, not the claimed 5-step flow. There is no sidebar step indicator (1/5 … 5/5), no per-step "Next / Back" buttons, and no auto-save on Next click (auto-save only fires after full draft generation).

---

## UI Gaps

| # | Gap | Severity | Location |
|---|---|---|---|
| G1 | Wizard not rendered — `WizardState` dead code in the UI | Critical | `main.py` has no `render_wizard` call |
| G2 | LLM disclosure is post-hoc and easy to miss — shown only as a `st.caption` after draft, not at intake time when PII is about to be transmitted | High | `main.py:741-742` |
| G3 | No progress indicator for generation — spinner text is generic; user has no idea which step is running | Medium | `main.py:689` |
| G4 | Landing has no "Get started" CTA button (PRD S8 item 1) — the `st.info` text is passive | Medium | `main.py:213` |
| G5 | Settings page is a stub (`"Settings will appear here in a future release."`) | Low | `main.py:610` |
| G6 | Return History sidebar loads silently — `st.success()` fires inside the `with get_session()` block but does not visually confirm what was loaded for the user until rerun | Low | `main.py:273-274` |
| G7 | No "Edit" button on return history items — PRD S6 item 3 ("Return History 'Edit' button pre-populates wizard") is not implemented | Medium | `main.py:263-274` |
| G8 | `approve_check_slips` / `approve_check_explanations` checkboxes have no persistent anchor — a browser refresh clears them before the user clicks Approve | Medium | `main.py:822-825` |
| G9 | Review report (TXT download) omits jurisdiction breakdown — shows only CA-legacy fields (`total_income`, `rrsp_deduction`) regardless of which jurisdictions were computed | High | `main.py:87-112` |

---

## Functionality Gaps

| # | Gap | Severity |
|---|---|---|
| F1 | End-to-end wizard journey not possible — G1 above | Critical |
| F2 | LLM consent / disclosure not shown before PII submission — Groq DPA marker exists (`docs/groq-dpa-marker.md`) but there is no user-visible notice that their slip text is sent to Groq for OCR/classification | High |
| F3 | India new-regime vs old-regime choice not exposed in the UI — the engine supports both but the user has no control surface to select the regime | Medium |
| F4 | No JSON export of the full `GraphState` / `DraftReturn` — only filing artifacts (PDF/XML) and TXT report; a machine-readable export would let the user hand off to a CPA's software | Low |
| F5 | No "amend a prior return" UI path — `GraphState.is_amendment` and `prior_filed_totals` exist in state but there is no intake control to set them | Low |
| F6 | Residency-days expander defaults to 0 for all countries — a user who doesn't notice it will silently get wrong residency classification (no warning is generated when all three are zero) | Medium |
| F7 | Clarifying questions are gated behind `state.awaiting_clarification`; if that flag is not set by the engine, the user never sees follow-up questions even when useful | Low |

---

## Testable Acceptance Criteria

| AC | Criterion | Test file |
|---|---|---|
| AC-W1 | Navigating to "New Return" renders a step indicator showing "1 / 5" | `tests/integration/test_wizard_ui.py` |
| AC-W2 | Clicking "Next" on step 1 with jurisdiction + year selected advances to step 2 | same |
| AC-W3 | Clicking "Back" on step 2 returns to step 1 with prior selections intact | same |
| AC-W4 | Completing step 5 ("Review + Submit") triggers draft generation and persists a revision | `tests/integration/test_intake_persistence.py` |
| AC-W5 | Wizard draft saved after step 1; reloading app on step 2 restores correct step and data | same |
| AC-L1 | A visible LLM consent banner or expander appears before the user clicks "Generate draft return" | `tests/integration/test_streamlit_smoke.py` |
| AC-L2 | Landing page has a clickable "Get started" button that scrolls/navigates to auth | same |
| AC-R1 | Review report TXT includes per-jurisdiction totals for all selected jurisdictions | `tests/unit/test_review_report.py` |
| AC-R2 | Residency-days all-zero triggers a visible `st.warning` before draft generation | `tests/integration/test_wizard_ui.py` |
| AC-IN1 | India new-regime toggle is visible when "IN" is in the selected jurisdictions | `tests/integration/test_wizard_ui.py` |

---

## Out of Scope

- Replacing Streamlit with React/Next.js (major rewrite; flag as v2 decision if SaaS growth demands it — Streamlit has real limitations for multi-step stateful flows and mobile use)
- SOC 2 / PIPEDA / right-to-erasure
- MFA, rate limiting, per-user RBAC
- New jurisdictions (UK, AU)
- CPA e-filing integration (IRS MeF / CRA NETFILE live submission)
- LLM arithmetic — invariant preserved throughout; all computation stays in deterministic engines

---

## Build / Test Commands

```bash
# Run all tests
PYTHONPATH=src .venv/bin/python -m pytest --no-cov -q

# Run only integration UI smoke
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_streamlit_smoke.py -v

# Run new wizard tests (once created)
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_wizard_ui.py -v
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_intake_persistence.py -v

# Streamlit local run
WEALTHTAX_MODE=self_hosted \
WEALTHTAX_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
GROQ_API_KEY=gsk-... \
PYTHONPATH=src .venv/bin/python -m streamlit run src/wealthtax_agent/main.py
```

---

## Effort Estimate

| Item | Effort | Risk |
|---|---|---|
| G1 / F1 — Wire wizard into main.py (5 `render_wizard_step_N` functions + sidebar indicator) | 3–4 days | Medium — Streamlit session state + form state interaction is tricky |
| G2 / F2 — LLM consent notice before generation | 0.5 days | Low |
| G9 — Fix review report to include all jurisdictions | 0.5 days | Low |
| F3 — India regime toggle | 1 day | Low |
| G6 / G7 — Return history Edit button + wizard pre-population | 1 day | Medium |
| G8 — Approval checkbox persistence across reruns | 0.5 days | Low |
| F6 — Residency-days zero warning | 0.5 days | Low |
| AC test coverage for above | 2 days | Low |
| **Total** | **~9 days** | |

**Priority order:** G1/F1 (wizard wiring) → G2/F2 (consent) → G9 (review report) → G8 (approval persistence) → F3 (India regime) → remainder.
