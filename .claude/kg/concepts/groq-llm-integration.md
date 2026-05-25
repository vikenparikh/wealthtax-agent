---
concept: groq-llm-integration
tags: [llm, groq, pii, third-party, ocr, extraction]
related: [tax-engine, auth-and-storage, compliance-gaps, user-data-model]
files: [src/wealthtax_agent/llm.py, src/wealthtax_agent/parse_docs.py, src/wealthtax_agent/explain_return.py]
last-updated: 2026-05-25
---

# Groq LLM Integration

Third-party LLM calls, the PII exposure boundary, and sanitization approach.

## Models in use

| Role | Model | Trigger |
|---|---|---|
| OCR / form parsing | `meta-llama/llama-4-scout-17b-16e-instruct` (vision) | PDF/image when `LOCAL_OCR_ONLY=false` |
| Form classification fallback | `llama-3.1-8b-instant` | Rule-based classifier miss |
| Field extraction | `llama-3.1-8b-instant` | LLM path in `extract_forms.py` |
| Plain-language explanation | `llama-3.1-8b-instant` | Always in `explain_return_node` |
| NL intake parsing | `llama-3.1-8b-instant` | User types a narrative description |

## Client (`llm.py`)

Direct Groq HTTP — no Anthropic SDK. Includes retry helpers and PII sanitization.
Env: `GROQ_API_KEY`, `LLM_PROVIDER=groq`, `OCR_MODEL`, `PARSE_MODEL`, `EXPLAIN_MODEL`.

Local OCR fallback: `LOCAL_OCR_ONLY=true` → tesseract (bypasses Groq entirely for parsing).

## PII exposure boundary — CRITICAL

When a user uploads a tax slip containing raw PII (name, SIN, SSN, PAN, account numbers),
that document text is transmitted to the Groq API after sanitization in `llm.py`.

**Sanitization:** applied before transmission. The implementation lives in `llm.py`.
**No local audit log** of LLM payloads is kept — what was sent to Groq is not recorded.

## Known gaps

- No formal Data Processing Agreement (DPA) with Groq.
- No SOC 2 / PIPEDA compliance documentation for this data flow.
- PII sanitization is best-effort — no formal verification that all PII is stripped before transmission.
- No audit log of LLM request payloads — cannot reconstruct what financial data left the system.
- `transmissible=false` on filing artifacts does not prevent LLM payload transmission to Groq.

## Key invariants

- LLMs are NEVER used for tax arithmetic — only document understanding and explanation.
- All LLM outputs are parsed and validated into Pydantic models before any downstream use.
- No function-calling / tools used — pipeline is deterministic graph + structured output parsing.
