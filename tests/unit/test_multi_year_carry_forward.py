"""P2-AC4 — multi-year carry-forward defaults.

Verifies that ``load_prior_year_defaults(user_id, year - 1)`` returns a dict
containing ``rrsp_room``, ``capital_loss_carryforward``, and
``foreign_tax_credits`` pulled from the previous year's :class:`TaxReturn`,
and that the wizard pre-fill helper does not overwrite values the user has
already typed.
"""

from __future__ import annotations

import pytest

from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, get_session, reset_engine_cache
from wealthtax_agent.db.models import TaxReturn, User
from wealthtax_agent.services.prior_year import (
    CARRY_FORWARD_KEYS,
    load_prior_year_defaults,
    prefill_wizard_data,
)

_FERNET_KEY = "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("WEALTHTAX_FERNET_KEY", _FERNET_KEY)
    reset_settings_cache()
    reset_engine_cache()
    create_all_for_tests()
    yield
    reset_engine_cache()
    reset_settings_cache()


def _make_user(session, email: str = "py-test@example.com") -> User:
    u = User(
        email=email,
        hashed_password="$2b$12$fakehashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    )
    session.add(u)
    session.flush()
    return u


def _save_prior_return(*, user_id: str, year: int, fields: dict) -> None:
    with get_session() as session:
        tr = TaxReturn(
            user_id=user_id,
            filing_year=year,
            jurisdictions_json=["CA"],
            fields=fields,
        )
        session.add(tr)


# ---------------------------------------------------------------------------
# Contract — load_prior_year_defaults
# ---------------------------------------------------------------------------


def test_returns_zero_dict_when_no_prior_return_exists():
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
    defaults = load_prior_year_defaults(user_id, 2023)
    assert set(defaults.keys()) >= set(CARRY_FORWARD_KEYS)
    for key in CARRY_FORWARD_KEYS:
        assert defaults[key] == 0.0


def test_pulls_top_level_carryforward_fields_from_prior_return():
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
    _save_prior_return(
        user_id=user_id,
        year=2023,
        fields={
            "rrsp_room": 17_500.0,
            "capital_loss_carryforward": 4_200.0,
            "foreign_tax_credits": 950.0,
            "other_noise": "ignored",
        },
    )
    defaults = load_prior_year_defaults(user_id, 2023)
    assert defaults["rrsp_room"] == 17_500.0
    assert defaults["capital_loss_carryforward"] == 4_200.0
    assert defaults["foreign_tax_credits"] == 950.0


def test_accepts_alternate_field_names_in_user_answers_scope():
    """Older draft data stored answers under ``user_answers`` w/ different keys."""
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
    _save_prior_return(
        user_id=user_id,
        year=2023,
        fields={
            "user_answers": {
                "rrsp_room_remaining": 12_000.0,
                "net_capital_loss_carryforward": 800.0,
                "ftc_carryforward": 150.0,
            }
        },
    )
    defaults = load_prior_year_defaults(user_id, 2023)
    assert defaults["rrsp_room"] == 12_000.0
    assert defaults["capital_loss_carryforward"] == 800.0
    assert defaults["foreign_tax_credits"] == 150.0


def test_accepts_values_under_wizard_data_scope():
    """Values stored from in-wizard saves live under ``wizard_data``."""
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
    _save_prior_return(
        user_id=user_id,
        year=2023,
        fields={"wizard_data": {"rrsp_room": 9_000.0}},
    )
    defaults = load_prior_year_defaults(user_id, 2023)
    assert defaults["rrsp_room"] == 9_000.0
    assert defaults["capital_loss_carryforward"] == 0.0
    assert defaults["foreign_tax_credits"] == 0.0


def test_coerces_string_amounts_to_float():
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
    _save_prior_return(
        user_id=user_id,
        year=2023,
        fields={"rrsp_room": "1234.50", "foreign_tax_credits": "75"},
    )
    defaults = load_prior_year_defaults(user_id, 2023)
    assert defaults["rrsp_room"] == 1234.5
    assert defaults["foreign_tax_credits"] == 75.0


def test_picks_most_recently_updated_prior_return():
    """If the user has multiple drafts for the same year, the latest wins."""
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
    _save_prior_return(
        user_id=user_id,
        year=2023,
        fields={"rrsp_room": 100.0},
    )
    _save_prior_return(
        user_id=user_id,
        year=2023,
        fields={"rrsp_room": 200.0},
    )
    defaults = load_prior_year_defaults(user_id, 2023)
    # The latest (200.0) write must win.
    assert defaults["rrsp_room"] == 200.0


def test_different_users_do_not_share_carry_forwards():
    with get_session() as session:
        user_a = _make_user(session, email="a@example.com")
        user_b = _make_user(session, email="b@example.com")
        a_id, b_id = user_a.id, user_b.id
    _save_prior_return(user_id=a_id, year=2023, fields={"rrsp_room": 5_000.0})
    defaults_b = load_prior_year_defaults(b_id, 2023)
    assert defaults_b["rrsp_room"] == 0.0


# ---------------------------------------------------------------------------
# Contract — prefill_wizard_data must not overwrite user-typed values
# ---------------------------------------------------------------------------


def test_prefill_pulls_defaults_into_empty_wizard_data():
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
    _save_prior_return(
        user_id=user_id,
        year=2023,
        fields={"rrsp_room": 11_000.0, "capital_loss_carryforward": 2_500.0},
    )
    merged = prefill_wizard_data(
        current_wizard_data={},
        user_id=user_id,
        filing_year=2024,  # service queries year - 1 = 2023
    )
    assert merged["rrsp_room"] == 11_000.0
    assert merged["capital_loss_carryforward"] == 2_500.0
    assert merged["foreign_tax_credits"] == 0.0


def test_prefill_does_not_overwrite_user_typed_fields():
    """If the user has already typed an rrsp_room, the prior-year default loses."""
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
    _save_prior_return(
        user_id=user_id,
        year=2023,
        fields={"rrsp_room": 11_000.0, "capital_loss_carryforward": 2_500.0},
    )
    merged = prefill_wizard_data(
        current_wizard_data={"rrsp_room": 22_222.22},  # user has already typed
        user_id=user_id,
        filing_year=2024,
    )
    assert merged["rrsp_room"] == 22_222.22  # user value preserved
    assert merged["capital_loss_carryforward"] == 2_500.0  # gap filled


def test_prefill_returns_a_new_dict_and_does_not_mutate_input():
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
    _save_prior_return(
        user_id=user_id,
        year=2023,
        fields={"rrsp_room": 500.0},
    )
    original = {"rrsp_room": 0.0}
    merged = prefill_wizard_data(
        current_wizard_data=original,
        user_id=user_id,
        filing_year=2024,
    )
    assert original == {"rrsp_room": 0.0}, "input dict must not be mutated"
    assert merged is not original
    assert merged["rrsp_room"] == 500.0
