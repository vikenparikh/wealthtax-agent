import json
import re

from wealthtax_agent.llm import call_with_retry, get_client, load_runtime_config, sanitize_runtime_error
from wealthtax_agent.state import Explanation, GraphState


client = None
_client_config = None


def _get_client():
	global client
	global _client_config
	if client is not None and _client_config is None:
		return client
	runtime = load_runtime_config()
	signature = (runtime.base_url, runtime.api_key)
	if client is None or _client_config != signature:
		client = get_client(runtime)
		_client_config = signature
	return client


SYSTEM_PROMPT = """You are an assistant explaining a Canadian tax return to a layperson.
Given a JSON with totals (total_income, rrsp_deduction, taxable_income, estimated_tax),
write very short, plain-English one-sentence explanations for each field.
Return JSON: {"lines": { "total_income": "...", "rrsp_deduction": "...", ... }}.
Keep each explanation under 25 words.
"""

FORMAT_SYSTEM_PROMPT = """You are formatting the output of an AI-powered Canadian tax draft system.

You will receive a JSON object with:
- \"draft_return\": numeric fields (total_income, rrsp_deduction, taxable_income, estimated_tax)
- \"explanations\": short plain-English explanations for some or all of those fields

Your job is to produce BOTH of the following in a single response, in order:

1) A human-readable DRAFT SUMMARY TEXT block.
	- Start with the line: \"WealthTax Agent – Draft Canadian Tax Summary (Not filed)\"
	- Show each key number on its own line in dollars with two decimals.
	- Then a section \"Explanations:\" with one bullet per line of explanation.
	- End with a clear disclaimer that this is a prototype draft and is NOT filed with CRA and the user must verify and file themselves.

2) A pseudo-XML representation of the same data.
	- Wrap everything in <WealthTaxDraftReturn>...</WealthTaxDraftReturn>.
	- Include a <Meta> section with:
		 <Version>0.1</Version>
		 <Jurisdiction>CA</Jurisdiction>
		 <Note>Prototype only - NOT CRA NETFILE compliant</Note>
	- Include a <Summary> section with one tag per numeric field:
		 <TotalIncome>, <RRSPDeduction>, <TaxableIncome>, <EstimatedTax>
	  using plain numbers with two decimals.
	- Include an <Explanations> section with one <Line> element per explanation, with an \"id\" attribute for the field name, e.g. <Line id=\"total_income\">...</Line>.

Output format requirements:
- First, output the draft summary text inside a Markdown code block labelled \"text\".
- Then, output the XML inside a Markdown code block labelled \"xml\".
- Do not add any commentary outside those two code blocks.
- Do not invent additional fields; only use the ones provided.
"""


def _sanitize_error_message(message: str) -> str:
	return sanitize_runtime_error(message)


def _try_parse_explanation_lines(content: str) -> dict:
	try:
		data = json.loads(content)
	except Exception:
		data = None

	if isinstance(data, dict):
		lines = data.get("lines")
		if isinstance(lines, dict) and lines:
			return {str(k): str(v) for k, v in lines.items() if str(v).strip()}

		known_keys = {"total_income", "rrsp_deduction", "taxable_income", "estimated_tax"}
		direct = {k: data.get(k) for k in known_keys if k in data}
		if direct and all(v is not None for v in direct.values()):
			return {str(k): str(v) for k, v in direct.items()}

	parsed = {}
	for line in content.splitlines():
		if ":" not in line:
			continue
		key, value = line.split(":", 1)
		normalized_key = key.strip().lower().replace(" ", "_")
		if normalized_key in {"total_income", "rrsp_deduction", "taxable_income", "estimated_tax"} and value.strip():
			parsed[normalized_key] = value.strip()

	return parsed


def _extract_code_block(content: str, language: str) -> str:
	pattern = rf"```{language}\s*(.*?)```"
	match = re.search(pattern, content, flags=re.DOTALL | re.IGNORECASE)
	if not match:
		raise ValueError(f"Missing {language} code block")
	return match.group(1).strip()


