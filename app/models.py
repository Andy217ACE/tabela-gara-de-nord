# © 2026 Andy217Ace
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    board: str
    train_type: str
    train_no: int
    station: str
    operator: str
    sched_time: str
    delay_min: int = 0
    platform: int | None = None
    flagged: bool = False
    confidence: float = 1.0
    operator_raw: str = ""  # text as read by OCR (operator/station hold canonical names)
    station_raw: str = ""
    uncertain: bool = False  # operator or station did not match a known name
    delay_read: bool = True  # False: the delay cell was unreadable (delay_min is not a reading)

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.board, self.train_no, self.sched_time)


@dataclass(frozen=True)
class Event:
    kind: str  # delay | platform | appeared | gone
    row: Row
    old: str | None
    new: str | None
    service_date: str | None = None  # ISO date of the service (set by the store)
