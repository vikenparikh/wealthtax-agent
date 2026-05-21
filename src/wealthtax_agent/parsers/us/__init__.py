"""US form parsers: 1099-B, 1099-DIV, 1099-INT, W-2, K-1."""

from wealthtax_agent.parsers.us.form_1099_b import parse_1099b
from wealthtax_agent.parsers.us.form_1099_div import parse_1099div
from wealthtax_agent.parsers.us.form_1099_int import parse_1099int
from wealthtax_agent.parsers.us.form_w2 import parse_w2
from wealthtax_agent.parsers.us.form_k1 import parse_k1

__all__ = ["parse_1099b", "parse_1099div", "parse_1099int", "parse_w2", "parse_k1"]
