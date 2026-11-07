from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.pipelines.notify.weekly import build_weekly_digest
from app.schemas import Level


def test_weekly_digest_counts_only_window(make_alert) -> None:
    now = datetime(2026, 11, 7, 12, 0, 0)
    alerts = [
        make_alert(Level.L3, "s1", "A1", (now - timedelta(days=1)).isoformat()),
        make_alert(Level.L1, "s2", "A2", (now - timedelta(days=3)).isoformat()),
        make_alert(Level.L2, "s3", "A3", (now - timedelta(days=10)).isoformat()),
    ]

    digest = build_weekly_digest(alerts, now=now, days=7)

    assert digest["total_alerts"] == 2
    assert digest["window_days"] == 7
    assert digest["sessions"] == 2
    assert digest["by_script"]["冒充公检法诈骗"] == 2
    assert digest["top_script"] == "冒充公检法诈骗"
    assert digest["by_level"]["L3 紧急"] == 1
    assert digest["by_level"]["L1 提醒"] == 1
    assert digest["by_day"] == {"2026-11-04": 1, "2026-11-06": 1}


def test_weekly_digest_handles_undated_and_high_risk(make_alert) -> None:
    now = datetime(2026, 11, 7, 12, 0, 0)
    alerts = [
        make_alert(Level.L3, "s1", "A1", (now - timedelta(days=2)).isoformat()),
        make_alert(Level.L2, "s2", "A2", (now - timedelta(days=2)).isoformat()),
        make_alert(Level.L2, "s3", "A3", ""),
    ]

    digest = build_weekly_digest(alerts, now=now)

    assert digest["total_alerts"] == 3
    assert digest["undated_alerts"] == 1
    assert digest["high_risk_alerts"] == 3
    assert digest["open_alerts"] == 3
    assert digest["by_status"] == {"open": 3}


def test_weekly_digest_rejects_non_positive_window(make_alert) -> None:
    with pytest.raises(ValueError):
        build_weekly_digest([make_alert()], days=0)
