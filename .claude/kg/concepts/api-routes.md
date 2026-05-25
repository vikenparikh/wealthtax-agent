---
concept: api-routes
tags: [ui, streamlit, langgraph, pipeline, routes]
related: [tax-engine, user-data-model, jurisdictions, groq-llm-integration]
files: [src/wealthtax_agent/main.py, src/wealthtax_agent/graph.py, src/wealthtax_agent/reason_tax.py, src/wealthtax_agent/build_return.py]
last-updated: 2026-05-25
---

# API Routes

No REST API. The "surface" is Streamlit UI sections + LangGraph pipeline nodes.

## Streamlit UI sections (`main.py:run_app()`)

| Section | Function |
|---|---|
| Auth sidebar (saas mode) | `_render_auth_sidebar()` |
| Return history | `_render_return_history()` |
| File upload + NL intake | inline in `run_app()` |
| Manual intake expander | `_render_manual_intake()` |
| Unsupported form notice | `_render_unsupported_section()` |
| Clarifying questions | `_render_clarifying_questions()` |
| Draft return totals | `_render_draft_returns()` |
| Optimization suggestions | `_render_optimizations()` |
| Filing artifact downloads | `_render_artifacts()` |
| Correction chat | `_render_correction_chat()` |
| Inline field edit | `_render_inline_edit()` |
| Revision diff | `_render_diff()` |

## LangGraph pipeline nodes (`graph.py:build_graph()`)

Sequential `StateGraph` with one conditional branch:

1. `parse_docs_node` — bytes → text (Groq vision or local OCR)
2. `classify_forms_node` — text → form_code + jurisdiction
3. `extract_forms_node` — text → `FormExtract`
4. `dedupe_extracts_node` — sha256 + form fingerprint dedupe
5. `residency_test_node` — days-per-country → `ResidencyResult`
6. `apply_corrections_node` — NL narrative + field patches
7. `ask_clarifications_node` — emits `ClarifyingQuestion` list; **conditional pause** here
8. `reason_tax_node` — dispatches CA/US/IN engines + cross-border guardrails
9. `optimize_node` — `OptimizationSuggestion` list
10. `explain_return_node` — LLM plain-language explanation
11. `build_return_node` — `FilingArtifact` list
12. `format_outputs_node` — final render prep

Conditional edge: `has_outstanding_clarifications → pause | continue`.

## Entry points

| Entry | Purpose |
|---|---|
| `main.py:run_app()` | Streamlit entrypoint |
| `graph.py:build_graph()` | Returns compiled `CompiledStateGraph` |
| `graph.py:build_legacy_graph()` | Legacy compatibility variant |
| `db/__init__.py:create_all_for_tests()` | In-memory SQLite for tests |

## Key invariants

- There is no FastAPI / REST layer. All interaction is Streamlit → `build_graph()`.
- Human approval gate fires between `format_outputs_node` and `persist_revision` — cannot be bypassed.
- Pipeline is deterministic; LLM outputs are Pydantic-validated before downstream use.
