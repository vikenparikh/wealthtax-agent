---
concept: user-data-model
tags: [schema, state, pydantic, orm, data]
related: [tax-engine, auth-and-storage, groq-llm-integration, api-routes]
files: [src/wealthtax_agent/state.py, src/wealthtax_agent/db/models.py, src/wealthtax_agent/db/repo.py]
last-updated: 2026-05-25
---

# User Data Model

Financial data schema, pipeline state, ORM models, and where data lives.

## Pipeline state (`state.py`)

`GraphState` is the single Pydantic model threaded through every LangGraph node.

Key fields:
- `raw_uploads: list[UploadedFile]` — bytes + filename from Streamlit
- `extracts: list[FormExtract]` — structured fields per classified form
- `residency: ResidencyResult` — days-per-country → resident status
- `draft_returns: list[DraftReturn]` — per-jurisdiction tax computation output
- `filing_artifacts: list[FilingArtifact]` — base64-encoded PDFs / XML / JSON
- `clarifying_questions: list[ClarifyingQuestion]` — outstanding user prompts
- `optimizations: list[OptimizationSuggestion]` — RRSP/401k/IRA/FTC suggestions
- `approved: bool` — human gate; must be `true` before `persist_revision` fires

## ORM models (`db/models.py`)

| Table | Key columns | Notes |
|---|---|---|
| `users` | `id`, `email`, `hashed_password`, `full_name_enc`, `sin_or_ssn_enc`, `dob_enc`, `address_enc` | PII columns Fernet-ciphertext |
| `user_sessions` | `token`, `user_id`, `expires_at` | Fernet-signed tokens |
| `tax_returns` | `id`, `user_id`, `fields` (JSON), `created_at` | `fields` is unencrypted JSON blob |

## Where data lives

| Data | Location | Encrypted? |
|---|---|---|
| User PII (name, SIN/SSN, DOB, address) | `users` table, ciphertext columns | Yes — Fernet at rest |
| Tax return extracts / fields | `TaxReturn.fields` JSON column | No — application-layer JSON only |
| Filing artifacts | In-memory during session; `FilingArtifact.content_b64` | Not persisted to disk independently |
| LLM inputs | Transmitted to Groq after sanitization in `llm.py` | No local audit log of payloads |

## Key invariants

- `GraphState` is immutable per node call — each node returns a new state copy.
- `FilingArtifact.transmissible` is always `false` — a flag, not a technical block.
- `TaxReturn.fields` JSON is NOT individually column-encrypted. A DB breach exposes structured financial data.

## Known gaps

- `TaxReturn.fields` stores structured financial data as plaintext JSON — not covered by Fernet.
- No data-deletion workflow (right to erasure / PIPEDA).
