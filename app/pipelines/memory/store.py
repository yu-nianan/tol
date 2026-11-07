"""会话记忆：sqlite3 落盘 sessions / messages / alerts 三张表。

没有 ORM、没有数据库服务；每次写入立即提交，所以"进程重启"（新建一个实例）
仍能读到历史。测试就是用 tmp_path 下的同一个 db 文件新建实例来模拟重启的。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.core.config import DATA_DIR
from app.schemas import Alert, Evidence, Level, Modality, SourceKind

DEFAULT_DB_NAME = "memory.sqlite3"
SUMMARY_TURNS = 5
SUMMARY_MAX_CHARS = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    role       TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'normal',
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id    TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 0,
    level       INTEGER NOT NULL DEFAULT 0,
    script_name TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    acked_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_session
    ON alerts(session_id, created_at);
"""


class MemoryStore:
    """三张表的轻量封装：写会话、取最近摘要、记告警、查冷却窗口。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DATA_DIR / DEFAULT_DB_NAME
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> MemoryStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---------- 会话 / 消息 ----------
    def record_turn(
        self,
        session_id: str,
        text: str,
        role: str = "normal",
        *,
        created_at: str | None = None,
    ) -> int:
        """记一轮对话；会话不存在就建，角色与更新时间跟着最新一轮走。"""
        moment = created_at or _now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO sessions(session_id, role, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    role = excluded.role,
                    updated_at = excluded.updated_at
                """,
                (session_id, role, moment, moment),
            )
            cursor = self._conn.execute(
                "INSERT INTO messages(session_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, text, moment),
            )
        return int(cursor.lastrowid or 0)

    def recent_messages(self, session_id: str, limit: int = SUMMARY_TURNS) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT role, text, created_at FROM messages
            WHERE session_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def recent_summary(self, session_id: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
        """最近 5 轮的摘要，硬上限 max_chars（默认 200 字），超出补省略号。"""
        rows = self.recent_messages(session_id, SUMMARY_TURNS)
        parts = [_clip(str(row["text"]), 60) for row in rows if str(row["text"]).strip()]
        if not parts:
            return ""
        summary = "；".join(parts)
        if len(summary) > max_chars:
            summary = summary[: max_chars - 1] + "…"
        return summary

    def context_evidence(self, session_id: str) -> Evidence | None:
        """把摘要包装成 Evidence(kind=CONTEXT)，交给打分器当会话上下文证据。"""
        rows = self.recent_messages(session_id, SUMMARY_TURNS)
        summary = self.recent_summary(session_id)
        if not summary:
            return None
        return Evidence(
            code="session_context",
            label="会话上下文摘要",
            category="other",
            text=summary,
            weight=0.3,
            confidence=0.6,
            modality=Modality.TEXT,
            kind=SourceKind.CONTEXT,
            meta={"session_id": session_id, "turns": len(rows)},
        )

    def turn_count(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    # ---------- 告警 ----------
    def record_alert(self, alert: Alert, *, created_at: str | None = None) -> None:
        moment = created_at or alert.created_at or _now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO alerts(alert_id, session_id, score, level, script_name, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    score = excluded.score,
                    level = excluded.level,
                    script_name = excluded.script_name,
                    status = excluded.status
                """,
                (
                    alert.id,
                    alert.session_id,
                    alert.score,
                    int(alert.level),
                    alert.script_name,
                    alert.status.value,
                    moment,
                ),
            )

    def record_ack(
        self, alert_id: str, status: str = "acked", *, now: str | None = None
    ) -> bool:
        """人工处置回写；返回是否真的更新到一行。"""
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE alerts SET status = ?, acked_at = ? WHERE alert_id = ?",
                (status, now or _now(), alert_id),
            )
        return cursor.rowcount > 0

    def recent_alerts(
        self,
        session_id: str,
        *,
        min_level: Level = Level.L0,
        window_minutes: int = 30,
        now: datetime | None = None,
    ) -> list[dict[str, object]]:
        moment = now or datetime.now()
        since = (moment - timedelta(minutes=window_minutes)).isoformat(timespec="seconds")
        rows = self._conn.execute(
            """
            SELECT alert_id, session_id, score, level, script_name, status, created_at
            FROM alerts
            WHERE session_id = ? AND level >= ? AND created_at >= ?
            ORDER BY created_at DESC, alert_id DESC
            """,
            (session_id, int(min_level), since),
        ).fetchall()
        return [dict(row) for row in rows]

    def alert_count(
        self,
        *,
        role: str | None = None,
        session_id: str | None = None,
        days: int = 30,
        now: datetime | None = None,
    ) -> int:
        """历史告警次数（画像用）：按角色或会话过滤，默认看最近 30 天。"""
        moment = now or datetime.now()
        since = (moment - timedelta(days=days)).isoformat(timespec="seconds")
        sql = "SELECT COUNT(*) AS n FROM alerts WHERE created_at >= ?"
        params: list[object] = [since]
        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(session_id)
        if role is not None:
            sql += " AND session_id IN (SELECT session_id FROM sessions WHERE role = ?)"
            params.append(role)
        row = self._conn.execute(sql, params).fetchone()
        return int(row["n"]) if row is not None else 0


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clip(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"
