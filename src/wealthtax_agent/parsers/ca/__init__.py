"""Canadian form parsers: T4, T5, RRSP (T4RSP)."""

from wealthtax_agent.parsers.ca.form_t4 import parse_t4
from wealthtax_agent.parsers.ca.form_t5 import parse_t5
from wealthtax_agent.parsers.ca.form_rrsp import parse_rrsp

__all__ = ["parse_t4", "parse_t5", "parse_rrsp"]
