"""监护人推送：三档 × 三渠道，配了 webhook 才真发，没配就如实返回 skipped。

渠道映射（等级越高触达越强）::

    L1 → 站内
    L2 → 站内 + 语音
    L3 → 站内 + 语音 + 监护人（企业微信/钉钉机器人 webhook）

诚实是底线：语音外呼通道没有接入，就返回 ``skipped``；webhook 没配置，也返回
``skipped``；绝不把"没发出去"写成"已发送"。演示时照着 channels 里的真实状态讲。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.pipelines.notify.sanitize import mask_data, mask_text
from app.schemas import Alert, Decision, Level

log = get_logger(__name__)

LEVEL_CHANNELS: dict[Level, tuple[str, ...]] = {
    Level.L0: (),
    Level.L1: ("in_app",),
    Level.L2: ("in_app", "voice"),
    Level.L3: ("in_app", "voice", "guardian"),
}

# 真正"离开进程"的渠道；站内只是写进会话/报告
EXTERNAL_CHANNELS = ("voice", "guardian")

VOICE_NOTE = "语音外呼通道未接入（无供应商配置），演示时请口播这句提醒"
WEBHOOK_NOTE = "未配置 GUARDIAN_WEBHOOK，演示时请说明这是降级路径"


def notify_guardian(alert: Alert, decision: Decision) -> dict[str, object]:
    """按等级选渠道并逐个投递，返回每个渠道的真实状态。"""
    results: list[dict[str, object]] = []
    for channel in LEVEL_CHANNELS.get(alert.level, ()):
        if channel == "in_app":
            results.append(_deliver_in_app(alert, decision))
        elif channel == "voice":
            results.append(_deliver_voice(alert, decision))
        elif channel == "guardian":
            results.append(_deliver_guardian(alert, decision))

    external_ok = [item for item in results if item["channel"] in EXTERNAL_CHANNELS and item.get("ok")]
    return {
        "event": "notify",
        "alert_id": alert.id,
        "session_id": alert.session_id,
        "level": int(alert.level),
        "level_label": alert.level_label,
        "status": _overall_status(results),
        "sent": bool(external_ok),
        "channels": results,
    }


def record_ack_in_session(
    session_state: object, alert: Alert, action: str, note: str = ""
) -> dict[str, object]:
    """把"已介入/误报/已忽略"的结论写回会话（报告的通知记录里能查到）。"""
    notifications = getattr(session_state, "notifications", None)
    if notifications is None:
        raise TypeError("session_state 缺少 notifications 列表，无法回写回执")
    record: dict[str, object] = {
        "event": "ack",
        "alert_id": alert.id,
        "session_id": alert.session_id,
        "action": action,
        "status": alert.status.value,
        "note": mask_text(note),
    }
    notifications.append(record)
    log.info("告警回写会话", extra={"alert_id": alert.id, "session_id": alert.session_id})
    return record


# ---------- 各渠道实现 ----------
def _deliver_in_app(alert: Alert, decision: Decision) -> dict[str, object]:
    """站内提醒：写入本地日志与报告，不需要外部网络。"""
    log.info(
        "站内提醒已记录",
        extra={"alert_id": alert.id, "session_id": alert.session_id, "level": int(alert.level)},
    )
    return {
        "channel": "in_app",
        "status": "recorded",
        "ok": True,
        "alert_id": alert.id,
        "summary": _summary(alert, decision),
    }


def _deliver_voice(alert: Alert, decision: Decision) -> dict[str, object]:
    """语音外呼：没有供应商配置，如实记为 skipped。"""
    log.info("语音外呼通道未接入，跳过", extra={"alert_id": alert.id})
    return {
        "channel": "voice",
        "status": "skipped",
        "ok": False,
        "alert_id": alert.id,
        "note": VOICE_NOTE,
    }


def _deliver_guardian(alert: Alert, decision: Decision) -> dict[str, object]:
    """监护人 webhook：配了才发；发失败也只报真实错误，不吞异常。"""
    payload = _build_payload(alert, decision)
    if not settings.guardian_webhook:
        log.info("guardian webhook 未配置，仅记录", extra={"alert_id": alert.id})
        return {
            "channel": "guardian",
            "status": "skipped",
            "ok": False,
            "alert_id": alert.id,
            "note": WEBHOOK_NOTE,
            "payload_preview": payload,
        }
    try:
        response = httpx.post(settings.guardian_webhook, json=payload, timeout=3.0)
        ok = 200 <= response.status_code < 300
        log.info(
            "guardian webhook 已发送",
            extra={"alert_id": alert.id, "level": int(alert.level)},
        )
        return {
            "channel": "guardian",
            "status": "sent" if ok else "http_error",
            "ok": ok,
            "alert_id": alert.id,
            "http_status": response.status_code,
        }
    except httpx.HTTPError as exc:
        detail = mask_text(str(exc))
        log.warning("guardian webhook 发送失败: %s", detail, extra={"alert_id": alert.id})
        return {
            "channel": "guardian",
            "status": "error",
            "ok": False,
            "alert_id": alert.id,
            "detail": detail,
        }


def _build_payload(alert: Alert, decision: Decision) -> dict[str, object]:
    advice = decision.script.advice[:3] if decision.script else []
    reasons = decision.reasons[:5]
    return mask_data(
        {
            "event": "fraud_alert",
            "alert_id": alert.id,
            "session_id": alert.session_id,
            "level": int(alert.level),
            "level_label": alert.level_label,
            "score": alert.score,
            "script": alert.script_name,
            "summary": _summary(alert, decision),
            "evidence_count": len(decision.evidence),
            "reasons": reasons,
            "advice": advice,
        }
    )


def _summary(alert: Alert, decision: Decision) -> str:
    script = alert.script_name or (decision.script.name if decision.script else "未匹配剧本")
    return f"{alert.level_label}｜{script}｜评分 {alert.score:.0f}｜证据 {len(decision.evidence)} 条"


def _overall_status(results: list[dict[str, Any]]) -> str:
    """L3 以监护人渠道为准；L1/L2 看外部渠道，站内单列 recorded。"""
    if not results:
        return "skipped"
    guardian = next((item for item in results if item["channel"] == "guardian"), None)
    if guardian is not None:
        return "sent" if guardian.get("ok") else "skipped"
    external = [item for item in results if item["channel"] in EXTERNAL_CHANNELS]
    if not external:
        return "recorded" if any(item.get("ok") for item in results) else "skipped"
    return "sent" if all(item.get("ok") for item in external) else "skipped"
