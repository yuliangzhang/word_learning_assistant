from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


@dataclass
class SRSState:
    last_review_at: str | None
    next_review_at: str | None
    ease: float = 2.5
    interval_days: int = 1
    streak: int = 0
    lapses: int = 0


@dataclass
class SRSUpdate:
    state: SRSState
    status: str


def next_state(previous: SRSState | None, passed: bool, now: datetime | None = None) -> SRSUpdate:
    now = now or datetime.now(UTC)
    state = previous or SRSState(last_review_at=None, next_review_at=now.isoformat())

    ease = state.ease
    interval = state.interval_days
    streak = state.streak
    lapses = state.lapses

    if passed:
        if streak <= 0:
            interval = 1
        elif streak == 1:
            interval = 3
        else:
            interval = max(1, round(interval * ease))
        ease = min(3.0, round(ease + 0.1, 2))
        streak += 1
    else:
        interval = 1
        ease = max(1.3, round(ease - 0.2, 2))
        streak = 0
        lapses += 1

    next_review_at = (now + timedelta(days=interval)).isoformat()
    status = derive_word_status(streak=streak, interval_days=interval, passed=passed)

    return SRSUpdate(
        state=SRSState(
            last_review_at=now.isoformat(),
            next_review_at=next_review_at,
            ease=ease,
            interval_days=interval,
            streak=streak,
            lapses=lapses,
        ),
        status=status,
    )


def derive_word_status(*, streak: int, interval_days: int, passed: bool) -> str:
    if not passed:
        return "LEARNING"
    if streak >= 5 and interval_days >= 14:
        return "MASTERED"
    if streak >= 2:
        return "REVIEWING"
    return "LEARNING"


def state_from_row(row: dict | None) -> SRSState | None:
    if row is None:
        return None
    return SRSState(
        last_review_at=row.get("last_review_at"),
        next_review_at=row.get("next_review_at"),
        ease=float(row.get("ease", 2.5)),
        interval_days=int(row.get("interval_days", 1)),
        streak=int(row.get("streak", 0)),
        lapses=int(row.get("lapses", 0)),
    )
