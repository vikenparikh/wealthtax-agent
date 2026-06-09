# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### CI/CD

- Build/deploy migrated from GitHub Actions to VPS-native CI (`infra/autodeploy/ci-repos.yaml`): the host `vps-ci.timer` now builds, tests, and deploys wealthtax-agent. Build/deploy mechanism only — the tax-filing/submission path is unchanged and stays separately gated.

Punch-list captured during the v0.5.0 audit; deferred to v0.5.1:

- Dedicated unit tests: `tests/unit/test_in_itr_serializer.py`, `tests/unit/engines/test_student_loan_cross_border.py`.
- Split `tests/integration/scenarios/test_scenarios_all.py` into 8 named files so failures point at a single named scenario.
- A GitHub Release object built from the `v0.5.0` tag with the CHANGELOG body as release notes.

### Added (post-v0.5.0, pre-v0.5.1)

- **AppTest smoke coverage** — `tests/integration/test_streamlit_smoke.py` boots `src/wealthtax_agent/main.py` via `streamlit.testing.v1.AppTest` under both `WEALTHTAX_MODE=self_hosted` and `WEALTHTAX_MODE=saas`, asserts no exceptions during initial render, and pins UI invariants (jurisdiction picker offers CA + US + IN; year picker includes 2024+). Closes the "Streamlit AppTest smoke coverage" item from the v0.5.0 audit.

### Removed (post-v0.5.0, pre-v0.5.1)

- **`scripts/ui_screenshot_playwright.py`** — had a `SyntaxError` (broken try/except indentation at module top), depended on a `playwright` package not in `requirements.txt`, and used pre-Round F UI selectors that no longer matched the current widget set. UI smoke is now covered by `tests/integration/test_streamlit_smoke.py` (AppTest). Closes the corresponding v0.5.1 punch-list item.

## [0.5.0] — 2026-05-20

Round F: India jurisdiction, residency tests, cross-border guardrails, multi-source ingestion, natural-language intake, full UI wire-up.

### Added

- **India jurisdiction (full)** — old + new regime with auto-select, sections 80C / 80D / 80E / 80G / 80TTA / 24(b), HRA exemption, standard deduction, 87A rebate, surcharge tiers (10 / 15 / 25 / 37%) with 25% cap on the new regime, 4% health-and-education cess, LTCG / STCG with pre/post 23-Jul-2024 split. Tax tables for FY 2023-24 (AY 2024-25) and FY 2024-25 (AY 2025-26). Residency-aware: NR / RNOR pay tax only on India-source income.
- **India form extractors** — Form 16 (TDS certificate), Form 16A (non-salary TDS), Form 26AS (annual tax-credit statement), AIS (Annual Information Statement), STOCK-GAIN (capital gains export).
- **India filing artifact** — ITR JSON shaped like the Indian e-filing schema (PartA-GEN, ScheduleS, ScheduleHP, ScheduleCG, ScheduleVIA, PartB-TI, PartB-TTI). Stamped `"transmissible": false`.
- **Residency tests** — IRS Substantial Presence (current + ⅓·prior + ⅙·prior₂ ≥ 183 and current ≥ 31), CRA 183-day + factual ties, India Section 6 (182 days current, or 60+365 prior-4-year, with 6(6) RNOR exemption). Treaty tie-breaker hints for US-CA Article IV, US-India Article 4, and CA-India when more than one jurisdiction claims residency. Threshold-proximity warnings when the user is within 30 days of any boundary.
- **Cross-border guardrails** — student-loan single-claim enforcement (selects the highest-marginal jurisdiction, zeros the others, emits a warning); RSU sourcing helper per Rev. Proc. 2008-23 / CRA Folio S5-F2-C1; FTC hint generator that flags doubled-taxed income and computes the credit amount.
- **Multi-source ingestion** — Excel (`.xlsx` via openpyxl) and CSV parsers integrated into the existing `parse_docs` pipeline; broker-export column-mapping profiles for Schwab, Wealthsimple, Zerodha; LLM fallback for unknown columns.
- **Deduplication** — content-hash (sha256) and form-fingerprint (`jurisdiction:form_code:payer:rounded_total`) dedupe. The same slip uploaded twice (or as both PDF and Excel) counts once; drops are surfaced in `state.warnings`. Implemented in `src/wealthtax_agent/ingest/dedupe.py`, wired into the LangGraph pipeline as `dedupe_extracts_node`.
- **Natural-language intake** — `parse_intake_narrative(prompt)` turns a one-paragraph description into structured extracts, residency days, and clarifying answers via the LLM; deterministic regex fallback keeps unit tests offline.
- **Real-world scenario tests** — 8 cross-border scenarios in `tests/integration/scenarios/test_scenarios_all.py`: US→CA with India vacation, US RSU vested while CA-resident, Indian H1B returning to India mid-year, US citizen living in Canada (FEIE), Canadian commuter to US, India ROR with US brokerage, dual-status year (US Jan-Jun then permanent move to India), 401(k) withdrawal after emigration to Canada.

### Changed

- **Streamlit UI** is fully wired to every new capability: per-country day-count inputs, residency-test display panel, India in the jurisdiction picker, Excel / CSV upload acceptance, natural-language intake textbox, auth sidebar (active only when `WEALTHTAX_MODE=saas`), manual intake expander, correction chat tab, inline per-field edit, revision history sidebar, and persistence on every successful run.
- `Jurisdiction` literal widened from `Literal["CA", "US"]` to `Literal["CA", "US", "IN"]` in `src/wealthtax_agent/state.py`.
- `GraphState` gained `residency_days: Dict[str, int]` and `residency_status: Dict[str, str]`.
- Pipeline expanded to insert `dedupe_extracts_node` and `residency_test_node` between `extract_forms` and `apply_corrections`.
- README now describes multi-jurisdiction support, residency tests, broker-export ingestion, NL intake, and cross-border guardrails.
- `pyproject.toml` description updated to "AI-native multi-jurisdiction tax draft assistant (CA / US / IN)".

### Test count

290 → **386** passing.

## [0.4.0] — Production foundation (PR #4)

- Account system (sign-up, sign-in, session) with `WEALTHTAX_MODE` toggle for SaaS vs self-hosted.
- Encrypted PII at rest (Fernet).
- CPA-style correction loop: chat-driven corrections, staging, apply, revert, revision history.
- Manual intake wizard for users without slips to upload.
- Docker + docker-compose with PostgreSQL 16, healthchecks, env-var-driven config.
- Alembic initial-schema migration.

## [0.3.0] — Round D (PR #3)

- AMT, NIIT, QBI, OAS clawback, Premium Tax Credit, FEIE (Form 2555).
- Amendment flow (T1-ADJ, 1040-X).
- Persistence layer for completed returns.
- Year-over-year projection.
- 10 new form extractors.

## [0.2.0] — Carry-forwards & expansion (PR #2)

- 8 new form extractors.
- 7 new sub-jurisdictions (provincial / state tax tables).
- Capital-loss carry-forward, RRSP room rollover, tuition carry-forward.
- Quarterly estimated-tax vouchers (1040-ES, INNS3).
- Year-over-year planning summary.

## [0.1.0] — Multi-country base (PR #1)

- Initial public version with a Canadian engine (federal + provincial brackets, BPA, CPP, EI, dividend tax credit) and a United States engine (federal + state brackets, standard deduction, CTC, FICA, preferential capital-gain rates).
- LangGraph pipeline: classify → extract → clarify → reason → optimize → explain → build → format.
- Streamlit UI for upload + draft display.
- 33 supported forms.
