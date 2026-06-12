"""Repo-level tests for the revision lifecycle, clarifications, and rate bucket.

Integration tests cover save_revision + user-scoping; these pin the
correctness-critical pieces that were only reached indirectly: monotonic
revision numbering across reverts, the current-revision pointer, revert
guards (unknown revision / foreign user), clarification upsert semantics,
and the per-session token-bucket throttle.
"""

from wealthtax_agent.db import get_session
from wealthtax_agent.db.repo import (
    consume_rate_token,
    create_user,
    get_clarification_answers,
    latest_revision,
    list_revisions,
    revert_to_revision,
    save_revision,
    start_return,
    upsert_clarification_answer,
)


def _new_return(email="rev@example.com"):
    with get_session() as s:
        user = create_user(s, email=email, hashed_password="h")
        ret = start_return(s, user_id=user.id, filing_year=2024, jurisdictions=["CA"])
        return user.id, ret.id


def _save(user_id, return_id, tax):
    with get_session() as s:
        save_revision(
            s,
            user_id=user_id,
            return_id=return_id,
            state_json={"t": tax},
            summary_totals_json={"CA": {"total_tax": tax}},
            form_snapshots=[],
        )


def test_save_revision_numbers_monotonically_and_sets_current():
    uid, rid = _new_return()
    _save(uid, rid, 100.0)
    _save(uid, rid, 200.0)
    with get_session() as s:
        assert [r.revision_number for r in list_revisions(s, user_id=uid, return_id=rid)] == [1, 2]
        cur = latest_revision(s, user_id=uid, return_id=rid)
        assert cur.revision_number == 2
        assert cur.summary_totals_json == {"CA": {"total_tax": 200.0}}


def test_revert_moves_current_pointer_to_prior_revision():
    uid, rid = _new_return()
    for t in (100.0, 200.0, 300.0):
        _save(uid, rid, t)
    with get_session() as s:
        target = revert_to_revision(s, user_id=uid, return_id=rid, revision_number=1)
        assert target is not None and target.revision_number == 1
    with get_session() as s:
        assert latest_revision(s, user_id=uid, return_id=rid).revision_number == 1


def test_new_revision_after_revert_continues_monotonic_numbering():
    uid, rid = _new_return()
    for t in (100.0, 200.0, 300.0):
        _save(uid, rid, t)
    with get_session() as s:
        revert_to_revision(s, user_id=uid, return_id=rid, revision_number=1)
    _save(uid, rid, 400.0)  # next number is 1 + len(history) = 4, not 2
    with get_session() as s:
        assert [r.revision_number for r in list_revisions(s, user_id=uid, return_id=rid)] == [1, 2, 3, 4]
        assert latest_revision(s, user_id=uid, return_id=rid).revision_number == 4


def test_revert_to_unknown_revision_returns_none():
    uid, rid = _new_return()
    _save(uid, rid, 100.0)
    with get_session() as s:
        assert revert_to_revision(s, user_id=uid, return_id=rid, revision_number=99) is None


def test_revert_for_foreign_user_returns_none_and_leaves_owner_pointer():
    uid, rid = _new_return("owner@example.com")
    _save(uid, rid, 100.0)
    _save(uid, rid, 200.0)
    with get_session() as s:
        intruder = create_user(s, email="intruder@example.com", hashed_password="h")
        intruder_id = intruder.id
    with get_session() as s:
        assert revert_to_revision(s, user_id=intruder_id, return_id=rid, revision_number=1) is None
        assert latest_revision(s, user_id=uid, return_id=rid).revision_number == 2


def test_list_revisions_empty_for_foreign_user():
    uid, rid = _new_return("a@example.com")
    _save(uid, rid, 100.0)
    with get_session() as s:
        other = create_user(s, email="b@example.com", hashed_password="h")
        other_id = other.id
    with get_session() as s:
        assert list_revisions(s, user_id=other_id, return_id=rid) == []


def test_clarification_answer_upsert_inserts_then_updates():
    uid, rid = _new_return("clar@example.com")
    with get_session() as s:
        upsert_clarification_answer(s, return_id=rid, question_id="q1", value="first")
    with get_session() as s:
        assert get_clarification_answers(s, return_id=rid) == {"q1": "first"}
    with get_session() as s:
        upsert_clarification_answer(s, return_id=rid, question_id="q1", value="second")
        upsert_clarification_answer(s, return_id=rid, question_id="q2", value="other")
    with get_session() as s:
        assert get_clarification_answers(s, return_id=rid) == {"q1": "second", "q2": "other"}


def test_consume_rate_token_allows_up_to_limit_then_throttles():
    # Mirrors real usage: one consume per committed session (per request).
    uid, _ = _new_return("rate@example.com")

    def consume():
        with get_session() as s:
            return consume_rate_token(s, user_id=uid, bucket="llm", max_per_minute=2)

    assert consume() is True   # fresh bucket
    assert consume() is True   # second token
    assert consume() is False  # exhausted within the same minute window
