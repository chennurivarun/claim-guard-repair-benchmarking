"""SQLite-safe scalar types for exact money and UTC timestamps."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    """Return an aware UTC timestamp for SQLAlchemy defaults."""

    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Persist UTC timestamps and always return timezone-aware values."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        value = value.astimezone(UTC)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class DecimalString(TypeDecorator):
    """Store a finite decimal as canonical text, never SQLite REAL.

    The Python-facing value is also a string. That keeps API/database boundaries
    explicit and prevents accidental binary-float arithmetic in persistence code.
    """

    impl = String
    cache_ok = True

    def __init__(self, scale: int = 2, max_digits: int = 20) -> None:
        if scale < 0 or max_digits <= scale:
            raise ValueError("max_digits must be greater than a non-negative scale")
        self.scale = scale
        self.max_digits = max_digits
        super().__init__(length=max_digits + 3)

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        try:
            decimal_value = Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid decimal value: {value!r}") from exc
        if not decimal_value.is_finite():
            raise ValueError("decimal values must be finite")

        quantum = Decimal(1).scaleb(-self.scale)
        try:
            decimal_value = decimal_value.quantize(quantum, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise ValueError(f"decimal value exceeds supported precision: {value!r}") from exc

        digits = decimal_value.as_tuple().digits
        if len(digits) > self.max_digits:
            raise ValueError(f"decimal value exceeds {self.max_digits} digits")
        return format(decimal_value, f".{self.scale}f")

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return str(value)


MoneyString = DecimalString(scale=2, max_digits=20)
QuantityString = DecimalString(scale=4, max_digits=20)
RateString = DecimalString(scale=4, max_digits=20)
WeightString = DecimalString(scale=6, max_digits=20)
