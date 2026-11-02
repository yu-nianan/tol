"""干预与报告：告警确认/忽略（人机协同）、会话报告（四个必填段落）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import AppError
from app.pipelines.decision.engine import get_engine
from app.schemas import AckRequest, Alert, ReportResponse

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/alerts/{alert_id}", response_model=Alert, summary="查询告警")
def get_alert(alert_id: str) -> Alert:
    engine = get_engine()
    alert = engine.alerts.get(alert_id)
    if alert is None:
        raise AppError("告警不存在", code="alert_not_found", status=404)
    return alert


@router.post("/alerts/{alert_id}/ack", response_model=Alert, summary="确认/忽略告警")
def ack_alert(alert_id: str, payload: AckRequest) -> Alert:
    engine = get_engine()
    try:
        return engine.ack_alert(alert_id, payload.action, payload.note)
    except KeyError as exc:
        raise AppError("告警不存在", code="alert_not_found", status=404) from exc


@router.get("/report/{session_id}", response_model=ReportResponse, summary="生成会话报告")
def get_report(session_id: str) -> ReportResponse:
    engine = get_engine()
    try:
        report = engine.build_report(session_id)
    except KeyError as exc:
        raise AppError("该会话还没有任何检测记录", code="session_not_found", status=404) from exc
    return ReportResponse(report=report)


@router.get("/stats", summary="运行概览")
def stats() -> dict[str, object]:
    return get_engine().stats()