def _build_dual_output_fallback(state: GraphState) -> tuple[str, str]:
	draft = state.draft_return
	if draft is None:
		raise ValueError("Draft return missing")

	explanations = state.explanation.lines if state.explanation else {}
	explanation_lines = [
		f"- {field}: {text}" for field, text in explanations.items()
	]
	if not explanation_lines:
		explanation_lines = [
			"- total_income: Estimated from parsed slips.",
			"- rrsp_deduction: Derived from detected RRSP contribution receipts.",
			"- taxable_income: Total income minus RRSP deduction.",
			"- estimated_tax: Simplified estimate for prototype use only.",
		]

	summary_text = (
		"WealthTax Agent – Draft Canadian Tax Summary (Not filed)\n\n"
		f"Total income: ${draft.total_income:,.2f}\n"
		f"RRSP deduction: ${draft.rrsp_deduction:,.2f}\n"
		f"Taxable income: ${draft.taxable_income:,.2f}\n"
		f"Estimated tax: ${draft.estimated_tax:,.2f}\n\n"
		"Explanations:\n"
		+ "\n".join(explanation_lines)
		+ "\n\nDisclaimer: This is a draft from an AI prototype. It is not filed with CRA.\n"
		"You must verify all amounts and file your tax return yourself."
	)

	xml_lines = [
		"<WealthTaxDraftReturn>",
		"  <Meta>",
		"    <Version>0.1</Version>",
		"    <Jurisdiction>CA</Jurisdiction>",
		"    <Note>Prototype only - NOT CRA NETFILE compliant</Note>",
		"  </Meta>",
		"  <Summary>",
		f"    <TotalIncome>{draft.total_income:.2f}</TotalIncome>",
		f"    <RRSPDeduction>{draft.rrsp_deduction:.2f}</RRSPDeduction>",
		f"    <TaxableIncome>{draft.taxable_income:.2f}</TaxableIncome>",
		f"    <EstimatedTax>{draft.estimated_tax:.2f}</EstimatedTax>",
		"  </Summary>",
		"  <Explanations>",
	]
	for field, text in explanations.items():
		xml_lines.append(f"    <Line id=\"{field}\">{text}</Line>")
	xml_lines.extend([
		"  </Explanations>",
		"</WealthTaxDraftReturn>",
	])

	return summary_text, "\n".join(xml_lines)


def generate_dual_outputs(state: GraphState) -> GraphState:
	if state.draft_return is None:
		return state

	runtime = load_runtime_config()
	active_client = _get_client()
	payload = {
		"draft_return": state.draft_return.model_dump(),
		"explanations": state.explanation.lines if state.explanation else {},
	}
	user_msg = "Here is the JSON with the draft return and explanations:\n\n" + json.dumps(payload)

	try:
		def _call():
			return active_client.chat.completions.create(
				model=runtime.explain_model,
				messages=[
					{"role": "system", "content": FORMAT_SYSTEM_PROMPT},
					{"role": "user", "content": user_msg},
				],
			)

		response = call_with_retry(_call)
		content = response.choices[0].message.content or ""
		state.draft_summary_text = _extract_code_block(content, "text")
		state.draft_pseudo_xml = _extract_code_block(content, "xml")
	except Exception as exc:
		state.warnings.append(f"Output formatting fallback used: {_sanitize_error_message(str(exc))}")
		summary_text, pseudo_xml = _build_dual_output_fallback(state)
		state.draft_summary_text = summary_text
		state.draft_pseudo_xml = pseudo_xml

	return state


def explain_return_node(state: GraphState) -> GraphState:
	if state.draft_return is None:
		return state

	runtime = load_runtime_config()
	state.llm_provider = state.llm_provider or runtime.provider

	payload = state.draft_return.model_dump()
	user_msg = json.dumps(payload)
	active_client = _get_client()

	try:
		def _call():
			return active_client.chat.completions.create(
				model=runtime.explain_model,
				messages=[
					{"role": "system", "content": SYSTEM_PROMPT},
					{"role": "user", "content": user_msg},
				],
				response_format={"type": "json_object"},
			)

		response = call_with_retry(_call)
		content = response.choices[0].message.content
		lines = _try_parse_explanation_lines(content or "")
		if not lines:
			raise ValueError("Invalid explanation payload")
		state.explanation = Explanation(lines=lines)
	except Exception as exc:
		draft = state.draft_return
		error_text = _sanitize_error_message(str(exc))
		if "Invalid explanation payload" not in str(exc):
			state.warnings.append(f"Explanation fallback used: {error_text}")
		state.explanation = Explanation(
			lines={
				"total_income": f"We added reported income sources to estimate total income at ${draft.total_income:,.2f}.",
				"rrsp_deduction": f"We treated reported RRSP contributions as deductions totaling ${draft.rrsp_deduction:,.2f}.",
				"taxable_income": f"Taxable income is total income minus deductions, estimated at ${draft.taxable_income:,.2f}.",
				"estimated_tax": f"Estimated tax uses simplified prototype logic and comes to ${draft.estimated_tax:,.2f}.",
			}
		)

	return state
