---
concept: tax-engine
tags: [tax, engines, canada, us, india, cross-border]
related: [jurisdictions, user-data-model, groq-llm-integration, api-routes]
files: [src/wealthtax_agent/engines/ca_engine.py, src/wealthtax_agent/engines/us_engine.py, src/wealthtax_agent/engines/in_engine.py, src/wealthtax_agent/engines/cross_border.py, src/wealthtax_agent/reason_tax.py]
last-updated: 2026-05-25
---

# Tax Engine

Rule-based tax computation across CA / US / IN. LLMs never touch bracket arithmetic.

## Interface

All engines implement `compute_tax(extracts, answers, config) → DraftReturn`.
Dispatched by `reason_tax.py` based on `GraphState.jurisdictions`.

## Canada (`ca_engine.py`)

Federal + provincial (ON / BC / AB / QC) progressive brackets, BPA, CPP/EI credits, RRSP
deduction. Tax tables loaded from `config/tax_tables/ca/YYYY.yaml`.

## United States (`us_engine.py`)

1040 brackets, standard deduction, CTC, FICA, preferential cap-gain rates, state tax
(CA / NY / TX / FL / WA). Quarterly vouchers via `estimated_tax.py`.

## India (`in_engine.py`)

Old regime + new regime selector, 87A rebate, surcharge tiers, 4% cess, LTCG split
pre/post-Jul'24, 80C/80D/80E/80G/24(b), HRA, NR/RNOR/ROR status.

## Cross-border guardrails (`cross_border.py`)

- Student-loan single-claim: highest-marginal jurisdiction wins.
- RSU sourcing: Rev. Proc. 2008-23.
- FTC hints (advisory, not computed).

## Key invariants

- Tax tables are versioned YAML; bracket changes → new YAML file, never edit in code.
- All arithmetic is pure functions (no I/O, no LLM calls).
- `DraftReturn` is Pydantic-validated before any downstream use.
- Output is advisory only — no independent CPA audit has been performed.

## See also

- `jurisdictions` — how to add a new country
- `user-data-model` — `FormExtract` and `DraftReturn` types
