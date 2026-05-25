---
title: WealthTax Agent — Knowledge Graph Index
last-updated: 2026-05-25
---

# WealthTax Agent — KG Index

AI-assisted tax-draft assistant for Canada / US / India cross-border filers.
LangGraph pipeline, Streamlit UI, Groq-hosted LLMs, Pydantic state, Fernet-encrypted PII.

## Concepts

| Slug | One-liner |
|---|---|
| [tax-engine](concepts/tax-engine.md) | Rule-based CA/US/IN bracket engines; LLMs never touch arithmetic |
| [jurisdictions](concepts/jurisdictions.md) | How jurisdictions are modeled and how to add one |
| [user-data-model](concepts/user-data-model.md) | Financial data schema, GraphState, ORM, where data lives |
| [auth-and-storage](concepts/auth-and-storage.md) | Auth, session tokens, Fernet encryption posture (honest) |
| [groq-llm-integration](concepts/groq-llm-integration.md) | Third-party LLM calls, PII exposure boundary, sanitization |
| [compliance-gaps](concepts/compliance-gaps.md) | Explicit gap inventory — prototype honesty |
| [api-routes](concepts/api-routes.md) | Streamlit UI sections / LangGraph node inventory (no REST layer) |

## Pipeline (data flow)

```
parse_docs → classify_forms → extract_forms → dedupe_extracts
→ residency_test → apply_corrections → ask_clarifications
→ reason_tax → optimize → explain_return → build_return → format_outputs
```

## Key invariants

- LLMs are used only for document understanding and explanation — never for tax arithmetic.
- `transmissible=false` is a flag in artifact JSON/XML, not a technical enforcement mechanism.
- All filing artifacts are download-only; the agent never contacts CRA/IRS/India e-filing portal.
- Groq receives raw slip text (potentially containing SIN/SSN/PAN) — no formal DPA exists.
