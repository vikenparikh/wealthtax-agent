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
