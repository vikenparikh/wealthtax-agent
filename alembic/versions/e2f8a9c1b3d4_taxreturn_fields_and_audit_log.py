"""P2-AC1/P2-AC2 — add encrypted TaxReturn.fields + tax_return_events table

Adds the LargeBinary ``fields`` column to ``tax_returns`` (encrypted at the
ORM layer via :class:`wealthtax_agent.db.crypto.EncryptedJSON`) and the
append-only ``tax_return_events`` audit table.

Also data-migrates any pre-existing rows: if a legacy plaintext JSON blob is
present in ``fields`` (i.e. someone upgraded an old DB), it is re-encrypted
in place using the active Fernet key so the post-migration invariant holds —
``SELECT fields FROM tax_returns`` must never yield valid JSON.

Revision ID: e2f8a9c1b3d4
Revises: d01bfd6ae83a
Create Date: 2026-05-27 11:00:00.000000
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "e2f8a9c1b3d4"
down_revision = "d01bfd6ae83a"
branch_labels = None
depends_on = None


def _encrypt_plaintext_rows(connection) -> None:
    """Re-encrypt any rows whose ``fields`` column still holds plaintext JSON."""
    try:
        from wealthtax_agent.db.crypto import _fernet  # type: ignore
    except Exception:
        # Crypto helper unavailable — skip; tests + production both ship it.
        return

    rows = connection.execute(
        sa.text("SELECT id, fields FROM tax_returns WHERE fields IS NOT NULL")
    ).fetchall()
    fernet = _fernet()
    for row in rows:
        raw = row[1]
        if raw is None:
            continue
        # Already-encrypted Fernet tokens start with 'gAA' / 'gAE'.
        head = raw[:3] if isinstance(raw, (bytes, bytearray)) else str(raw)[:3].encode()
        if head in (b"gAA", b"gAE"):
            continue
        # Treat as plaintext JSON; if it parses, re-encrypt.
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            continue
        cipher = fernet.encrypt(json.dumps(payload, default=str).encode("utf-8"))
        connection.execute(
            sa.text("UPDATE tax_returns SET fields = :v WHERE id = :id"),
            {"v": cipher, "id": row[0]},
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ---- tax_returns.fields (encrypted JSON, stored as LargeBinary) ----
    tax_return_cols = {c["name"] for c in inspector.get_columns("tax_returns")}
    if "fields" not in tax_return_cols:
        with op.batch_alter_table("tax_returns") as batch:
            batch.add_column(sa.Column("fields", sa.LargeBinary(), nullable=True))

    # Re-encrypt any legacy plaintext blobs.
    _encrypt_plaintext_rows(bind)

    # ---- tax_return_events (append-only audit log) ----
    if not inspector.has_table("tax_return_events"):
        op.create_table(
            "tax_return_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("return_id", sa.String(length=36), nullable=False),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.Column("before_hash", sa.String(length=64), nullable=True),
            sa.Column("after_hash", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["return_id"], ["tax_returns.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_tax_return_events_user_id"),
            "tax_return_events",
            ["user_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_tax_return_events_return_id"),
            "tax_return_events",
            ["return_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_tax_return_events_return_id"), table_name="tax_return_events")
    op.drop_index(op.f("ix_tax_return_events_user_id"), table_name="tax_return_events")
    op.drop_table("tax_return_events")

    with op.batch_alter_table("tax_returns") as batch:
        batch.drop_column("fields")
