# Demo Runbook (3 minutes)

## Pre-flight

1. From project root, start app with: `./start.sh` (or `./scripts/app.sh start`).
2. Confirm app is reachable at `http://localhost:8501`.
3. Keep one terminal visible for startup output; show browser for main demo.
4. Prepare 2–4 synthetic slips (T4/T5/RRSP).
5. Note: if `LOCAL_OCR_ONLY=true`, OCR will not fall back to vision model and may warn on low-quality scans.

## Recording script

### 0:00–0:20
- Explain problem: manual slip interpretation and reconciliation friction.

### 0:20–1:20
- Upload synthetic slips.
- Click **Generate draft return**.
- Show total income, RRSP deduction, taxable income, estimated tax.

### 1:20–2:10
- Show plain-English explanations and warning banners when present.
- Explain true pipeline behavior:
	- Local text extraction/OCR runs first.
	- Rule-based slip extraction runs first.
	- Groq parse fallback is used only if rule-based extraction yields no slips.
	- Groq vision OCR fallback is used only when local OCR text quality is low and `LOCAL_OCR_ONLY` is disabled.

### 2:10–2:40
- Emphasize human decision boundary: approval required, no CRA filing.

### 2:40–3:00
- Summarize next scale steps (more slip types, CRA reconciliation, richer tax logic).

## Contingency if API fails

- Continue demo with warning banner shown.
- Explain resilient behavior: deterministic tax reasoning still runs on parsed slips; explanation/output formatting have fallback text/XML paths.

## Stop after recording

- Stop app with: `./stop.sh` (or `./scripts/app.sh stop`).
