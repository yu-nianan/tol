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
from app.pipelines.decision.scoring import (
    CASE_MIN_SIM,
    STAGE_FLOOR_FROM,
    STAGE_FLOOR_SCORE,
    STAGE_MIN_HITS,
    STAGE_MIN_SIM,
    evaluate,
    stage_index,
)
from app.pipelines.knowledge.store import Case, KnowledgeBase
from app.pipelines.memory import MemoryStore, build_profile, match_whitelist, should_notify
from app.pipelines.notify.guardian import notify_guardian
from app.pipelines.notify.report_builder import build_report
from app.pipelines.text import llm, rules
from app.pipelines.text.normalize import mask_sensitive, normalize
from app.schemas import (
    CAP_WITHOUT_EVIDENCE,
    Alert,
    AlertStatus,
    Decision,
    Evidence,
    Level,
    Report,
    ScriptHit,
    SourceKind,
    dedupe,
    level_for,
)

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
    # 会话内已走到的剧本阶段（0–4），只增不减（T-07）
    stage_index: int = 0


class DetectionEngine:
    def __init__(self, kb: KnowledgeBase, store: MemoryStore | None = None) -> None:
        self.kb = kb
        self.store = store if store is not None else MemoryStore()
        self.sessions: dict[str, SessionState] = {}
        self.alerts: dict[str, Alert] = {}

    # ---------- 会话 ----------
    def _state(self, session_id: str, role: str) -> SessionState:
        state = self.sessions.get(session_id)
        if state is None:
            state = SessionState(session_id=session_id, role=role)
            self.sessions[session_id] = state
        if role:
            state.role = role
        return state

    # ---------- 主流程 ----------
    def detect_text(self, text: str, session_id: str = "default", role: str = "normal"):
        started = time.perf_counter()
        clean = normalize(text)
        masked = mask_sensitive(clean)
        state = self._state(session_id, role)

        evidence: list[Evidence] = rules.extract(masked)
        self.store.record_turn(session_id, masked, role)

        # T-09 白名单：只有"没命中任何规则证据"时才生效，避免骗子一句"不信打 110"把分洗白
        whitelist_reason = match_whitelist(masked)
        if whitelist_reason and not evidence:
            decision = Decision(
                score=0.0,
                level=Level.L0,
                script=None,
                evidence=[],
                reasons=[whitelist_reason],
                stage_index=state.stage_index,
            )
            state.turns += 1
            state.texts.append(masked)
            state.last_decision = decision
            return None, decision, (time.perf_counter() - started) * 1000

        context = self.store.context_evidence(session_id)
        if context is not None:
            evidence.insert(0, context)

        script = self._match_script(masked)
        if settings.llm_enabled:
            hints = [script.stage_label] if script else []
            evidence.extend(llm.extract_evidence(masked, hints))

        for row in self.kb.search_cases(masked, top_k=2):
            case, similarity = row[0], row[1]
            source = row[2] if len(row) > 2 else "bm25"
            if similarity < CASE_MIN_SIM:
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
                    meta={
                        "case_id": case.id,
                        "similarity": similarity,
                        "script_id": case.script_id,
                        "source": source,
                    },
                )
            )

        # 证据累积（T-07）：历史证据参与本轮打分，但只保留最近 40 条，防止越滚越大
        scored = dedupe([*state.evidence[-40:], *evidence])
        state.stage_index = max(state.stage_index, self._stage_pos(script))
        stage_floor = STAGE_FLOOR_SCORE if state.stage_index >= STAGE_FLOOR_FROM else 0.0
        score, reasons, _dims, cap_applied = evaluate(scored, script, role, stage_floor=stage_floor)
        # T-09 画像偏移：角色 bias 已在 scoring 里加过，这里只补"历史告警次数"带来的额外偏移，
        # 理由一并进 Decision.reasons（避免同一份 bias 被加两次）
        profile = build_profile(scored, role, self.store.alert_count(role=role))
        extra_offset = float(profile["offset"]) - float(profile["bias"])
        score = round(min(score + extra_offset, 100.0), 1)
        reasons.extend(str(reason) for reason in profile["reasons"])
        cited_case_ids = [
            str(ev.meta.get("case_id"))
            for ev in scored
            if ev.kind == SourceKind.CASE and ev.meta.get("case_id")
        ]
        # FR-2.7 幻觉抑制：一条检索案例都没引用时不许给出最高等级（封顶 60 → 最高 L2）
        if not cited_case_ids and score > CAP_WITHOUT_EVIDENCE:
            score = CAP_WITHOUT_EVIDENCE
            cap_applied = True
            reasons.append(
                f"无检索案例引用，按幻觉抑制封顶 {CAP_WITHOUT_EVIDENCE:.0f} 分（最高 L2）"
            )
        level = level_for(score)
        decision = Decision(
            score=score,
            level=level,
            script=script,
            evidence=scored,
            reasons=reasons,
            cap_applied=cap_applied,
            need_human=level >= Level.L2,
            stage_index=state.stage_index,
            cited_case_ids=list(dict.fromkeys(cited_case_ids)),
        )

        state.turns += 1
        state.texts.append(masked)
        state.evidence.extend(evidence)
        state.last_decision = decision

        alert: Alert | None = None
        if level >= Level.L1:
            # T-09 冷却只压"再推一次通知"，不压"记一条告警"：
            # 告警本身要落盘可审计，否则 30 分钟内的第二通电话在报告里会凭空消失。
            alert = self._open_alert(state, decision)
            self.store.record_alert(alert)
            allow, why = should_notify(self.store, session_id, level)
            if allow:
                # T-11：分级推送交给 notify 层（L1 站内 / L2 +语音 / L3 +监护人），engine 不再挑档
                note = notify_guardian(alert, decision)
                state.notifications.append(note)
            else:
                reasons.append(why)

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

    def _match_script(self, text: str) -> ScriptHit | None:
        """按"整段对话命中该剧本多少信号"选剧本，而不是"哪个阶段单词分最高"（T-07）。

        背景：``KnowledgeBase.match_script`` 只取分数最高的阶段，真实样本里一句话通常
        只含每个阶段 1 个信号（实测 S01 四个阶段各 1/4、1/5），按比例门禁会全灭；
        而跨剧本共用词（S01 立威说"涉嫌洗钱"、S10 转账阶段也收"洗钱"）会让分数最高的
        阶段来自错误剧本。这里的口径是：

        1. 按剧本累计命中信号数，命中多的剧本优先（平分再比阶段分）；
        2. 累计命中 < ``STAGE_MIN_HITS`` 且该阶段命中比例 < ``STAGE_MIN_SIM`` 时视为擦边，
           单一通用词（"洗钱""公安"）不足以认定剧本；
        3. 剧本内取"走到最远"的那个阶段（阶段分最高）。
        """
        best: ScriptHit | None = None
        best_key: tuple[int, float] = (0, 0.0)
        for script in self.kb.scripts:
            total_hits = 0
            best_stage = None
            best_hits: list[str] = []
            best_score = 0.0
            for stage in script.stages:
                hits = [signal for signal in stage.signals if signal in text]
                if not hits:
                    continue
                total_hits += len(hits)
                score = stage.weight * (0.6 + 0.4 * len(hits) / max(len(stage.signals), 1))
                if score > best_score:
                    best_stage, best_hits, best_score = stage, hits, score
            if best_stage is None:
                continue
            ratio = len(best_hits) / max(len(best_stage.signals), 1)
            if total_hits < STAGE_MIN_HITS and ratio < STAGE_MIN_SIM:
                continue
            key = (total_hits, best_score)
            if key <= best_key:
                continue
            best_key = key
            best = ScriptHit(
                script_id=script.id,
                name=script.name,
                stage_name=best_stage.name,
                stage_label=best_stage.label,
                stage_weight=min(best_score, 0.99),
                risk_base=script.risk_base,
                advice=list(script.advice),
                matched_signals=best_hits,
            )
        return best

    def _stage_pos(self, hit) -> int:
        """按剧本内真实位置算阶段序号（1–4）；找不到就退回按权重估算。"""
        if hit is None:
            return 0
        for script in self.kb.scripts:
            if script.id != hit.script_id:
                continue
            for position, stage in enumerate(script.stages, start=1):
                if stage.name == hit.stage_name:
                    return min(position, 4)
        return stage_index(hit)

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
        return alert

    # ---------- 干预 / 报告 ----------
    def ack_alert(self, alert_id: str, action: str, note: str = "") -> Alert:
        alert = self.alerts.get(alert_id)
        if alert is None:
            raise KeyError(alert_id)
        if action == "dismiss":
            alert.status = AlertStatus.DISMISSED
        else:
            alert.status = AlertStatus.ACKED
        if note:
            alert.actions = [*alert.actions, f"备注：{note}"]
        self.store.record_ack(alert.id, "dismissed" if action == "dismiss" else "acked")
        return alert

    def build_report(self, session_id: str) -> Report:
        state = self.sessions.get(session_id)
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
        return {
            "sessions": len(self.sessions),
            "alerts": len(self.alerts),
            "open_alerts": sum(1 for a in self.alerts.values() if a.status == AlertStatus.OPEN),
        }


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
