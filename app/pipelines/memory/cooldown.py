"""冷却：同一会话 30 分钟内已经推过同级或更高等级，就不再重复打扰。"""

from __future__ import annotations

from datetime import datetime

from app.pipelines.memory.store import MemoryStore
from app.schemas import Level

COOLDOWN_MINUTES = 30


def should_notify(
    store: MemoryStore,
    session_id: str,
    level: Level,
    *,
    now: datetime | None = None,
    window_minutes: int = COOLDOWN_MINUTES,
) -> tuple[bool, str]:
    """返回 (是否允许推送, 原因)。原因直接写进报告/日志，便于解释"为什么没重复弹"。"""
    if level < Level.L1:
        return True, "L0 仅记录，不触发推送，无需冷却判断"
    recent = store.recent_alerts(
        session_id,
        min_level=level,
        window_minutes=window_minutes,
        now=now,
    )
    if not recent:
        return True, f"同会话 {window_minutes} 分钟内没有同级或更高等级告警，允许推送"
    latest = recent[0]
    latest_level = Level(int(latest["level"])) if latest.get("level") is not None else level
    return False, (
        f"同会话 {window_minutes} 分钟内已推送 {latest_level.label}"
        f"（{latest['created_at']}），本次不重复打扰"
    )
