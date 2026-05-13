"""Clock and epoch helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    """Provides epoch timestamps for services."""

    def now_epoch(self) -> int:
        """Return the current Unix epoch timestamp in seconds."""


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Clock implementation backed by the system time."""

    def now_epoch(self) -> int:
        """Return the current Unix epoch timestamp in seconds."""

        return int(datetime.now(tz=UTC).timestamp())


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Clock useful for deterministic tests."""

    epoch: int

    def now_epoch(self) -> int:
        """Return the fixed Unix epoch timestamp in seconds."""

        return self.epoch


def epoch_to_datetime(epoch: int, timezone: str) -> datetime:
    """Convert an epoch timestamp to an aware datetime in the requested timezone."""

    return datetime.fromtimestamp(epoch, ZoneInfo(timezone))


def datetime_to_epoch(value: datetime, timezone: str) -> int:
    """Convert a datetime to an epoch timestamp using the requested timezone if needed."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(timezone))
    return int(value.timestamp())
