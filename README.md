# WealthTax Agent – Multi-Jurisdiction Tax Draft Assistant (CA / US / IN)

This is a prototype built for the Wealthsimple builder challenge.
It redesigns the personal tax workflow for Canada, the United States, and India using a modern, human-centered system with cross-border awareness.

1) 3 min video  of WealthTax Agent- https://drive.google.com/file/d/1KwyjVE9gFBfe6rH5mMn9HvSpVAd14nGe/view?usp=sharing

2) Submission file - https://github.com/vikenparikh/wealthtax-agent/blob/main/WealthsimpleSubmissionFile

3) 7 minute full length video - https://drive.google.com/file/d/1ElDrbsxWw1ecrLweZAQrTNfikkikzOYq/view?usp=drive_link


## What it does

- Accepts any uploaded tax form (PDF / image / **Excel** / **CSV**) for **Canada, the United States, or India** and identifies it.
- If the form is outside the v1 supported list, it returns an explicit
  "unsupported form" message with the reason and a suggested next step.
- Supported forms (38 in total):
  - **Canada (13):** T1 + T4, T5, T3, T5008, T2202, T4A, RRSP receipts, T776,
    T2125, T2200 (employment expenses), T4RSP, T4RIF, T5013 (partnership).
  - **United States (20):** 1040 + W-2, 1099-INT/DIV/B/NEC/MISC/R/K/G,
    1098 / 1098-E / 1098-T, SSA-1099, Schedule K-1, Schedules A/B/C/D/E/SE.
  - **India (5):** Form 16, Form 16A, Form 26AS, AIS (Annual Information Statement), STOCK-GAIN.
- Computes draft returns using real progressive brackets, BPA / CPP / EI /
  dividend tax credit (CA, with provincial tables for **ON / BC / AB / QC**),
  standard deduction / CTC / FICA / preferential capital-gain rates (US, with
  state tables for **CA / NY / TX / FL / WA**), and **India's old + new regime**
  (87A rebate, surcharge tiers, 4% cess, LTCG pre/post-Jul'24 split, sections
  80C / 80D / 80E / 80G / 24(b), HRA exemption, residency-aware NR / RNOR / ROR).
- **Auto-runs residency tests** (US Substantial Presence, CA 183-day deemed residency,
  India §6 ROR / RNOR / NR) and emits **treaty tie-breaker notes** (US-CA Article IV,
  US-India Article 4) when more than one jurisdiction would treat the user as resident.
- **Ingests Excel and CSV broker exports** (Schwab / Wealthsimple / Zerodha) and **dedupes**
  the same form across upload formats (content sha256 + form fingerprint).
