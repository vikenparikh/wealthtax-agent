"""Form extractor registry. Importing this package registers all supported forms."""

from wealthtax_agent.forms import registry  # noqa: F401

# Importing the per-form modules registers each extractor by side-effect.
from wealthtax_agent.forms.ca import (  # noqa: F401
    t4, t5, t3, t5008, t2202, t4a, rrsp, t776, t2125,
)
from wealthtax_agent.forms.us import (  # noqa: F401
    w2,
    i1099_int, i1099_div, i1099_b, i1099_nec, i1099_misc, i1099_r,
    i1098, i1098_e, i1098_t,
    ssa_1099, k1,
    sch_a, sch_b, sch_c, sch_d,
)
