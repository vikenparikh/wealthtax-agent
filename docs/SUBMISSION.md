# Wealthsimple AI Builder Submission – WealthTax Agent

## 500-word explanation (ready to paste)

WealthTax Agent redesigns a legacy tax-prep workflow that was built for manual data entry. Instead of asking a human to read slips line by line, retype values, and mentally reconcile totals, the system takes on the cognitive load of extraction, synthesis, and explanation.

What the human can now do that they could not do before is move from “data entry operator” to “final decision-maker.” In a few steps, a user can upload multiple slips (T4/T5/RRSP), receive a consolidated draft return summary, and understand each key number through plain-English explanations. This compresses the work from many manual micro-decisions into one high-quality review decision.

AI responsibility in this system is explicit and operational, not decorative. The model is responsible for:
1) OCR/transcription of uploaded slips,
2) structured parsing into normalized slip fields,
3) assembling a draft return summary from parsed data, and
4) generating concise explanations for major totals.

The system also handles failure conditions in real time. If parsing or explanation generation fails, warnings are surfaced directly in the UI and deterministic fallbacks preserve continuity. That means the flow degrades gracefully instead of collapsing, which is necessary for real-world use.

Where AI must stop is also explicit: final approval. The critical decision that remains human is whether the draft should be used for filing. This must remain human because tax filing carries legal and financial responsibility, and model outputs can be wrong due to source quality, ambiguity, or edge-case forms. The product enforces this boundary through a dedicated human approval step and clear language that no CRA filing occurs automatically.

What would break first at scale is upstream document variability and policy complexity. As volume grows, the first bottleneck is not UI throughput; it is extraction quality across long-tail document formats, scan quality, and exceptions (amendments, atypical slips, mixed provinces, Quebec dual filing, and carry-forward interactions). The second bottleneck is trust calibration: users need confidence signals tied to evidence, not just outputs. The third is compliance hardening: auditability, policy versioning, and robust controls for model drift and incident response.

The next scale steps are straightforward: broaden slip coverage, add evidence-linked explanations, integrate CRA reconciliation, and introduce confidence thresholds with structured human escalation queues. The design principle remains the same: AI takes operational responsibility for cognitive heavy lifting, while humans retain legally material decisions.

This system is intentionally narrow in scope but real in behavior. It demonstrates an AI-native redesign of work, not a chatbot layered onto the old process.

## Candidate details (fill before submitting)

- Salary expectation: [ADD YOUR NUMBER]
- Years of hands-on experience with AI tools/systems: [ADD YOUR YEARS]
