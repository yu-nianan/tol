"""周报聚合：把最近 N 天的告警压成一份可展示的概览。

纯函数，不读数据库、不发网络请求 —— 数据从 `engine.alerts` 里传进来即可，
方便单测，也方便以后换成 SQLite 取数而不改接口。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta

from app.schemas import Alert, Level


def build_weekly_digest(
    alerts: Iterable[Alert],
    *,
    now: datetime | None = None,
    days: int = 7,
) -> dict[str, object]:
    """统计时间窗内的告警：总量、等级、剧本、状态、涉及会话与每日分布。"""
    if days <= 0:
        raise ValueError("days 必须为正整数")
    end = now or datetime.now()
    start = end - timedelta(days=days)

    window: list[Alert] = []
    undated = 0
    for alert in alerts:
        created = _parse_time(alert.created_at)
        if created is None:
            undated += 1
            window.append(alert)
            continue
        if start <= created <= end:
            window.append(alert)

    level_counts: Counter[str] = Counter(alert.level.label for alert in window)
    script_counts: Counter[str] = Counter(alert.script_name or "未匹配剧本" for alert in window)
    status_counts: Counter[str] = Counter(alert.status.value for alert in window)
    day_counts: Counter[str] = Counter()
    for alert in window:
        created = _parse_time(alert.created_at)
        if created is not None:
            day_counts[created.date().isoformat()] += 1

    top_script = script_counts.most_common(1)[0][0] if script_counts else ""
    high_risk = sum(1 for alert in window if alert.level >= Level.L2)
    return {
        "window_days": days,
        "window_start": start.isoformat(timespec="seconds"),
        "window_end": end.isoformat(timespec="seconds"),
        "total_alerts": len(window),
        "undated_alerts": undated,
        "high_risk_alerts": high_risk,
        "open_alerts": sum(1 for alert in window if alert.status.value == "open"),
        "sessions": len({alert.session_id for alert in window}),
        "by_level": {level.label: level_counts.get(level.label, 0) for level in Level},
        "by_script": dict(script_counts.most_common()),
        "by_status": dict(status_counts),
        "by_day": dict(sorted(day_counts.items())),
        "top_script": top_script,
    }


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
