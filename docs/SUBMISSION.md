# Wealthsimple AI Builder Submission – WealthTax Agent

## 500-word explanation (ready to paste)

WealthTax Agent redesigns a legacy tax-prep workflow that was built for manual data entry. Instead of asking a human to read slips line by line, retype values, and mentally reconcile totals, the system takes on the cognitive load of extraction, synthesis, and explanation.

What the human can now do that they could not do before is move from “data entry operator” to “final decision-maker.” In a few steps, a user can upload multiple slips (T4/T5/RRSP), receive a consolidated draft return summary, and understand each key number through plain-English explanations. This compresses the work from many manual micro-decisions into one high-quality review decision.

AI responsibility in this system is explicit and operational, not decorative. The model is used where it adds the most value:
1) OCR/transcription fallback when local extraction quality is too low,
2) structured parsing fallback when rule-based parsing cannot extract slips,
3) generating concise explanations for major totals, and
4) formatting dual draft outputs for readability and portability.

Core numeric reasoning remains deterministic in code: the system aggregates slip fields by type, computes taxable income, and derives an estimated tax value using the prototype formula.

The system also handles failure conditions in real time. It follows a local-first strategy for OCR/text extraction and rule-based parsing, then falls back to model-based steps only when needed. If parsing, explanation generation, or output formatting fails, warnings are surfaced directly in the UI and deterministic fallback paths preserve continuity. That means the flow degrades gracefully instead of collapsing, which is necessary for real-world use.

Where AI must stop is also explicit: final approval. The critical decision that remains human is whether the draft should be used for filing. This must remain human because tax filing carries legal and financial responsibility, and model outputs can be wrong due to source quality, ambiguity, or edge-case forms. The product enforces this boundary through a dedicated human approval step and clear language that no CRA filing occurs automatically.

What would break first at scale is upstream document variability and policy complexity. As volume grows, the first bottleneck is not UI throughput; it is extraction quality across long-tail document formats, scan quality, and exceptions (amendments, atypical slips, mixed provinces, Quebec dual filing, and carry-forward interactions). The second bottleneck is trust calibration: users need confidence signals tied to evidence, not just outputs. The third is compliance hardening: auditability, policy versioning, and robust controls for model drift and incident response.

The next scale steps are straightforward: broaden slip coverage, add evidence-linked explanations, integrate CRA reconciliation, and introduce confidence thresholds with structured human escalation queues. The design principle remains the same: AI takes operational responsibility for cognitive heavy lifting, while humans retain legally material decisions.

This system is intentionally narrow in scope but real in behavior. It demonstrates an AI-native redesign of work, not a chatbot layered onto the old process.

## Candidate details (fill before submitting)

- Salary expectation: [ADD YOUR NUMBER]
- Years of hands-on experience with AI tools/systems: [ADD YOUR YEARS]