- **Natural-language intake**: a one-paragraph description of the year ("I worked in
  the US Jan-Jun and moved to India Jul-Dec, W-2 wages $120k...") is a complete
  alternative to uploading slips — extracts, residency days, and clarifying answers
  are populated automatically.
- **Cross-border guardrails**: student-loan interest can only be claimed in one
  jurisdiction (picks the highest-marginal); RSU vesting is sourced per
  Rev. Proc. 2008-23; FTC hints are emitted when the same income is taxed twice.
- Carry-forward aware: prior-year capital losses, RRSP room rollover,
  tuition carry-forward, HSA + traditional IRA above-the-line adjustments.
- Lets the user pick the **tax year** (multi-year YAML config; 2023 / 2024 / 2025 shipped).
- Asks high-value clarifying questions (marital status, dependants, foreign
  property, RRSP room, filing status, US-person status, prior capital losses,
  HSA, Roth-conversion year) and re-runs the pipeline once answered.
- Suggests **legal** tax-optimization moves for *now* and *future*: RRSP /
  401(k) / IRA top-ups, FHSA, capital-loss harvesting, tuition transfers,
  HSA, student-loan interest, and more.
- Produces downloadable filing-ready artifacts every run:
  - Filled draft PDF (T1 summary / 1040 summary / ITR summary).
  - CRA NETFILE-shaped XML (CA).
  - IRS MeF-shaped JSON (US).
  - Indian e-filing-shaped ITR JSON (IN), with PartA-GEN, ScheduleS, ScheduleHP,
    ScheduleCG, ScheduleVIA, PartB-TI, PartB-TTI.
  - Quarterly estimated-tax vouchers — IRS 1040-ES Q1-Q4 and CRA INNS3 Q1-Q4
    — generated automatically when self-employment income or balance owing
    crosses the threshold.
  - Year-over-year planning summary (next-year action plan).
  - Plain-text review report.
- Presents a UI where the **human must decide** whether to approve and file.
- Explicitly does **not** transmit to CRA NETFILE or IRS MeF — every artifact
  is stamped `transmissible="false"`.

This demonstrates:
- Automation taking on complex document understanding, reasoning, and explanation work.
- A redesigned workflow compared to manual entry + CRA auto-fill in Wealthsimple Tax.
- A clear, legally grounded human decision boundary (signing/filing the return).

## Quickstart

### 1. Prerequisites

- Python 3.10+
- A Groq API key (free tier)

Set provider mode and key:

  ```bash
  export LLM_PROVIDER=groq
  export GROQ_API_KEY=gsk-...
  ```

Optional endpoint/model overrides:

  ```bash
  export GROQ_BASE_URL=https://api.groq.com/openai/v1
  export OPENAI_BASE_URL=https://api.groq.com/openai/v1
  export OCR_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
  export PARSE_MODEL=llama-3.1-8b-instant
  export EXPLAIN_MODEL=llama-3.1-8b-instant
  export LOCAL_OCR_ONLY=false
  export MAX_UPLOAD_FILES=20
  ```
  
`LOCAL_OCR_ONLY=true` forces local OCR-only behavior. For image uploads this requires a local OCR backend (e.g., `tesseract`) to be installed.

Optional deployment-mode flag for the production UI:

  ```bash
  export WEALTHTAX_MODE=saas   # enables the auth sidebar (email sign-up / sign-in)
  # or
  export WEALTHTAX_MODE=self_hosted   # single-user mode, no auth
  ```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the UI

```bash
PYTHONPATH=src python -m streamlit run src/wealthtax_agent/main.py
```

Then open the URL shown in your terminal (by default http://localhost:8501).

### 4. One-command validation (tests + app boot)

```bash
./scripts/validate.sh
```

Optional: override Python binary or key for local runs.

```bash
PYTHON_BIN=$PWD/.venv/bin/python GROQ_API_KEY=gsk-... ./scripts/validate.sh
```

### 5. Using the app

1. Prepare 2–20 slips (T4/T5/RRSP) as PDFs or images.
2. Upload them via the file uploader.
3. Click **"Generate draft return"**.
4. Review the computed totals and explanations.
5. Click **"Approve this draft (I take responsibility)"** if you would be comfortable using it.

The system will not contact CRA; it only produces a draft for demonstration.

### 6. Sample files + end-to-end tests

- Sample upload files (realistic formats): `sample_tax_slips/*.pdf`, `sample_tax_slips/*.png`, `sample_tax_slips/*.jpg`, `sample_tax_slips/*.jpeg`
- Fixture-based end-to-end test: `tests/integration/test_pipeline_with_synthetic_fixture.py`
- Format coverage test: `tests/integration/test_supported_file_formats.py`

Run all validation (tests + app boot):

```bash
./scripts/validate.sh
```

Regenerate realistic sample files and validate all upload formats:

```bash
./scripts/regen_and_test_samples.sh
```

Validation history is automatically appended to:

```bash
docs/run_history.md
```

### Adding Screenshots

To further document the workflow, you can add screenshots of:
- The Streamlit UI after uploading slips and generating a draft return.
- The validation output in your terminal.

**How to add screenshots:**
1. Take a screenshot (Cmd+Shift+4 on Mac, or use your OS tool).
2. Save the image in the `docs/` folder (e.g., `docs/ui_screenshot.png`).
3. Embed it in the README:

```markdown
![Draft Return UI](docs/ui_screenshot.png)
```

Repeat for any other key screens you want to showcase.

---

## 📸 UI Screenshots: End-to-End Flow

Below are placeholders for screenshots demonstrating the full user flow in the WealthTax Agent Streamlit UI. To complete this section, follow the instructions below and add your screenshots to the `docs/` folder.

### 1. Launch & Upload Tax Slips
![Launch and Upload](docs/step1_upload.png)
*User launches the app and uploads sample tax slips (PDF, PNG, JPG, JPEG).*

### 2. Review Extracted Slips
![Review Extracted Slips](docs/step2_review_slips.png)
*The UI displays parsed slips and extracted data for user review.*

### 3. Generate Draft Return
![Draft Return](docs/step3_draft_return.png)
*The draft tax return is generated and shown, with key values highlighted.*

### 4. Approve & Download
![Approve and Download](docs/step4_approve.png)
*User approves the draft and can download the completed return.*

---

## 📷 How to Add or Update Screenshots

1. Launch the Streamlit UI: `streamlit run src/wealthtax_agent/main.py`
2. Walk through the full flow (upload, review, generate, approve).
3. Take screenshots at each step and save as:
   - `docs/step1_upload.png`
   - `docs/step2_review_slips.png`
   - `docs/step3_draft_return.png`
   - `docs/step4_approve.png`
4. Screenshots will be automatically displayed above.

---

## Engineering docs

- Architecture: `docs/architecture.md`
- Demo script: `docs/demo_runbook.md`
- Demo voiceover: `docs/demo_voiceover.md`
- Submission draft: `SUBMISSION.md`
- Submission checklist: `SUBMISSION_CHECKLIST.md`

## Project structure

```text
wealthtax-agent/
  src/
    wealthtax_agent/
      __init__.py
      main.py          # Streamlit UI
      graph.py         # LangGraph graph assembly
      state.py         # Shared state (slips, draft return, explanations)
      parse_docs.py    # Slip parsing (rule-based first, model fallback)
      reason_tax.py    # Simplified tax reasoning
      build_return.py  # Placeholder for T1 mapping
      explain_return.py # Plain-language explanations
      llm.py           # Provider config + client + retry helpers
  tests/
  docs/
  requirements.txt   # Python dependencies
  README.md
```

## Design notes

- **Scope is intentionally narrow**: only a few slip types (T4/T5/RRSP) and simplified tax logic.
- This keeps the prototype buildable in under a week on a laptop while still being realistic.
- The system focuses on:
  - Replacing manual data entry and mental reconciliation.
  - Providing explanations that improve user understanding and decision quality.
  - Making the human decision point explicit and non-delegable.

## Extending the prototype

Ideas for future work (and "what breaks at scale"):

- Support more slip types (T3, T5008, foreign income).
- Integrate CRA Auto-fill data and reconcile against user-uploaded slips.
- Add RAG over the CRA T1 guide and Income Tax Folios for more accurate reasoning.
- Model multiple provinces, Québec dual filing, and more precise tax brackets.
- Track RRSP room and carry-forward losses using prior NOAs.

