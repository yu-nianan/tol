"""判定引擎：归一化 → 规则 → 知识库 → 打分 → 分级 → 告警/推送。

这是唯一把各层串起来的地方。接口层只调这里，不直接碰规则和知识库。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from app.core.config import KB_DIR, settings
from app.core.logging import get_logger
from app.pipelines.decision.scoring import evaluate
from app.pipelines.knowledge.store import Case, KnowledgeBase
from app.pipelines.notify.guardian import notify_guardian
from app.pipelines.notify.report_builder import build_report
from app.pipelines.storage import get_storage
from app.pipelines.text import rules
from app.pipelines.text.normalize import mask_sensitive, normalize
from app.schemas import Alert, AlertStatus, Decision, Evidence, Level, Report, SourceKind, level_for

log = get_logger(__name__)

LEVEL_ACTIONS: dict[Level, list[str]] = {
    Level.L0: ["静默记录"],
    Level.L1: ["弹窗提醒", "展示科普提示"],
    Level.L2: ["弹窗警告", "语音提示", "建议挂断并自行核实"],
    Level.L3: ["全屏拦截", "语音告警", "通知监护人", "一键拨打 96110"],
}


@dataclass
class SessionState:
    session_id: str
    role: str = "normal"
    turns: int = 0
    texts: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    notifications: list[dict[str, object]] = field(default_factory=list)
    last_decision: Decision | None = None


class DetectionEngine:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self.db = get_storage()
        # 内存只做"热缓存"，真相在 SQLite：进程重启后仍能读回上一次会话
        self.sessions: dict[str, SessionState] = {}
        self.alerts: dict[str, Alert] = {}

    # ---------- 会话 ----------
    def _state(self, session_id: str, role: str) -> SessionState:
        state = self.sessions.get(session_id)
        if state is None:
            state = self._hydrate(session_id) or SessionState(session_id=session_id, role=role)
            self.sessions[session_id] = state
        if role:
            state.role = role
        return state

    def _hydrate(self, session_id: str) -> SessionState | None:
        record = self.db.load_session(session_id)
        if record is None:
            return None
        return SessionState(
            session_id=record.session_id,
            role=record.role,
            turns=record.turns,
            texts=list(record.texts),
            evidence=[Evidence(**item) for item in record.evidence],
            notifications=list(record.notifications),
            last_decision=Decision(**record.last_decision) if record.last_decision else None,
        )

    def _persist(self, state: SessionState, text: str, decision: Decision) -> None:
        self.db.save_session(
            state.session_id,
            role=state.role,
            turns=state.turns,
            texts=state.texts,
            evidence=[item.model_dump() for item in state.evidence],
            notifications=state.notifications,
            last_decision=decision.model_dump() if state.last_decision else None,
        )
        self.db.append_message(
            state.session_id,
            text=text,
            level=int(decision.level),
            score=decision.score,
        )

    # ---------- 主流程 ----------
    def detect_text(self, text: str, session_id: str = "default", role: str = "normal"):
        started = time.perf_counter()
        clean = normalize(text)
        masked = mask_sensitive(clean)

        evidence: list[Evidence] = rules.extract(masked)

        script = self.kb.match_script(masked)
        for case, similarity in self.kb.search_cases(masked, top_k=2):
            if similarity < 0.2:
                continue
            evidence.append(
                Evidence(
                    code=f"case_{case.id}",
                    label=f"相似案例：{case.title}",
                    category="case",
                    text=case.text[:60],
                    weight=min(1.0, similarity),
                    confidence=similarity,
                    kind=SourceKind.CASE,
                    meta={"case_id": case.id, "similarity": similarity, "script_id": case.script_id},
                )
            )

        score, reasons, _dims, cap_applied = evaluate(evidence, script, role)
        level = level_for(score)
        decision = Decision(
            score=score,
            level=level,
            script=script,
            evidence=evidence,
            reasons=reasons,
            cap_applied=cap_applied,
            need_human=level >= Level.L2,
        )

        state = self._state(session_id, role)
        state.turns += 1
        state.texts.append(masked)
        state.evidence.extend(evidence)
        state.last_decision = decision
        self._persist(state, masked, decision)

        alert: Alert | None = None
        if level >= Level.L1:
            alert = self._open_alert(state, decision)
            if level >= Level.L3:
                note = notify_guardian(alert, decision)
                state.notifications.append(note)

        latency_ms = (time.perf_counter() - started) * 1000
        log.info(
            "文本检测完成",
            extra={
                "session_id": session_id,
                "level": int(level),
                "score": score,
                "latency_ms": round(latency_ms, 2),
            },
        )
        return alert, decision, latency_ms

    def _open_alert(self, state: SessionState, decision: Decision) -> Alert:
        alert = Alert(
            id=f"A{uuid.uuid4().hex[:10]}",
            session_id=state.session_id,
            score=decision.score,
            level=decision.level,
            script_name=decision.script.name if decision.script else "",
            created_at=datetime.now().isoformat(timespec="seconds"),
            status=AlertStatus.OPEN,
            actions=LEVEL_ACTIONS[decision.level],
        )
        self.alerts[alert.id] = alert
        self.db.save_alert(alert)
        return alert

    # ---------- 干预 / 报告 ----------
    def get_alert(self, alert_id: str) -> Alert | None:
        alert = self.alerts.get(alert_id)
        if alert is None:
            alert = self.db.get_alert(alert_id)
            if alert is not None:
                self.alerts[alert_id] = alert
        return alert

    def ack_alert(self, alert_id: str, action: str, note: str = "") -> Alert:
        alert = self.get_alert(alert_id)
        if alert is None:
            raise KeyError(alert_id)
        status = AlertStatus.DISMISSED if action == "dismiss" else AlertStatus.ACKED
        stored = self.db.update_alert_status(alert_id, status, note) or alert
        self.alerts[alert_id] = stored
        return stored

    def build_report(self, session_id: str) -> Report:
        state = self.sessions.get(session_id) or self._hydrate(session_id)
        if state is None or state.last_decision is None:
            raise KeyError(session_id)
        return build_report(
            session_id=session_id,
            turns=state.turns,
            decision=state.last_decision,
            notifications=state.notifications,
            text_count=len(state.texts),
        )

    # ---------- 知识库自更新 ----------
    def ingest_case(self, payload: dict) -> tuple[bool, str]:
        case = Case(
            id=str(payload.get("id") or f"C{len(self.kb.cases) + 1:03d}"),
            script_id=str(payload.get("script_id", "")),
            title=str(payload.get("title", "")),
            text=str(payload.get("text", "")),
            level=str(payload.get("level", "L2")),
        )
        if not case.text.strip():
            return False, "案例文本不能为空"
        added = self.kb.add_case(case)
        return added, case.id if added else "案例已存在"

    # ---------- 概览 ----------
    def stats(self) -> dict[str, object]:
        return self.db.stats()


@lru_cache(maxsize=1)
def get_engine() -> DetectionEngine:
    kb = KnowledgeBase(KB_DIR)
    log.info(
        "引擎就绪 scripts=%s cases=%s llm=%s",
        kb.script_count,
        kb.case_count,
        settings.llm_enabled,
    )
    return DetectionEngine(kb)
