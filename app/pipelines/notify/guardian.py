"""监护人推送：配了 webhook 就真发，没配就写日志并如实返回"未推送"。

演示时最忌讳"假装发出去了" —— 所以这里把真实状态写进返回值，
报告里的"监护记录"直接引用它。
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import Alert, Decision

log = get_logger(__name__)


def notify_guardian(alert: Alert, decision: Decision) -> dict[str, object]:
    payload = {
        "event": "fraud_alert",
        "alert_id": alert.id,
        "session_id": alert.session_id,
        "level": int(alert.level),
        "level_label": alert.level_label,
        "score": alert.score,
        "script": alert.script_name,
        "reasons": decision.reasons[:5],
        "advice": (decision.script.advice if decision.script else [])[:3],
    }

    if not settings.guardian_webhook:
        log.info("guardian webhook 未配置，仅记录", extra={"alert_id": alert.id})
        return {
            "channel": "log",
            "status": "skipped",
            "alert_id": alert.id,
            "note": "未配置 GUARDIAN_WEBHOOK，演示时请说明这是降级路径",
        }

    try:
        response = httpx.post(settings.guardian_webhook, json=payload, timeout=3.0)
        ok = 200 <= response.status_code < 300
        log.info(
            "guardian webhook 已发送",
            extra={"alert_id": alert.id, "level": int(alert.level)},
        )
        return {
            "channel": "webhook",
            "status": response.status_code,
            "ok": ok,
            "alert_id": alert.id,
        }
    except httpx.HTTPError as exc:
        log.warning("guardian webhook 发送失败: %s", exc, extra={"alert_id": alert.id})
        return {
            "channel": "webhook",
            "status": "error",
            "alert_id": alert.id,
            "detail": str(exc),
        }
