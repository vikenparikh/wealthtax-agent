# Submission Checklist (Wealthsimple AI Builder)

## Required package

- Demo video recorded (2–3 minutes)
- Written explanation prepared (max 500 words)
- Salary expectation added
- Years of hands-on AI experience added

## In this repo

- Fill placeholders in `SUBMISSION.md`:
  - Salary expectation
  - AI experience years
- Use `docs/demo_voiceover.md` as your script
- Use `docs/demo_runbook.md` for recording flow

## Technical pre-flight before recording

- Ensure environment variables are loaded (`LLM_PROVIDER=groq`, `GROQ_API_KEY`)
- Start app with:
  - `PYTHONPATH=src python -m streamlit run src/wealthtax_agent/main.py`
- Confirm upload + generate + approval path works with synthetic slips

## Final quality gate

- Does the demo clearly show what AI is responsible for?
- Does the demo clearly show one critical human-only decision and why?
- Does the writeup include what breaks first at scale?
- Is everything concise and under required length/time limits?

## Submission readiness

- Video exported and playable
- Written response copied from `SUBMISSION.md` and under 500 words
- Compensation and experience fields completed
- All artifacts uploaded before deadline
