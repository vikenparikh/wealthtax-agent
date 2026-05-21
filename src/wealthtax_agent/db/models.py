"""SQLAlchemy ORM models for the multi-user data layer.

Schema is intentionally portable between SQLite (dev) and Postgres (prod):
JSON payloads use the ``JSON`` type which both engines support; PII is
encrypted on write via the helpers in ``crypto.py`` and stored as ``LargeBinary``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from wealthtax_agent.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(320), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    # Encrypted PII columns. Stored ciphertext only.
    full_name_enc = Column(LargeBinary, nullable=True)
    sin_or_ssn_enc = Column(LargeBinary, nullable=True)
    dob_enc = Column(LargeBinary, nullable=True)
    address_enc = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)

    returns = relationship("TaxReturn", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User", back_populates="sessions")


class TaxReturn(Base):
    __tablename__ = "tax_returns"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filing_year = Column(Integer, nullable=False)
    jurisdictions_json = Column(JSON, nullable=False, default=list)
    status = Column(String(32), nullable=False, default="draft")
    current_revision_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="returns")
    revisions = relationship("ReturnRevision", back_populates="tax_return", cascade="all, delete-orphan",
                             foreign_keys="ReturnRevision.return_id")
    clarification_answers = relationship("ClarificationAnswer", back_populates="tax_return", cascade="all, delete-orphan")


class ReturnRevision(Base):
    __tablename__ = "return_revisions"

    id = Column(String(36), primary_key=True, default=_uuid)
    return_id = Column(String(36), ForeignKey("tax_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_number = Column(Integer, nullable=False)
    state_json = Column(JSON, nullable=False)
    summary_totals_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tax_return = relationship("TaxReturn", back_populates="revisions", foreign_keys=[return_id])
    form_snapshots = relationship("FormSnapshot", back_populates="revision", cascade="all, delete-orphan")
    corrections = relationship("Correction", back_populates="revision", cascade="all, delete-orphan")


class FormSnapshot(Base):
    __tablename__ = "form_snapshots"

    id = Column(String(36), primary_key=True, default=_uuid)
    revision_id = Column(String(36), ForeignKey("return_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    form_code = Column(String(32), nullable=False)
    jurisdiction = Column(String(8), nullable=False)
    fields_json = Column(JSON, nullable=False)
    source = Column(String(16), nullable=False, default="upload")  # upload | manual | correction
    source_filename = Column(String(255), nullable=True)

    revision = relationship("ReturnRevision", back_populates="form_snapshots")


class Correction(Base):
    __tablename__ = "corrections"

    id = Column(String(36), primary_key=True, default=_uuid)
    revision_id = Column(String(36), ForeignKey("return_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False)  # chat | inline_edit | add_form | remove_form
    user_prompt = Column(Text, nullable=True)
    parsed_changes_json = Column(JSON, nullable=False, default=list)
    applied = Column(Boolean, default=True, nullable=False)
    reverted = Column(Boolean, default=False, nullable=False)
    low_confidence = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    revision = relationship("ReturnRevision", back_populates="corrections")


class ClarificationAnswer(Base):
    __tablename__ = "clarification_answers"

    id = Column(String(36), primary_key=True, default=_uuid)
    return_id = Column(String(36), ForeignKey("tax_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(String(64), nullable=False)
    value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tax_return = relationship("TaxReturn", back_populates="clarification_answers")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    return_id = Column(String(36), ForeignKey("tax_returns.id", ondelete="CASCADE"), nullable=True, index=True)
    action = Column(String(64), nullable=False)
    payload_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RateLimitBucket(Base):
    """Per-user token bucket used to throttle correction-loop LLM calls."""

    __tablename__ = "rate_limit_buckets"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    bucket = Column(String(64), primary_key=True)
    tokens = Column(Integer, nullable=False, default=0)
    last_refill = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Capital-gains tracking (C2 / C3)
# ---------------------------------------------------------------------------

class Lot(Base):
    """One buy or sell transaction for capital-gains and wash-sale tracking.

    Both acquisitions (buy) and dispositions (sell) are rows here; the
    ``side`` column distinguishes them.  Wash-sale adjustments write back to
    ``adjusted_basis``.
    """

    __tablename__ = "lots"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    return_id = Column(String(36), ForeignKey("tax_returns.id", ondelete="CASCADE"), nullable=True, index=True)

    # Security identity
    ticker = Column(String(16), nullable=False, index=True)
    cusip = Column(String(12), nullable=True)    # for "substantially identical" matching
    description = Column(String(255), nullable=True)

    # Transaction
    side = Column(String(4), nullable=False)     # "buy" | "sell"
    trade_date = Column(DateTime, nullable=False)
    settle_date = Column(DateTime, nullable=True)
    quantity = Column(Integer, nullable=False)   # shares / contracts
    price = Column(Integer, nullable=False)      # cents — avoids float rounding

    # Basis tracking
    original_basis_cents = Column(Integer, nullable=False)   # total cost (cents)
    adjusted_basis_cents = Column(Integer, nullable=True)    # after wash-sale add-back

    # Wash-sale flag
    is_wash_sale = Column(Boolean, default=False, nullable=False)
    wash_sale_id = Column(String(36), ForeignKey("wash_sales.id"), nullable=True)

    # Source: "upload" = from a 1099-B parser, "trad_audit" = imported from Trad-Platform
    source = Column(String(16), nullable=False, default="upload")
    source_ref = Column(String(255), nullable=True)   # e.g. audit.sqlite row id

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    wash_sale = relationship("WashSale", foreign_keys=[wash_sale_id], back_populates="disallowed_lot")


class WashSale(Base):
    """One wash-sale rule application (IRS §1091).

    Links the disallowed sell lot and the replacement buy lot.  The
    ``disallowed_loss_cents`` is added back to the replacement lot's basis.
    """

    __tablename__ = "wash_sales"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    ticker = Column(String(16), nullable=False, index=True)
    sell_date = Column(DateTime, nullable=False)
    replacement_buy_date = Column(DateTime, nullable=False)

    # Loss that was disallowed on the sell lot (cents, positive)
    disallowed_loss_cents = Column(Integer, nullable=False)
    # Basis add-back applied to the replacement lot (cents, positive)
    basis_adjustment_cents = Column(Integer, nullable=False)

    # FK back to Lot rows (nullable so schema can be created before lots exist)
    sell_lot_id = Column(String(36), ForeignKey("lots.id"), nullable=True)
    replacement_lot_id = Column(String(36), ForeignKey("lots.id"), nullable=True)

    irc_section = Column(String(16), nullable=False, default="§1091")
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    disallowed_lot = relationship("Lot", foreign_keys="[Lot.wash_sale_id]", back_populates="wash_sale")
