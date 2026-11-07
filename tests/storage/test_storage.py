"""运行时库：建表、会话、消息、告警、重启后仍在。"""

from __future__ import annotations

from app.pipelines.storage import SCHEMA_VERSION, Storage
from app.schemas import Alert, AlertStatus, Level


def _db(tmp_path) -> Storage:
    return Storage(path=tmp_path / "app.db")


def test_init_is_idempotent_and_records_version(tmp_path):
    db = _db(tmp_path)
    db.init_db()  # 再跑一次不许报错
    with db._connect() as conn:  # noqa: SLF001 —— 测试直接看表
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
    assert {"sessions", "messages", "alerts", "meta"} <= tables
    assert version == str(SCHEMA_VERSION)


def test_session_roundtrip(tmp_path):
    db = _db(tmp_path)
    db.save_session(
        "s_1",
        role="elder",
        turns=2,
        texts=["第一句", "第二句"],
        evidence=[{"code": "authority", "label": "冒充身份", "category": "text", "text": "我是公安"}],
        notifications=[{"channel": "webhook", "status": "skipped"}],
        last_decision={"score": 87.3, "level": 3, "reasons": ["要求转账"]},
    )
    record = db.load_session("s_1")
    assert record is not None
    assert record.role == "elder"
    assert record.turns == 2
    assert record.texts == ["第一句", "第二句"]
    assert record.last_decision["score"] == 87.3


def test_session_survives_new_instance(tmp_path):
    _db(tmp_path).save_session(
        "s_2",
        role="student",
        turns=1,
        texts=["把钱转到安全账户"],
        evidence=[],
        notifications=[],
        last_decision={"score": 70.0, "level": 2},
    )
    reopened = Storage(path=tmp_path / "app.db")
    record = reopened.load_session("s_2")
    assert record is not None and record.turns == 1
    assert reopened.load_session("不存在") is None


def test_messages_append_in_order(tmp_path):
    db = _db(tmp_path)
    for i in range(3):
        db.append_message("s_3", text=f"第{i}条", level=i, score=float(i))
    rows = db.list_messages("s_3")
    assert [row["text"] for row in rows] == ["第0条", "第1条", "第2条"]
    assert db.count_messages("s_3") == 3
    assert db.count_messages() == 3


def test_alert_save_and_status_update(tmp_path):
    db = _db(tmp_path)
    alert = Alert(
        id="A0001",
        session_id="s_4",
        score=91.0,
        level=Level.L3,
        script_name="冒充公检法",
        created_at="2026-11-07T10:00:00",
    )
    db.save_alert(alert)
    loaded = db.get_alert("A0001")
    assert loaded is not None and loaded.level is Level.L3 and loaded.status is AlertStatus.OPEN

    updated = db.update_alert_status("A0001", AlertStatus.ACKED, note="已联系家属")
    assert updated is not None
    assert updated.status is AlertStatus.ACKED
    assert any("已联系家属" in item for item in updated.actions)
    assert db.get_alert("A0001").status is AlertStatus.ACKED
    assert db.stats()["open_alerts"] == 0
    assert db.update_alert_status("没这个", AlertStatus.ACKED) is None


def test_reset_clears_everything(tmp_path):
    db = _db(tmp_path)
    db.save_session(
        "s_5", role="normal", turns=1, texts=["x"], evidence=[], notifications=[], last_decision=None
    )
    db.append_message("s_5", text="x")
    db.init_db(reset=True)
    assert db.load_session("s_5") is None
    assert db.count_messages() == 0
