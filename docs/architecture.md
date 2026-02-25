# Architecture

## Source layout

All application code lives in `src/wealthtax_agent`.

- `main.py`: Streamlit UI rendering and user interaction.
- `graph.py`: LangGraph workflow composition.
- `parse_docs.py`: OCR + parsing node.
- `reason_tax.py`: deterministic tax reasoning node.
- `build_return.py`: return build placeholder node.
- `explain_return.py`: explanation generation node.
- `state.py`: shared Pydantic state models.
- `llm.py`: provider selection and model configuration.

The repository keeps implementation code in `src` only; root-level files are project metadata, tests, and documentation.

## Runtime flow

1. User uploads synthetic slips in Streamlit.
2. `parse_docs_node` performs OCR and structured extraction.
3. `reason_tax_node` computes simplified return fields.
4. `build_return_node` preserves draft shape for future T1 mapping.
5. `explain_return_node` generates brief explanations with deterministic fallback.
6. UI shows metrics, explanations, warnings, and human approval step.

## Provider strategy

- `LLM_PROVIDER=groq` is the supported provider mode.
- `GROQ_API_KEY` is required at runtime.
- `GROQ_BASE_URL` (or `OPENAI_BASE_URL` for compatibility) can override endpoint URL.
