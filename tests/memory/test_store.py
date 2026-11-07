from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from app.pipelines.memory import SUMMARY_MAX_CHARS, MemoryStore
from app.schemas import Alert, Level, SourceKind

NOW = datetime(2026, 11, 7, 12, 0, 0)


def _alert(alert_id: str, level: Level, session_id: str = "s1", created_at: datetime | None = None):
    return Alert(
        id=alert_id,
        session_id=session_id,
        score=90.0,
        level=level,
        script_name="冒充公检法诈骗",
        created_at=(created_at or NOW).isoformat(timespec="seconds"),
    )


def test_schema_creates_three_tables(tmp_path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    MemoryStore(db_path).close()

    with sqlite3.connect(db_path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert {"sessions", "messages", "alerts"} <= names


def test_recent_summary_uses_last_five_turns_only(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    for index in range(7):
        store.record_turn("s1", f"第{index}轮：对方让我转账", role="elder")

    summary = store.recent_summary("s1")

    assert store.turn_count("s1") == 7
    assert "第6轮" in summary
    assert "第2轮" in summary
    assert "第1轮" not in summary
    assert len(summary) <= SUMMARY_MAX_CHARS


def test_long_summary_is_capped_at_200_chars(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    for index in range(5):
        store.record_turn("s1", f"第{index}轮：" + "对" * 100)

    summary = store.recent_summary("s1")

    assert len(summary) <= 200
    assert summary.endswith("…")


def test_restart_keeps_history(tmp_path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    first = MemoryStore(db_path)
    first.record_turn("s1", "我是公检法的，请把钱转到安全账户", role="elder")
    first.record_alert(_alert("A1", Level.L3))
    first.close()

    second = MemoryStore(db_path)

    assert second.turn_count("s1") == 1
    assert "安全账户" in second.recent_summary("s1")
    assert second.alert_count() == 1
    assert second.recent_alerts("s1", now=NOW)[0]["alert_id"] == "A1"


def test_context_evidence_wraps_summary(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    assert store.context_evidence("empty") is None

    for index in range(3):
        store.record_turn("s1", f"第{index}轮", role="normal")
    evidence = store.context_evidence("s1")

    assert evidence is not None
    assert evidence.kind == SourceKind.CONTEXT
    assert evidence.text == store.recent_summary("s1")
    assert evidence.meta["turns"] == 3


def test_record_alert_and_ack(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.record_turn("s1", "疑似诈骗", role="elder")
    store.record_alert(_alert("A1", Level.L3))

    recent = store.recent_alerts("s1", min_level=Level.L2, now=NOW)
    assert len(recent) == 1
    assert recent[0]["level"] == 3
    assert recent[0]["status"] == "open"

    assert store.record_ack("A1", "acked", now=NOW.isoformat(timespec="seconds")) is True
    assert store.recent_alerts("s1", now=NOW)[0]["status"] == "acked"
    assert store.record_ack("A-missing") is False


def test_alert_count_filters_by_role(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.record_turn("s1", "a", role="elder")
    store.record_turn("s2", "b", role="normal")
    store.record_alert(_alert("A1", Level.L3, session_id="s2"))
    store.record_alert(_alert("A2", Level.L2, session_id="s2"))

    assert store.alert_count() == 2
    assert store.alert_count(role="elder") == 0
    assert store.alert_count(role="normal") == 2
    assert store.alert_count(session_id="s2") == 2


def test_recent_alerts_filters_window_and_level(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.record_alert(_alert("A1", Level.L3, created_at=NOW))
    store.record_alert(_alert("A2", Level.L2, created_at=NOW - timedelta(minutes=10)))
    store.record_alert(_alert("A3", Level.L3, created_at=NOW - timedelta(minutes=40)))

    assert [row["alert_id"] for row in store.recent_alerts("s1", min_level=Level.L2, now=NOW)] == [
        "A1",
        "A2",
    ]
    assert [row["alert_id"] for row in store.recent_alerts("s1", min_level=Level.L3, now=NOW)] == [
        "A1"
    ]
