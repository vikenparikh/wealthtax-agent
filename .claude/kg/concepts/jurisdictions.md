---
concept: jurisdictions
tags: [jurisdiction, canada, us, india, residency, forms]
related: [tax-engine, user-data-model, api-routes]
files: [src/wealthtax_agent/engines/residency.py, src/wealthtax_agent/classify_forms.py, src/wealthtax_agent/config]
last-updated: 2026-05-25
---

# Jurisdictions

How jurisdictions are modeled and how to add a new one.

## Currently supported

| Jurisdiction | Residency test | Forms (count) | Filing artifact |
|---|---|---|---|
| Canada | 183-day deemed residency | T4, T5, T3, T5008, T2202, … | T1 PDF + NETFILE-shaped XML |
| United States | Substantial Presence Test (SPT) | W-2, 1099-*, 1098-*, … | 1040 PDF + IRS MeF-shaped JSON |
| India | §6 ROR / RNOR / NR + treaty | Form 16, 16A, 26AS, AIS, STOCK-GAIN | ITR JSON |

Total: 38 supported form codes across 3 jurisdictions.

## Residency engine (`residency.py`)

Pure function: `days_per_country → ResidencyResult(status, treaty_notes)`.
US SPT, CA 183-day, India §6 — treaty tie-breaker notes are advisory text only.

## Adding a new jurisdiction (e.g. UK)

1. `src/wealthtax_agent/forms/<jk>/` — field schemas per form code.
2. `classify_forms.py` — register form codes in rule table + LLM fallback examples.
3. `extract_forms.py` — add extraction rules.
4. `src/wealthtax_agent/engines/<jk>_engine.py` — implement `compute_tax(…) → DraftReturn`.
5. `src/wealthtax_agent/config/tax_tables/<jk>/YYYY.yaml` — bracket YAML.
6. `reason_tax.py` — wire engine into dispatcher.
7. `src/wealthtax_agent/filing/<jk>_*.py` — artifact builders.
8. `build_return.py` — wire artifacts.
9. `src/wealthtax_agent/config/clarifying_questions/` — add question configs.
10. `tests/integration/scenarios/test_scenarios_all.py` — golden scenarios.

## Adding a bracket year (e.g. 2026)

Copy `config/tax_tables/<jk>/2025.yaml` → `2026.yaml`, update values, add year to
`_available_years_combined()` in `main.py`. Existing scenario tests are year-parameterized
and will surface failures for any broken bracket logic.

## Key invariants

- Jurisdiction detection flows from form classification — never user-declared alone.
- Cross-border guardrails in `cross_border.py` fire after all per-jurisdiction engines run.
