"""Branch coverage for db/repo.py persistence helpers.

Targets the uncovered branches in save_revision (the corrections loop),
latest_revision (no current revision), and consume_rate_token (bucket
exhausted). These are persistence-only paths — no tax math or filing.
"""

from datetime import datetime, timedelta

from wealthtax_agent.db import get_session
from wealthtax_agent.db.models import Correction, RateLimitBucket
from wealthtax_agent.db.repo import (
    consume_rate_token,
    create_user,
    latest_revision,
    list_revisions,
    save_revision,
    start_return,
)


def _new_return(email="branch@example.com"):
    with get_session() as s:
        user = create_user(s, email=email, hashed_password="h")
        ret = start_return(s, user_id=user.id, filing_year=2024, jurisdictions=["CA"])
        return user.id, ret.id


# ---------- save_revision: corrections loop persists Correction rows ----------

def test_save_revision_persists_corrections():
    uid, rid = _new_return("corr@example.com")
    with get_session() as s:
        rev = save_revision(
            s,
            user_id=uid,
            return_id=rid,
            state_json={"t": 100.0},
            summary_totals_json={"CA": {"total_tax": 100.0}},
            form_snapshots=[],
            corrections=[
                {
                    "kind": "chat",
                    "user_prompt": "add my RRSP",
                    "parsed_changes_json": [{"field": "rrsp", "value": 5000}],
                },
                {
                    "kind": "inline_edit",
                    "user_prompt": "fix box 14",
                    "parsed_changes_json": [{"field": "box14", "value": 42000}],
                },
            ],
        )
        rev_id = rev.id

    # Assert real persisted state: query the Correction rows back.
    with get_session() as s:
        rows = sorted(
            s.query(Correction).filter(Correction.revision_id == rev_id).all(),
            key=lambda c: c.kind,
        )
        assert [r.kind for r in rows] == ["chat", "inline_edit"]
        chat = next(r for r in rows if r.kind == "chat")
        assert chat.user_prompt == "add my RRSP"
        assert chat.parsed_changes_json == [{"field": "rrsp", "value": 5000}]
        assert chat.applied is True
        assert chat.reverted is False

    # And they hang off the revision relationship.
    with get_session() as s:
        revs = list_revisions(s, user_id=uid, return_id=rid)
        assert len(revs) == 1
        assert len(revs[0].corrections) == 2


def test_save_revision_no_corrections_persists_none():
    # The `corrections or []` default branch: None means no rows added.
    uid, rid = _new_return("nocorr@example.com")
    with get_session() as s:
        rev = save_revision(
            s,
            user_id=uid,
            return_id=rid,
            state_json={"t": 1.0},
            summary_totals_json={"CA": {"total_tax": 1.0}},
            form_snapshots=[],
        )
        rev_id = rev.id
    with get_session() as s:
        assert s.query(Correction).filter(Correction.revision_id == rev_id).count() == 0


# ---------- latest_revision: returns None with no current revision ----------

def test_latest_revision_none_when_no_revision_saved():
    uid, rid = _new_return("norev@example.com")
    with get_session() as s:
        # Freshly-started return: current_revision_id is None.
        assert latest_revision(s, user_id=uid, return_id=rid) is None


def test_latest_revision_none_for_unknown_return():
    uid, _ = _new_return("unknown@example.com")
    with get_session() as s:
        assert latest_revision(s, user_id=uid, return_id="does-not-exist") is None


# ---------- consume_rate_token: exhaustion (return False) and refill branches ----------

def test_consume_rate_token_returns_false_when_exhausted():
    uid, _ = _new_return("throttle@example.com")

    def consume(n):
        with get_session() as s:
            return consume_rate_token(s, user_id=uid, bucket="llm", max_per_minute=n)

    # Fresh bucket + remaining tokens are True; once exhausted (same minute), False.
    assert consume(3) is True   # fresh bucket path
    assert consume(3) is True
    assert consume(3) is True
    assert consume(3) is False  # exhausted -> return False
    assert consume(3) is False  # stays throttled


def test_consume_rate_token_refills_after_elapsed_time():
    # Covers the refill branch: when >= a minute has elapsed since last_refill,
    # tokens are topped back up and last_refill advances.
    uid, _ = _new_return("refill@example.com")

    def consume(n):
        with get_session() as s:
            return consume_rate_token(s, user_id=uid, bucket="llm", max_per_minute=n)

    # Drain a max_per_minute=2 bucket: fresh (True), second (True), throttled (False).
    assert consume(2) is True
    assert consume(2) is True
    assert consume(2) is False

    # Rewind last_refill 2 minutes into the past so elapsed >= 1 minute and
    # refill = int(2/60*60*... ) > 0, forcing the token top-up branch.
    with get_session() as s:
        row = s.get(RateLimitBucket, (uid, "llm"))
        assert row.tokens == 0
        row.last_refill = datetime.utcnow() - timedelta(minutes=2)

    # Next call takes the refill branch, tops tokens back to max,
    # then consumes one -> True again.
    assert consume(2) is True

    # Verify the refill actually happened: last_refill was advanced to ~now.
    with get_session() as s:
        row = s.get(RateLimitBucket, (uid, "llm"))
        assert (datetime.utcnow() - row.last_refill) < timedelta(seconds=30)
