"""Manual intake: turn typed-in form values into ``FormExtract`` records.

Lets a user share their tax details without uploading a PDF — useful for the
"share details, get filings" production flow.
"""

from wealthtax_agent.intake.wizard import (  # noqa: F401
    SUPPORTED_INTAKE_FORMS,
    field_spec_for,
    manual_extract,
)
