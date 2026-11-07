"""会话与画像（T-09）：落盘记忆、上下文摘要、画像偏移、冷却与白名单。

对外只暴露 4 个入口，engine 接线时按这 4 个调即可：

- ``MemoryStore``：sqlite3 三表读写
  （record_turn / recent_summary / context_evidence / record_alert / record_ack / recent_alerts / alert_count）
- ``build_profile(evidences, role, alert_count=0) -> dict``：阈值偏移 + reasons
- ``should_notify(store, session_id, level, now=None) -> (bool, str)``：30 分钟冷却
- ``match_whitelist(text, entries=None) -> str | None``：白名单命中原因
"""

from __future__ import annotations

from app.pipelines.memory.cooldown import COOLDOWN_MINUTES, should_notify
from app.pipelines.memory.profile import build_profile
from app.pipelines.memory.store import (
    DEFAULT_DB_NAME,
    SUMMARY_MAX_CHARS,
    SUMMARY_TURNS,
    MemoryStore,
)
from app.pipelines.memory.whitelist import DEFAULT_WHITELIST, match_whitelist

__all__ = [
    "COOLDOWN_MINUTES",
    "DEFAULT_DB_NAME",
    "DEFAULT_WHITELIST",
    "SUMMARY_MAX_CHARS",
    "SUMMARY_TURNS",
    "MemoryStore",
    "build_profile",
    "match_whitelist",
    "should_notify",
]
