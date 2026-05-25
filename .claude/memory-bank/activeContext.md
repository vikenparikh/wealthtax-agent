# Active context — wealthtax-agent

## Current state

AI-assisted personal-tax draft assistant for cross-border filers covering Canada (T1), United
States (1040), and India (ITR) — all three jurisdictions are wired and functional. The pipeline is
LangGraph with a Streamlit UI; Groq-hosted Llama models handle OCR, classification, extraction,
and explanation. Hard invariant: LLMs never perform tax arithmetic — only the deterministic
CA/US/IN engine code does. Status: prototype (v0.5.0, 478 tests passing), NOT compliant for
real-user financial PII; never transmits returns to any tax authority.

## What's covered by the KG

- **tax-engine** — rule-based bracket engines for CA / US / IN; `compute_tax → DraftReturn`
- **jurisdictions** — how jurisdictions are modeled and how to add one
- **user-data-model** — `GraphState`, `FormExtract`, `DraftReturn`, ORM schema, where PII lives
- **auth-and-storage** — Fernet-encrypted PII columns, session tokens, auth posture
- **groq-llm-integration** — LLM call sites, PII exposure boundary, sanitization in `llm.py`
- **compliance-gaps** — explicit gap inventory (third-party exposure, plaintext fields, no DPA)
- **api-routes** — Streamlit UI sections and LangGraph node inventory (no REST layer)

## Known gaps (be explicit — this handles money)

- Groq third-party PII exposure — no DPA signed
- `transmissible=false` is a soft flag, not a technical block
- `TaxReturn.fields` is plaintext JSON in SQLite
- Password hashing scheme unverified (field exists; bcrypt vs sha256 not confirmed)
- No SOC2 / PIPEDA audit
- No payload audit log for LLM calls

## In flight

_(none yet — populate on session start)_

## Pick up here next session

1. (placeholder)
