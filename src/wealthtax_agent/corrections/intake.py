"""Single-shot natural-language intake.

Takes one paragraph describing the user's year and produces a structured
``IntakeResult`` carrying ``FormExtract`` objects, ``user_answers`` updates,
and ``residency_days``. The LLM path emits a tight JSON envelope; a
deterministic regex fallback covers the common one-liners so unit tests
stay offline.

Mirror of the parser used in the chat correction loop: produces the same
``FieldChange`` shape under the hood, then re-packages them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from wealthtax_agent.llm import call_with_retry, get_client, load_runtime_config
from wealthtax_agent.state import FormExtract


@dataclass
class IntakeResult:
    extracts: List[FormExtract] = field(default_factory=list)
    user_answers: Dict[str, str] = field(default_factory=dict)
    residency_days: Dict[str, int] = field(default_factory=dict)
    jurisdictions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


_INTAKE_SYSTEM_PROMPT = """You convert a taxpayer's one-paragraph description of their tax year
into a structured JSON envelope. Reply only with JSON of this shape:

{
  "extracts": [
    {"form_code": "W-2", "jurisdiction": "US",
     "fields": {"wages": 120000, "federal_income_tax_withheld": 18000},
     "source_filename": "intake-narrative"},
    ...
  ],
  "user_answers": {"filing_status": "single", "province_of_residence": "ON"},
  "residency_days": {"US": 180, "CA": 0, "IN": 184},
  "jurisdictions": ["US", "IN"],
  "notes": ["short one-liners explaining any assumption you made"]
}

Supported form_codes per jurisdiction (use these verbatim):
  CA: T4, T5, T3, T5008, T2202, T4A, RRSP, T776, T2125, T2200, T4RSP, T4RIF, T5013, T1135, T2222
  US: W-2, 1099-INT, 1099-DIV, 1099-B, 1099-NEC, 1099-MISC, 1099-R, 1099-K, 1099-G, 1098-E, 1098-T,
      1095-A, SCH-C, SCH-D, SCH-E, K-1, 5498, 8889, 2555, SSA-1099
  IN: FORM-16, FORM-16A, FORM-26AS, AIS, INVESTMENTS-80C, MEDICAL-80D, STOCK-GAIN

