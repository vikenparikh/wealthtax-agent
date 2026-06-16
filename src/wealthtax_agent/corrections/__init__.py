"""CPA-style correction loop.

Pipeline:
  1. ``parse_correction_prompt`` turns natural language into a list of
     ``FieldChange`` ops (LLM call; falls back to a deterministic parser if
     the LLM isn't available so unit tests stay offline).
  2. ``apply_corrections`` is the pure overlay applied as a new LangGraph
     node between ``extract_forms`` and ``ask_clarifications``. It mutates
     a copy of the state, never the input.
  3. ``compute_correction_diff`` produces a per-jurisdiction before/after
     totals diff for the UI to render.
  4. ``revert_correction`` removes one previously-applied correction and
     re-runs the rest from scratch so the result is reproducible.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Dict, List, Optional, Tuple

from wealthtax_agent.llm import call_with_retry, get_client, load_runtime_config
from wealthtax_agent.state import Correction, DraftReturn, FieldChange, FormExtract, GraphState


_CORRECTION_SYSTEM_PROMPT = """You convert a taxpayer's natural-language correction
into a JSON list of structured field changes.

Reply with JSON: {"changes": [<FieldChange>, ...]}. Each FieldChange has:
  - op: "set" | "add" | "remove"
  - target: "extract" | "user_answer" | "form"
  - form_code: optional, e.g. "T4", "W-2", "1099-INT"
  - jurisdiction: optional, "CA" or "US"
  - field: optional, the field name to set (e.g. "employment_income", "wages")
  - new_value: numeric or string
  - reason: short explanation in plain English
  - low_confidence: true when you are unsure

Examples:
  Prompt: "Set my T4 box 14 to 92,300"
  -> {"changes":[{"op":"set","target":"extract","form_code":"T4","field":"employment_income","new_value":92300,"reason":"Updated T4 box 14"}]}

  Prompt: "Add a 1099-INT for $400 from Chase"
  -> {"changes":[{"op":"add","target":"form","form_code":"1099-INT","jurisdiction":"US","field":"interest_income","new_value":400,"reason":"Add new 1099-INT"}]}

  Prompt: "Remove the 1099-MISC"
  -> {"changes":[{"op":"remove","target":"form","form_code":"1099-MISC","reason":"User asked to remove"}]}

  Prompt: "Set my filing status to married filing jointly"
  -> {"changes":[{"op":"set","target":"user_answer","field":"filing_status","new_value":"married_filing_jointly","reason":"User specified MFJ"}]}

