from wealthtax_agent.db import get_session
from wealthtax_agent.db.crypto import decrypt, encrypt
from wealthtax_agent.db.repo import (
    create_user,
    get_user_by_email,
    list_user_returns,
    save_revision,
    start_return,
)


def test_user_create_and_lookup_with_encrypted_name():
    with get_session() as s:
        user = create_user(s, email="user@example.com", hashed_password="hash", full_name_enc=encrypt("Jane Doe"))
        user_id = user.id

    with get_session() as s:
        fetched = get_user_by_email(s, "user@example.com")
        assert fetched is not None
        assert fetched.id == user_id
        assert decrypt(fetched.full_name_enc) == "Jane Doe"


def test_return_revision_save_and_list():
    with get_session() as s:
        user = create_user(s, email="rs@example.com", hashed_password="hash")
        ret = start_return(s, user_id=user.id, filing_year=2024, jurisdictions=["CA"])
        user_id, return_id = user.id, ret.id

    with get_session() as s:
        save_revision(
            s,
            user_id=user_id,
            return_id=return_id,
            state_json={"filing_year": 2024},
            summary_totals_json={"CA": {"total_tax": 12000.0}},
            form_snapshots=[
                {"form_code": "T4", "jurisdiction": "CA", "fields_json": {"employment_income": 80000.0}, "source": "upload", "source_filename": "t4.pdf"},
            ],
        )

    with get_session() as s:
        returns = list_user_returns(s, user_id)
        assert len(returns) == 1
        ret = returns[0]
        assert ret.current_revision_id is not None
        assert len(ret.revisions) == 1
        assert ret.revisions[0].revision_number == 1
        assert ret.revisions[0].summary_totals_json["CA"]["total_tax"] == 12000.0
        assert len(ret.revisions[0].form_snapshots) == 1
