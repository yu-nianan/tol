"""运行时库：会话 / 消息 / 告警的落库存取（SQLite 单文件，只用标准库）。

三条原则：
1. **表结构写在代码里**，启动时 `init_db()` 幂等建表，不需要手工执行 SQL；
2. **库文件不进 git**，删掉它就等于清空重放（`RESET_DB=1` 也能一键重置）；
3. **只此一处碰 SQL**，别的模块都通过本模块的函数存取，换存储只改这里。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import DATA_DIR
from app.core.logging import get_logger
from app.schemas import Alert, AlertStatus, Level

log = get_logger(__name__)

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    role          TEXT NOT NULL DEFAULT 'normal',
    turns         INTEGER NOT NULL DEFAULT 0,
    texts         TEXT NOT NULL DEFAULT '[]',
    evidence      TEXT NOT NULL DEFAULT '[]',
    notifications TEXT NOT NULL DEFAULT '[]',
    last_decision TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    modality   TEXT NOT NULL DEFAULT 'text',
    text       TEXT NOT NULL DEFAULT '',
    level      INTEGER NOT NULL DEFAULT 0,
    score      REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS alerts (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    score       REAL NOT NULL,
    level       INTEGER NOT NULL,
    script_name TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',
    actions     TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:  # 库被手工改坏时不要炸整个服务
        log.warning("存储内容不是合法 JSON，已按空值处理", extra={"raw_head": (raw or "")[:40]})
        return default


@dataclass
class SessionRecord:
    """一行的读模型：和 engine.SessionState 一一对应。"""

    session_id: str
    role: str = "normal"
    turns: int = 0
    texts: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    last_decision: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""


class Storage:
    def __init__(self, path: str | Path | None = None, reset: bool = False) -> None:
        env_path = os.getenv("APP_DB_PATH", "").strip()
        self.path = Path(path or env_path or (DATA_DIR / "app.db"))
        self._lock = threading.Lock()
        self.init_db(reset=reset)

    # ---------- 建库 ----------
    def init_db(self, reset: bool = False) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if reset and self.path.exists():
            self.path.unlink()
            log.info("运行时库已重置", extra={"path": str(self.path)})
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        log.info("运行时库就绪", extra={"path": str(self.path), "schema_version": SCHEMA_VERSION})

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ---------- 会话 ----------
    def save_session(
        self,
        session_id: str,
        *,
        role: str,
        turns: int,
        texts: list[str],
        evidence: list[dict[str, Any]],
        notifications: list[dict[str, Any]],
        last_decision: dict[str, Any] | None,
    ) -> None:
        now = _now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO sessions
                    (session_id, role, turns, texts, evidence, notifications, last_decision,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    role=excluded.role,
                    turns=excluded.turns,
                    texts=excluded.texts,
                    evidence=excluded.evidence,
                    notifications=excluded.notifications,
                    last_decision=excluded.last_decision,
                    updated_at=excluded.updated_at
                """,
                (
                    session_id,
                    role,
                    turns,
                    _dumps(texts),
                    _dumps(evidence),
                    _dumps(notifications),
                    _dumps(last_decision) if last_decision is not None else None,
                    now,
                    now,
                ),
            )
            conn.commit()

    def load_session(self, session_id: str) -> SessionRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return SessionRecord(
            session_id=row["session_id"],
            role=row["role"],
            turns=row["turns"],
            texts=_loads(row["texts"], []),
            evidence=_loads(row["evidence"], []),
            notifications=_loads(row["notifications"], []),
            last_decision=_loads(row["last_decision"], None),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ---------- 消息 ----------
    def append_message(
        self,
        session_id: str,
        *,
        text: str,
        modality: str = "text",
        level: int = 0,
        score: float = 0.0,
    ) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO messages(session_id, modality, text, level, score, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, modality, text, int(level), float(score), _now()),
            )
            conn.commit()

    def list_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_messages(self, session_id: str | None = None) -> int:
        with closing(self._connect()) as conn:
            if session_id is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?", (session_id,)
                ).fetchone()
        return int(row["n"])

    # ---------- 告警 ----------
    def save_alert(self, alert: Alert) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO alerts(id, session_id, score, level, script_name, status, actions, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    score=excluded.score,
                    level=excluded.level,
                    script_name=excluded.script_name,
                    status=excluded.status,
                    actions=excluded.actions
                """,
                (
                    alert.id,
                    alert.session_id,
                    float(alert.score),
                    int(alert.level),
                    alert.script_name,
                    alert.status.value,
                    _dumps(alert.actions),
                    alert.created_at or _now(),
                ),
            )
            conn.commit()

    def get_alert(self, alert_id: str) -> Alert | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return self._row_to_alert(row) if row is not None else None

    def list_alerts(self, limit: int = 20, status: AlertStatus | None = None) -> list[Alert]:
        sql = "SELECT * FROM alerts"
        args: list[Any] = []
        if status is not None:
            sql += " WHERE status = ?"
            args.append(status.value)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._row_to_alert(row) for row in rows]

    def update_alert_status(self, alert_id: str, status: AlertStatus, note: str = "") -> Alert | None:
        alert = self.get_alert(alert_id)
        if alert is None:
            return None
        alert.status = status
        if note:
            alert.actions = [*alert.actions, f"备注：{note}"]
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE alerts SET status = ?, actions = ? WHERE id = ?",
                (status.value, _dumps(alert.actions), alert_id),
            )
            conn.commit()
        return alert

    @staticmethod
    def _row_to_alert(row: sqlite3.Row) -> Alert:
        return Alert(
            id=row["id"],
            session_id=row["session_id"],
            score=row["score"],
            level=Level(int(row["level"])),
            script_name=row["script_name"],
            status=AlertStatus(row["status"]),
            actions=_loads(row["actions"], []),
            created_at=row["created_at"],
        )

    # ---------- 概览 ----------
    def stats(self) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            sessions = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
            alerts = conn.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"]
            open_alerts = conn.execute(
                "SELECT COUNT(*) AS n FROM alerts WHERE status = ?", (AlertStatus.OPEN.value,)
            ).fetchone()["n"]
            messages = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
        return {
            "sessions": int(sessions),
            "messages": int(messages),
            "alerts": int(alerts),
            "open_alerts": int(open_alerts),
        }


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    return Storage(reset=os.getenv("RESET_DB", "").strip() in {"1", "true", "yes"})
