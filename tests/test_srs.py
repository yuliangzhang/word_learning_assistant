from __future__ import annotations

from datetime import datetime, timezone

from word_assistance.scheduler.srs import SRSState, next_state

UTC = timezone.utc


def test_srs_pass_then_expand_interval():
    now = datetime(2026, 2, 12, tzinfo=UTC)
    first = next_state(None, passed=True, now=now)
    second = next_state(first.state, passed=True, now=now)

    assert first.state.interval_days == 1
    assert second.state.interval_days == 3
    assert second.status == "REVIEWING"


def test_srs_fail_resets_interval_and_increases_lapses():
    now = datetime(2026, 2, 12, tzinfo=UTC)
    previous = SRSState(
        last_review_at=now.isoformat(),
        next_review_at=now.isoformat(),
        ease=2.6,
        interval_days=5,
        streak=3,
        lapses=1,
    )

    failed = next_state(previous, passed=False, now=now)

    assert failed.state.interval_days == 1
    assert failed.state.streak == 0
    assert failed.state.lapses == 2
    assert failed.status == "LEARNING"
