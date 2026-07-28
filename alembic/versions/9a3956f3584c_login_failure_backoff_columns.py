"""login-failure backoff columns on users (delay-not-lockout)

Adds the two bookkeeping columns that back the email-scoped brute-force
backoff in ``auth.login``:

  - ``failed_login_count``     INTEGER  NOT NULL DEFAULT 0
  - ``last_failed_login_at``   DATETIME NULL

These only ever gate the *failed* login path with a capped, exponential
"try again in Ns" response; a correct password always succeeds and resets the
counter (see ``auth.login`` / ``db.repo.reset_failed_logins``). No data
migration is needed — existing users default to 0 failures.

The upgrade is idempotent (guards on column existence) so a partial/re-run
apply does not wedge, matching the guard style used in the prior migration
(``f55b767adc22``).

Revision ID: 9a3956f3584c
Revises: f55b767adc22
Create Date: 2026-07-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9a3956f3584c"
down_revision = "f55b767adc22"
branch_labels = None
depends_on = None


def _user_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns("users")}


def upgrade() -> None:
    cols = _user_columns()
    if "failed_login_count" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "failed_login_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    if "last_failed_login_at" not in cols:
        op.add_column(
            "users",
            sa.Column("last_failed_login_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    cols = _user_columns()
    if "last_failed_login_at" in cols:
        op.drop_column("users", "last_failed_login_at")
    if "failed_login_count" in cols:
        op.drop_column("users", "failed_login_count")
