"""Form extractor registry. Importing this package registers all supported forms."""

from wealthtax_agent.forms import registry  # noqa: F401

# Importing the per-form modules registers each extractor by side-effect.
from wealthtax_agent.forms.ca import (  # noqa: F401
    t4, t5, t3, t5008, t2202, t4a, rrsp, t776, t2125,
    t2200, t4rsp, t4rif, t5013,
    t1135, t2222,
)
from wealthtax_agent.forms.us import (  # noqa: F401
    w2, w2g,
    i1099_int, i1099_div, i1099_b, i1099_nec, i1099_misc, i1099_r,
    i1099_k, i1099_g, i1099_sa, i1099_q,
    i1098, i1098_e, i1098_t,
    i1095_a,
    ssa_1099, k1,
    sch_a, sch_b, sch_c, sch_d, sch_e, sch_se,
    i8949, i8889, i5498, i2555,
)
