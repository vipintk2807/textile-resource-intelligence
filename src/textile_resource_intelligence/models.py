"""SQLAlchemy 2.0 table definitions.

Quantities are stored as exact decimal text (``DecimalText``), never as floats, so a
value such as 0.1 round-trips without binary rounding error.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .domain.numbers import decimal_to_text


class DecimalText(TypeDecorator):
    """Store ``Decimal`` as canonical plain text and read it back as ``Decimal``."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return decimal_to_text(value if isinstance(value, Decimal) else Decimal(str(value)))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # naive UTC, documented in the README


class Base(DeclarativeBase):
    pass


class CategoryRow(Base):
    __tablename__ = "resource_categories"
    __table_args__ = (
        CheckConstraint(
            "resource_type IN ('electricity','water','chemicals','steam','fuel','waste','other')",
            name="ck_category_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    default_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    allowed_units: Mapped[str] = mapped_column(String(200), nullable=False)  # comma-separated codes
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class ResourceRecordRow(Base):
    __tablename__ = "resource_records"
    __table_args__ = (
        CheckConstraint("record_type = 'interval_consumption'", name="ck_resource_record_type"),
        CheckConstraint("source_type IN ('manual','import','demo')", name="ck_resource_source"),
        CheckConstraint("period_end IS NULL OR period_end >= period_start", name="ck_resource_period"),
        CheckConstraint("CAST(quantity AS REAL) >= 0", name="ck_resource_quantity"),
        Index("ix_resource_records_period", "period_start"),
        Index("ix_resource_records_category", "resource_category_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_category_id: Mapped[int] = mapped_column(
        ForeignKey("resource_categories.id", ondelete="RESTRICT"), nullable=False
    )
    record_type: Mapped[str] = mapped_column(String(30), nullable=False, default="interval_consumption")
    quantity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)  # NULL = single date
    scope_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class ProductionRecordRow(Base):
    __tablename__ = "production_records"
    __table_args__ = (
        CheckConstraint("source_type IN ('manual','import','demo')", name="ck_production_source"),
        CheckConstraint("period_end IS NULL OR period_end >= period_start", name="ck_production_period"),
        CheckConstraint("CAST(quantity AS REAL) >= 0", name="ck_production_quantity"),
        Index("ix_production_records_period", "period_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    scope_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class PreferenceRow(Base):
    __tablename__ = "app_preferences"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
