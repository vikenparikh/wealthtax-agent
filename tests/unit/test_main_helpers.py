from types import SimpleNamespace

import wealthtax_agent.main as main
from wealthtax_agent.state import DraftReturn, GraphState, Slip


def test_validate_uploads_limits_count_and_size():
    files = [SimpleNamespace(name=f"f{i}.pdf", size=1) for i in range(main.MAX_FILES + 1)]
    files[0] = SimpleNamespace(name="big.pdf", size=main.MAX_FILE_SIZE_BYTES + 1)

    warnings = main._validate_uploads(files)

    assert any("at most" in warning for warning in warnings)
    assert any("exceeds 5MB" in warning for warning in warnings)


def test_format_bytes_human_readable():
    assert main._format_bytes(512) == "512.0 B"
    assert main._format_bytes(1024) == "1.0 KB"
    assert main._format_bytes(1024 * 1024) == "1.0 MB"


def test_sanitize_error_message_redacts_keys():
    message = "bad request using gsk_abc123 and api_key details"

    sanitized = main._sanitize_error_message(message)

    assert sanitized == "Model provider authentication failed. Verify GROQ_API_KEY and endpoint settings."


def test_approval_ready_requires_all_checks():
    assert not main._approval_ready([True, False, True])
    assert main._approval_ready([True, True, True])


def test_build_review_report_contains_expected_fields():
    state = GraphState(
        slips=[Slip(type="T4", fields={"employment_income": 80000.0})],
        # Use draft_returns (multi-jurisdiction) to exercise the new report path.
        draft_returns={
            "CA": DraftReturn(
                total_income=80000.0,
                rrsp_deduction=7000.0,
                taxable_income=73000.0,
                estimated_tax=18250.0,
                estimated_refund=0.0,
            )
        },
        warnings=["Example warning"],
        llm_provider="groq",
        human_approved=False,
    )

    report = main._build_review_report(state, "Dana")

    assert "Reviewer: Dana" in report
    assert "LLM provider: groq" in report
    assert "Parsed slips: 1" in report
    assert "80,000.00" in report
    assert "- Example warning" in report


def test_build_review_report_contains_ca_rrsp_field():
    state = GraphState(
        draft_returns={
            "CA": DraftReturn(
                total_income=90000.0,
                rrsp_deduction=5000.0,
                taxable_income=85000.0,
                estimated_tax=20000.0,
                estimated_refund=0.0,
            )
        },
    )

    report = main._build_review_report(state, "")

    assert "CA Draft Summary" in report
    assert "RRSP deduction" in report


def test_build_review_report_handles_missing_draft():
    state = GraphState()

    report = main._build_review_report(state, "")

    assert "No draft return available." in report