Only emit numbers you are confident about; omit anything you had to guess.
Set residency_days to whole integers; omit a country if the user didn't mention it.
"""


# ---------- Regex fallback ----------

_AMOUNT_RE = r"\$?\s*([0-9][\d,]*(?:\.\d+)?)\s*([kKmM]?)"
_INR_AMOUNT_RE = r"(?:₹|rs\.?|inr)\s*([0-9][\d,]*(?:\.\d+)?)\s*(lakh|cr|crore|k|l)?"


def _amount(raw: str, magnitude: str = "") -> float:
    try:
        val = float(raw.replace(",", ""))
    except ValueError:
        return 0.0
    mag = magnitude.lower()
    if mag == "k":
        val *= 1_000
    elif mag == "m":
        val *= 1_000_000
    elif mag == "l" or mag == "lakh":
        val *= 100_000
    elif mag in {"cr", "crore"}:
        val *= 10_000_000
    return val


def _local_fallback(prompt: str) -> IntakeResult:
    text = prompt.strip()
    lowered = text.lower()
    result = IntakeResult()

    # Days spent in each country: "200 days in India", "180 days in the US", etc.
    country_map = {
        "us": "US", "usa": "US", "united states": "US", "america": "US",
        "canada": "CA",
        "india": "IN", "in": "IN",
    }
    for match in re.finditer(r"(\d{1,3})\s*days?\s+(?:in|at|spent\s+in)\s+(the\s+)?(us|usa|united states|america|canada|india|in)\b", lowered):
        days = int(match.group(1))
        country_raw = match.group(3)
        country = country_map.get(country_raw, "")
        if country:
            result.residency_days[country] = days

    # Compact form: "Days: US 180, India 184", "US: 180 days", "Canada 200 days"
    for match in re.finditer(r"\b(us|usa|united states|america|canada|india|in)\b\s*[:=]?\s*(\d{1,3})\s*(?:days?)?\b", lowered):
        country_raw = match.group(1)
        country = country_map.get(country_raw, "")
        if not country:
            continue
        days = int(match.group(2))
        if 0 < days <= 366 and country not in result.residency_days:
            result.residency_days[country] = days

    # W-2 wages: "$120k W-2", "W-2 wages of $80,000", "earned $90,000 W-2"
    for match in re.finditer(r"w[-\s]?2[^\d$]*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)", lowered):
        val = _amount(match.group(1), match.group(2))
        result.extracts.append(FormExtract(
            form_code="W-2", jurisdiction="US",
            fields={"wages": val},
            source_filename="intake-narrative",
            extractor="rule", confidence="medium",
        ))
        if "US" not in result.jurisdictions:
            result.jurisdictions.append("US")
    for match in re.finditer(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)\s*w[-\s]?2", lowered):
        val = _amount(match.group(1), match.group(2))
        result.extracts.append(FormExtract(
            form_code="W-2", jurisdiction="US",
            fields={"wages": val},
            source_filename="intake-narrative",
            extractor="rule", confidence="medium",
        ))
        if "US" not in result.jurisdictions:
            result.jurisdictions.append("US")

    # Canadian T4: "$70k T4", "T4 income of $50,000"
    t4_patterns = [
        r"t4[^\d$]*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)",
        r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)\s*t4",
    ]
    seen_t4: set = set()
    for pattern in t4_patterns:
        for match in re.finditer(pattern, lowered):
            val = _amount(match.group(1), match.group(2))
            if val == 0 or val in seen_t4:
                continue
            seen_t4.add(val)
            result.extracts.append(FormExtract(
                form_code="T4", jurisdiction="CA",
                fields={"employment_income": val},
                source_filename="intake-narrative",
                extractor="rule", confidence="medium",
            ))
            if "CA" not in result.jurisdictions:
                result.jurisdictions.append("CA")

    # India Form 16: "Form 16 ₹18L salary", "Form 16 ₹1,800,000"
    for match in re.finditer(r"form\s*16[^₹]*₹\s*(\d[\d,]*(?:\.\d+)?)\s*(lakh|cr|crore|k|l)?", lowered):
        val = _amount(match.group(1), match.group(2) or "")
        result.extracts.append(FormExtract(
            form_code="FORM-16", jurisdiction="IN",
            fields={"gross_salary": val},
            source_filename="intake-narrative",
            extractor="rule", confidence="medium",
        ))
        if "IN" not in result.jurisdictions:
            result.jurisdictions.append("IN")

    # 80C contributions: "80C ₹1.5L PPF", "section 80C ₹1,50,000"
    for match in re.finditer(r"80c[^₹]*₹\s*(\d[\d,]*(?:\.\d+)?)\s*(lakh|cr|crore|k|l)?", lowered):
        val = _amount(match.group(1), match.group(2) or "")
        result.extracts.append(FormExtract(
            form_code="INVESTMENTS-80C", jurisdiction="IN",
            fields={"amount": val},
            source_filename="intake-narrative",
            extractor="rule", confidence="medium",
        ))
        if "IN" not in result.jurisdictions:
            result.jurisdictions.append("IN")

    # 80D: "80D ₹25k self insurance"
    for match in re.finditer(r"80d[^₹]*₹\s*(\d[\d,]*(?:\.\d+)?)\s*(lakh|cr|crore|k|l)?", lowered):
        val = _amount(match.group(1), match.group(2) or "")
        result.extracts.append(FormExtract(
            form_code="MEDICAL-80D", jurisdiction="IN",
            fields={"self_premium": val},
            source_filename="intake-narrative",
            extractor="rule", confidence="medium",
        ))

    # Student loan interest: "$2500 1098-E", "1098-E for $1,200", "$2500 1098-E student loan"
    loan_patterns = [
        r"1098[-\s]?e[^\d$]*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)",
        r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)\s*(?:in\s+)?(?:1098[-\s]?e|student\s+loan\s+interest)",
        r"(?:1098[-\s]?e|student\s+loan\s+interest)[^\d$]*\$\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)",
    ]
    seen_amounts: set = set()
    for pattern in loan_patterns:
        for match in re.finditer(pattern, lowered):
            val = _amount(match.group(1), match.group(2))
            if val == 0 or val in seen_amounts:
                continue
            seen_amounts.add(val)
            result.extracts.append(FormExtract(
                form_code="1098-E", jurisdiction="US",
                fields={"student_loan_interest": val},
                source_filename="intake-narrative",
                extractor="rule", confidence="medium",
            ))
            if "US" not in result.jurisdictions:
                result.jurisdictions.append("US")

    # LTCG: "$5k LTCG", "long-term capital gain of $5,000"
    for match in re.finditer(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)\s*(?:long[\s\-]?term|ltcg)", lowered):
        val = _amount(match.group(1), match.group(2))
        result.extracts.append(FormExtract(
            form_code="SCH-D", jurisdiction="US",
            fields={"net_long_term_capital_gain": val},
            source_filename="intake-narrative",
            extractor="rule", confidence="medium",
        ))

    # 1098-T tuition: "$8000 1098-T", "1098-T for $8,000"
    for match in re.finditer(r"1098[-\s]?t[^\d$]*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)", lowered):
        val = _amount(match.group(1), match.group(2))
        result.extracts.append(FormExtract(
            form_code="1098-T", jurisdiction="US",
            fields={"qualified_tuition_paid": val},
            source_filename="intake-narrative",
            extractor="rule", confidence="medium",
        ))

    # 1099-INT interest: "$400 1099-INT", "1099-INT of $250"
    for match in re.finditer(r"1099[-\s]?int[^\d$]*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)", lowered):
        val = _amount(match.group(1), match.group(2))
        result.extracts.append(FormExtract(
            form_code="1099-INT", jurisdiction="US",
            fields={"interest_income": val},
            source_filename="intake-narrative",
            extractor="rule", confidence="medium",
        ))

    # Citizenship / status hints
    if "us citizen" in lowered or "american citizen" in lowered:
        result.user_answers["is_us_citizen"] = "yes"
    if "green card" in lowered:
        result.user_answers["is_green_card_holder"] = "yes"
    if "indian citizen" in lowered:
        result.user_answers["is_indian_citizen"] = "yes"
    if "married filing jointly" in lowered or "mfj" in lowered:
        result.user_answers["filing_status"] = "married_filing_jointly"
    elif re.search(r"\bsingle\b", lowered):
        result.user_answers["filing_status"] = "single"
    if "moved" in lowered or "relocated" in lowered:
        result.user_answers["moved_country_during_year"] = "yes"

    return result


def parse_intake_narrative(prompt: str) -> IntakeResult:
    """Parse a one-paragraph natural-language description of the tax year.

    Tries the LLM first; falls back to the deterministic regex parser on any
    error so unit tests stay offline.
    """
    if not prompt or not prompt.strip():
        return IntakeResult()

    try:
        runtime = load_runtime_config()
        client = get_client(runtime)
    except Exception:
        return _local_fallback(prompt)

    def _call():
        return client.chat.completions.create(
            model=runtime.parse_model,
            messages=[
                {"role": "system", "content": _INTAKE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

    try:
        response = call_with_retry(_call)
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:
        return _local_fallback(prompt)

    return _result_from_dict(data) or _local_fallback(prompt)


def _result_from_dict(data: dict) -> Optional[IntakeResult]:
    if not isinstance(data, dict):
        return None
    out = IntakeResult()
    for raw in data.get("extracts", []) or []:
        if not isinstance(raw, dict):
            continue
        try:
            fields = {k: float(v) for k, v in (raw.get("fields") or {}).items()}
        except (TypeError, ValueError):
            continue
        out.extracts.append(FormExtract(
            form_code=str(raw.get("form_code", "")).upper(),
            jurisdiction=str(raw.get("jurisdiction", "")).upper(),  # type: ignore[arg-type]
            fields=fields,
            source_filename=str(raw.get("source_filename", "intake-narrative")),
            extractor="llm",
            confidence="medium",
        ))
    for k, v in (data.get("user_answers") or {}).items():
        out.user_answers[str(k)] = str(v)
    for k, v in (data.get("residency_days") or {}).items():
        try:
            out.residency_days[str(k).upper()] = int(v)
        except (TypeError, ValueError):
            continue
    out.jurisdictions = [str(j).upper() for j in (data.get("jurisdictions") or [])]
    out.notes = [str(n) for n in (data.get("notes") or [])]
    return out if (out.extracts or out.user_answers or out.residency_days) else None
