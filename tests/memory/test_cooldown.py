from __future__ import annotations

from datetime import datetime, timedelta

from app.pipelines.memory import MemoryStore, should_notify
from app.schemas import Alert, Level

NOW = datetime(2026, 11, 7, 12, 0, 0)


def _alert(alert_id: str, level: Level, minutes_ago: int, session_id: str = "s1") -> Alert:
    created = NOW - timedelta(minutes=minutes_ago)
    return Alert(
        id=alert_id,
        session_id=session_id,
        score=90.0,
        level=level,
        created_at=created.isoformat(timespec="seconds"),
    )


def test_same_level_within_30_minutes_is_suppressed(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.record_alert(_alert("A1", Level.L2, 10))

    allowed, reason = should_notify(store, "s1", Level.L2, now=NOW)

    assert allowed is False
    assert "不重复打扰" in reason
    assert "L2 警告" in reason


def test_higher_recent_level_also_suppresses(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.record_alert(_alert("A1", Level.L3, 5))

    allowed, _ = should_notify(store, "s1", Level.L2, now=NOW)

    assert allowed is False


def test_lower_recent_level_does_not_suppress(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.record_alert(_alert("A1", Level.L1, 5))

    allowed, reason = should_notify(store, "s1", Level.L2, now=NOW)

    assert allowed is True
    assert "允许推送" in reason


def test_alert_outside_window_does_not_suppress(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.record_alert(_alert("A1", Level.L3, 40))

    allowed, _ = should_notify(store, "s1", Level.L2, now=NOW)

    assert allowed is True


def test_other_session_does_not_suppress(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.record_alert(_alert("A1", Level.L3, 5, session_id="s2"))

    allowed, _ = should_notify(store, "s1", Level.L3, now=NOW)

    assert allowed is True


def test_l0_never_notifies(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")

    allowed, reason = should_notify(store, "s1", Level.L0, now=NOW)

    assert allowed is True
    assert "L0" in reason
