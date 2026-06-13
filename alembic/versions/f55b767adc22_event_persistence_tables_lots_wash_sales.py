"""event persistence tables (lots, wash_sales)

Creates the capital-gains / wash-sale tables that back the event consumer's
trade.filled persistence path. These tables live only in db/models.py (and
SQLite create_all for tests) — no prior Alembic migration created them, so on
Postgres ``alembic upgrade head`` ran the tax-engine migrations only and the
consumer's ``INSERT INTO lots`` failed with "relation lots does not exist".

``lots`` and ``wash_sales`` have mutually-referencing foreign keys
(lots.wash_sale_id -> wash_sales.id, and wash_sales.{sell,replacement}_lot_id
-> lots.id). On Postgres an inline FK to a not-yet-created table fails, so the
two tables are created first WITHOUT the cross-references and the cyclic FKs
are added afterwards with ``create_foreign_key``. (SQLite does not enforce
this ordering, which is why autogenerate against SQLite did not surface it.)

Revision ID: f55b767adc22
Revises: e2f8a9c1b3d4
Create Date: 2026-06-12 23:04:48.763077

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f55b767adc22"
down_revision = "e2f8a9c1b3d4"
branch_labels = None
depends_on = None


# Explicit names so the cyclic FKs can be dropped cleanly on downgrade.
_FK_LOTS_WASH_SALE = "fk_lots_wash_sale_id_wash_sales"
_FK_WS_SELL_LOT = "fk_wash_sales_sell_lot_id_lots"
_FK_WS_REPL_LOT = "fk_wash_sales_replacement_lot_id_lots"


def upgrade() -> None:
    # Idempotent guard: the consumer's _ensure_schema may race other runners,
    # and a prior partial apply should not wedge the upgrade.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # --- lots (cross-FK to wash_sales added later) ---
    if "lots" not in existing:
        op.create_table(
            "lots",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("return_id", sa.String(length=36), nullable=True),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("cusip", sa.String(length=12), nullable=True),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("side", sa.String(length=4), nullable=False),
            sa.Column("trade_date", sa.DateTime(), nullable=False),
            sa.Column("settle_date", sa.DateTime(), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("price", sa.Integer(), nullable=False),
            sa.Column("original_basis_cents", sa.Integer(), nullable=False),
            sa.Column("adjusted_basis_cents", sa.Integer(), nullable=True),
            sa.Column("is_wash_sale", sa.Boolean(), nullable=False),
            sa.Column("wash_sale_id", sa.String(length=36), nullable=True),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("source_ref", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["return_id"], ["tax_returns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_lots_return_id"), "lots", ["return_id"], unique=False)
        op.create_index(op.f("ix_lots_ticker"), "lots", ["ticker"], unique=False)
        op.create_index(op.f("ix_lots_user_id"), "lots", ["user_id"], unique=False)

    # --- wash_sales (cross-FK to lots added later) ---
    if "wash_sales" not in existing:
        op.create_table(
            "wash_sales",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("sell_date", sa.DateTime(), nullable=False),
            sa.Column("replacement_buy_date", sa.DateTime(), nullable=False),
            sa.Column("disallowed_loss_cents", sa.Integer(), nullable=False),
            sa.Column("basis_adjustment_cents", sa.Integer(), nullable=False),
            sa.Column("sell_lot_id", sa.String(length=36), nullable=True),
            sa.Column("replacement_lot_id", sa.String(length=36), nullable=True),
            sa.Column("irc_section", sa.String(length=16), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_wash_sales_ticker"), "wash_sales", ["ticker"], unique=False)
        op.create_index(op.f("ix_wash_sales_user_id"), "wash_sales", ["user_id"], unique=False)

    # --- cyclic FKs, now that both tables exist ---
    # SQLite cannot ALTER TABLE to add a FK; it doesn't enforce them here anyway,
    # so only emit these on backends that support it (e.g. Postgres).
    if bind.dialect.name != "sqlite":
        existing_fks_lots = {fk["name"] for fk in inspector.get_foreign_keys("lots")} if "lots" in existing else set()
        existing_fks_ws = {fk["name"] for fk in inspector.get_foreign_keys("wash_sales")} if "wash_sales" in existing else set()
        if _FK_LOTS_WASH_SALE not in existing_fks_lots:
            op.create_foreign_key(_FK_LOTS_WASH_SALE, "lots", "wash_sales", ["wash_sale_id"], ["id"])
        if _FK_WS_SELL_LOT not in existing_fks_ws:
            op.create_foreign_key(_FK_WS_SELL_LOT, "wash_sales", "lots", ["sell_lot_id"], ["id"])
        if _FK_WS_REPL_LOT not in existing_fks_ws:
            op.create_foreign_key(_FK_WS_REPL_LOT, "wash_sales", "lots", ["replacement_lot_id"], ["id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        # Drop the cyclic FKs first so the tables can be dropped in any order.
        op.drop_constraint(_FK_WS_REPL_LOT, "wash_sales", type_="foreignkey")
        op.drop_constraint(_FK_WS_SELL_LOT, "wash_sales", type_="foreignkey")
        op.drop_constraint(_FK_LOTS_WASH_SALE, "lots", type_="foreignkey")

    op.drop_index(op.f("ix_wash_sales_user_id"), table_name="wash_sales")
    op.drop_index(op.f("ix_wash_sales_ticker"), table_name="wash_sales")
    op.drop_table("wash_sales")
    op.drop_index(op.f("ix_lots_user_id"), table_name="lots")
    op.drop_index(op.f("ix_lots_ticker"), table_name="lots")
    op.drop_index(op.f("ix_lots_return_id"), table_name="lots")
    op.drop_table("lots")
