"""S2 guard — `FilingArtifact.transmissible=True` must raise.

WealthTax never transmits returns to CRA/IRS/ITD. The Pydantic model rejects
``transmissible=True`` at construction, mutation, and ``model_copy`` time so
neither a coding bug nor a hostile config can produce a transmissible artifact.
"""

from __future__ import annotations

import pytest

from wealthtax_agent.state import FilingArtifact, TransmissionBlockedError


def _base_kwargs() -> dict:
    return dict(
        jurisdiction="CA",
        form_code="T1",
        filename="ca_t1_2024_draft.pdf",
        mime_type="application/pdf",
        content_b64="ZmFrZQ==",
    )


def test_default_construction_is_non_transmissible() -> None:
    art = FilingArtifact(**_base_kwargs())
    assert art.transmissible is False


def test_transmissible_false_is_allowed() -> None:
    art = FilingArtifact(**_base_kwargs(), transmissible=False)
    assert art.transmissible is False


def test_transmissible_true_raises_at_construction() -> None:
    with pytest.raises(TransmissionBlockedError):
        FilingArtifact(**_base_kwargs(), transmissible=True)


def test_transmissible_true_via_setattr_raises() -> None:
    art = FilingArtifact(**_base_kwargs())
    with pytest.raises(TransmissionBlockedError):
        art.transmissible = True


def test_transmissible_true_via_model_copy_raises() -> None:
    art = FilingArtifact(**_base_kwargs())
    with pytest.raises(TransmissionBlockedError):
        art.model_copy(update={"transmissible": True})


def test_model_copy_without_flip_succeeds() -> None:
    art = FilingArtifact(**_base_kwargs())
    clone = art.model_copy(update={"form_code": "T1-XML"})
    assert clone.transmissible is False
    assert clone.form_code == "T1-XML"


def test_transmission_blocked_error_is_runtime_error() -> None:
    """Callers can catch the bad path with a broad ``except RuntimeError``."""

    assert issubclass(TransmissionBlockedError, RuntimeError)
