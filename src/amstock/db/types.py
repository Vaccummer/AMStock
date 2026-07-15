"""Project-specific SQLAlchemy column types."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect


class ExactDecimal(TypeDecorator[Decimal]):
    """Store finite ``Decimal`` values as lossless canonical text."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        """Serialize without exponent notation or binary floating-point conversion."""

        del dialect
        if value is None:
            return None
        decimal = value if isinstance(value, Decimal) else Decimal(value)
        if decimal == 0:
            return "0"
        text = format(decimal, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    def process_result_value(self, value: str | None, dialect: Dialect) -> Decimal | None:
        """Restore the exact Python ``Decimal`` from persisted text."""

        del dialect
        return Decimal(value) if value is not None else None
