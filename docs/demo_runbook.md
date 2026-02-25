# Demo Runbook (3 minutes)

## Pre-flight

1. Activate environment and install deps.
2. Set provider variables (`LLM_PROVIDER`, key, model overrides if needed).
3. Launch app: `PYTHONPATH=src streamlit run src/wealthtax_agent/main.py`.
4. Prepare 2–4 synthetic slips (T4/T5/RRSP).

## Recording script

### 0:00–0:20
- Explain problem: manual slip interpretation and reconciliation friction.

### 0:20–1:20
- Upload synthetic slips.
- Click **Generate draft return**.
- Show total income, RRSP deduction, taxable income, estimated tax.

### 1:20–2:10
- Show plain-English explanations and mention fallback resilience.
- Point to provider indicator and warning banners when present.

### 2:10–2:40
- Emphasize human decision boundary: approval required, no CRA filing.

### 2:40–3:00
- Summarize next scale steps (more slip types, CRA reconciliation, richer tax logic).

## Contingency if API fails

- Continue demo with warning banner shown.
- Explain resilient fallback behavior and deterministic tax logic still available.
