# Groq Data Processing Agreement — Marker

**Status:** DPA on file.

WealthTax Agent uses Groq Cloud APIs exclusively for LLM inference (OCR, form
classification, field extraction, explanation generation). No tax-slip text
containing SIN / SSN / PAN is transmitted to Groq without a signed Data
Processing Addendum in place.

**DPA reference:** Groq's standard Data Processing Addendum, accepted via the
Groq Console under the workspace of record for this deployment.

**PII mitigation layers (defence-in-depth):**

1. `LOCAL_OCR_ONLY=true` — when set, raw slip text is processed locally; only
   structured field dictionaries (no free text) are passed to the LLM.
2. `llm.py::sanitize_runtime_error()` — strips key-shaped tokens from any
   error messages before they reach logs.
3. All PII persisted to the DB is Fernet-encrypted at rest (see `db/crypto.py`
   and `db/models.py`).

**To renew or update this marker:**

1. Confirm the active DPA reference in the Groq Console.
2. Update the "DPA reference" line above.
3. Commit with message `docs(security): refresh groq-dpa-marker`.

*Last reviewed: 2026-05-25 — vsparikh1996@gmail.com*
