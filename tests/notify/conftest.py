from __future__ import annotations

from datetime import datetime

import pytest

from app.schemas import Alert, AlertStatus, Decision, Evidence, Level, ScriptHit, SourceKind

PHONE = "13812345678"


@pytest.fixture
def make_decision():
    def _make(level: Level = Level.L3, phone: str = PHONE) -> Decision:
        evidence = [
            Evidence(
                code="impersonate_authority",
                label="冒充公检法",
                category="stage_authority",
                text=f"你的银行卡涉嫌洗钱，请拨 {phone}",
                weight=0.9,
                confidence=0.95,
                kind=SourceKind.RULE,
            )
        ]
        script = ScriptHit(
            script_id="S01",
            name="冒充公检法诈骗",
            stage_name="transfer",
            stage_label="诱导转账",
            stage_weight=0.9,
            advice=["立即挂断并拨打 96110", "不要向陌生账户转账"],
        )
        return Decision(
            score=92.0,
            level=level,
            script=script,
            evidence=evidence,
            reasons=[f"对方要求转账，来电号码 {phone}"],
            cap_applied=False,
            need_human=level >= Level.L2,
            stage_index=4,
            cited_case_ids=["C001"],
        )

    return _make


@pytest.fixture
def make_alert():
    def _make(
        level: Level = Level.L3,
        session_id: str = "s1",
        alert_id: str = "A1",
        created_at: str | None = None,
    ) -> Alert:
        stamp = created_at if created_at is not None else datetime(2026, 11, 7, 12, 0, 0).isoformat()
        return Alert(
            id=alert_id,
            session_id=session_id,
            score=92.0,
            level=level,
            script_name="冒充公检法诈骗",
            created_at=stamp,
            status=AlertStatus.OPEN,
            actions=["全屏拦截", "通知监护人"],
        )

    return _make