Only output valid JSON. Set low_confidence=true if you had to guess.
"""


# ---------- Parsing ----------

_AMOUNT_RE = r"\$?\s*([0-9][\d,]*(?:\.\d+)?)"


def _parse_amount(raw: str) -> Optional[float]:
    match = re.search(_AMOUNT_RE, raw)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _local_fallback_parse(prompt: str) -> List[FieldChange]:
    """Deterministic pattern matcher used when the LLM isn't available.

    Catches the most common phrasings; everything else returns an empty list
    and the UI shows the LLM-driven path instead.
    """
    text = prompt.strip().lower()
    changes: List[FieldChange] = []

    field_map = {
        "T4": "employment_income",
        "W-2": "wages",
        "T5": "interest_income",
        "RRSP": "rrsp_contributions",
        "1099-INT": "interest_income",
        "1099-DIV": "ordinary_dividends",
        "1099-NEC": "nonemployee_compensation",
        "1099-MISC": "rents",
        "1099-R": "taxable_amount",
    }
    form_codes_re = r"(t4|w-?2|t5|rrsp|1099-int|1099-div|1099-nec|1099-misc|1099-r)"
    ca_codes = {"T4", "T5", "RRSP"}

    # "set my T4 box 14 to 92,300" — amount appears AFTER "to"/"=".
    m = re.search(r"\b(?:set|change|update)\b.*?\b" + form_codes_re + r"\b.*?\b(?:to|=)\b\s*\$?\s*([0-9][\d,]*(?:\.\d+)?)", text)
    if m:
        form_code = m.group(1).upper().replace("W2", "W-2")
        amount = _parse_amount(m.group(2))
        field = field_map.get(form_code)
        if field and amount is not None:
            changes.append(FieldChange(
                op="set", target="extract", form_code=form_code, field=field,
                new_value=amount, reason=f"Set {form_code} {field} to ${amount:,.2f}",
            ))

    # "add a 1099-INT for $400 from Chase" — amount appears AFTER "for"/"of" or after a "$".
    m = re.search(r"\badd\b.*?\b" + form_codes_re + r"\b.*?(?:for|of|=)\s*\$?\s*([0-9][\d,]*(?:\.\d+)?)", text)
    if m is None:
        m = re.search(r"\badd\b.*?\b" + form_codes_re + r"\b.*?\$\s*([0-9][\d,]*(?:\.\d+)?)", text)
    if m:
        form_code = m.group(1).upper().replace("W2", "W-2")
        amount = _parse_amount(m.group(2))
        field = field_map.get(form_code)
        if field and amount is not None:
            changes.append(FieldChange(
                op="add", target="form", form_code=form_code,
                jurisdiction="CA" if form_code in ca_codes else "US",
                field=field, new_value=amount,
                reason=f"Add new {form_code} with {field}=${amount:,.2f}",
            ))

    # "remove the 1099-MISC"
    m = re.search(r"\b(?:remove|delete|drop)\b.*?\b(t4|w-?2|t5|rrsp|1099-int|1099-div|1099-nec|1099-misc|1099-r)\b", text)
    if m:
        form_code = m.group(1).upper().replace("W2", "W-2")
        changes.append(FieldChange(
            op="remove", target="form", form_code=form_code,
            reason=f"Remove {form_code} as requested",
        ))

    # "set my filing status to mfj"
    m = re.search(r"\bfiling\s+status\b.*?\b(single|mfj|married\s+filing\s+jointly|married_filing_jointly|head\s+of\s+household)\b", text)
    if m:
        value = m.group(1).strip().lower().replace(" ", "_")
        if value == "mfj":
            value = "married_filing_jointly"
        changes.append(FieldChange(
            op="set", target="user_answer", field="filing_status", new_value=value,
            reason=f"Set filing status to {value}",
        ))

    # "set my province to BC"
    m = re.search(r"\bprovince\b.*?\b(on|bc|ab|qc|ns|nb|mb|sk|pe|nl|yt|nt|nu)\b", text)
    if m:
        changes.append(FieldChange(
            op="set", target="user_answer", field="province_of_residence",
            new_value=m.group(1).upper(),
            reason=f"Set province of residence to {m.group(1).upper()}",
        ))

    return changes


def parse_correction_prompt(prompt: str) -> List[FieldChange]:
    """Parse a natural-language correction. Returns a list of FieldChange ops.

    Tries the LLM first; falls back to local pattern matching when the LLM
    isn't configured or fails. Caller decides whether to ask the user to
    confirm before applying.
    """
    if not prompt or not prompt.strip():
        return []

    try:
        runtime = load_runtime_config()
        client = get_client(runtime)
    except Exception:
        return _local_fallback_parse(prompt)

    def _call():
        return client.chat.completions.create(
            model=runtime.parse_model,
            messages=[
                {"role": "system", "content": _CORRECTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

    try:
        response = call_with_retry(_call)
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:
        return _local_fallback_parse(prompt)

    raw_changes = data.get("changes", []) or []
    parsed: List[FieldChange] = []
    for raw in raw_changes:
        if not isinstance(raw, dict):
            continue
        try:
            parsed.append(FieldChange(**raw))
        except Exception:
            continue
    return parsed or _local_fallback_parse(prompt)


# ---------- Application ----------

def _coerce_value(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("$", "").strip())
        except ValueError:
            return value
    return value


def _find_extract(extracts: List[FormExtract], form_code: str, jurisdiction: Optional[str] = None) -> Optional[FormExtract]:
    for e in extracts:
        if e.form_code != form_code:
            continue
        if jurisdiction and e.jurisdiction != jurisdiction:
            continue
        return e
    return None


def _validate_change(change: FieldChange, state: GraphState) -> Optional[str]:
    """Return an error string if a change fails sanity checks, else None."""
    if change.op == "set" and change.target == "extract":
        if not change.form_code or not change.field:
            return "set on extract requires form_code and field"
    if change.op == "add" and change.target == "form":
        if not change.form_code or not change.jurisdiction:
            return "add form requires form_code and jurisdiction"
    if change.op == "remove" and change.target == "form":
        if not change.form_code:
            return "remove form requires form_code"
    if isinstance(change.new_value, (int, float)) and change.new_value < 0 and change.field in {
        "employment_income", "wages", "interest_income"
    }:
        return f"{change.field} cannot be negative"
    return None


def apply_corrections(state: GraphState) -> GraphState:
    """Apply every staged correction in-order to a copy of the state.

    Pure function — produces a new GraphState; original is not mutated.
    Records each applied correction in ``state.applied_corrections``.
    """
    if not state.corrections:
        return state

    new_state = state.model_copy(deep=True)
    for correction in list(new_state.corrections):
        for change in correction.changes:
            err = _validate_change(change, new_state)
            if err:
                new_state.warnings.append(f"Correction skipped: {err}")
                continue
            _apply_change(new_state, change)
        correction.applied = True
        new_state.applied_corrections.append(correction)

    new_state.corrections = []
    new_state.revision_number += 1
    return new_state


def _apply_change(state: GraphState, change: FieldChange) -> None:
    if change.target == "user_answer":
        if change.op == "set" and change.field is not None:
            state.user_answers[change.field] = str(change.new_value)
        elif change.op == "remove" and change.field is not None:
            state.user_answers.pop(change.field, None)
        return

    if change.target == "form":
        if change.op == "add" and change.form_code and change.jurisdiction:
            # Coerce the value with the same numeric guard the set-extract path
            # uses below: a non-numeric value (e.g. the LLM echoing "four hundred")
            # must degrade gracefully — add the form, skip the bad field, warn —
            # rather than crashing the whole correction pass on float(str).
            fields = {}
            if change.field and change.new_value is not None:
                coerced = _coerce_value(change.new_value)
                if isinstance(coerced, (int, float)):
                    fields[change.field] = float(coerced)
                else:
                    state.warnings.append(
                        f"Correction skipped: {change.field} expects numeric, got {coerced!r}"
                    )
            state.extracts.append(FormExtract(
                form_code=change.form_code,
                jurisdiction=change.jurisdiction,
                fields=fields,
                source_filename=f"manual-correction-{change.form_code}",
                extractor="rule",
                confidence="medium",
            ))
        elif change.op == "remove" and change.form_code:
            state.extracts = [
                e for e in state.extracts
                if not (e.form_code == change.form_code and (not change.jurisdiction or e.jurisdiction == change.jurisdiction))
            ]
        return

    # target == "extract"
    if change.op == "set" and change.form_code and change.field is not None:
        extract = _find_extract(state.extracts, change.form_code, change.jurisdiction)
        if extract is None:
            state.warnings.append(f"Correction skipped: no {change.form_code} extract to set {change.field}")
            return
        coerced = _coerce_value(change.new_value)
        change.old_value = extract.fields.get(change.field)
        if isinstance(coerced, (int, float)):
            extract.fields[change.field] = float(coerced)
        else:
            state.warnings.append(f"Correction skipped: {change.field} expects numeric, got {coerced!r}")


# ---------- Diff + revert ----------

def compute_correction_diff(
    before: Dict[str, DraftReturn], after: Dict[str, DraftReturn]
) -> Dict[str, Dict[str, float]]:
    """Per-jurisdiction summary diff. Negative delta = went down vs before."""
    out: Dict[str, Dict[str, float]] = {}
    keys = ("total_income", "taxable_income", "total_tax", "refund", "balance_owing")
    for jurisdiction, after_draft in after.items():
        before_draft = before.get(jurisdiction)
        before_totals = (before_draft.totals if before_draft else {}) or {}
        after_totals = after_draft.totals or {}
        out[jurisdiction] = {
            key: round(float(after_totals.get(key, 0.0)) - float(before_totals.get(key, 0.0)), 2)
            for key in keys
        }
    return out


def revert_correction(state: GraphState, correction_id: str) -> Tuple[GraphState, bool]:
    """Drop the named correction from ``applied_corrections``, re-stage the rest,
    and return the rebuilt state. The caller should re-run the graph to
    re-compute the draft. Returns (new_state, True) on success.
    """
    new_state = state.model_copy(deep=True)
    keep: List[Correction] = []
    found = False
    for c in new_state.applied_corrections:
        if c.id == correction_id:
            found = True
            continue
        c.applied = False
        keep.append(c)
    if not found:
        return state, False
    new_state.applied_corrections = []
    new_state.corrections = keep
    new_state.revision_number = max(0, new_state.revision_number - 1)
    return new_state, True
