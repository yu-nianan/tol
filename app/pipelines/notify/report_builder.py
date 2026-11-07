"""报告生成：赛题要的四段（结论 / 证据链 / 剧本匹配 / 建议 + 监护记录）。"""

from __future__ import annotations

from datetime import datetime

from app.schemas import Decision, Level, Report


def default_advice(level: Level) -> list[str]:
    if level >= Level.L3:
        return [
            "立即停止一切操作，不要再转账或提供验证码",
            "拨打 96110 或 110 报警，并通知家人",
            "保存聊天记录、转账凭证、对方账号作为证据",
        ]
    if level >= Level.L2:
        return [
            "先挂断电话，不要按对方要求操作手机或银行 APP",
            "通过官方渠道（APP / 官网 / 官方客服）自行核实",
            "把这段对话发给家人或同学看一眼",
        ]
    if level >= Level.L1:
        return ["保持警惕，涉及转账、验证码、共享屏幕一律拒绝", "如有疑问，先与家人核实"]
    return ["未发现明显诈骗特征，仍需警惕陌生链接与陌生来电"]


def build_report(
    *,
    session_id: str,
    turns: int,
    decision: Decision,
    notifications: list[dict[str, object]],
    text_count: int,
) -> Report:
    evidence = decision.evidence
    modalities = sorted({ev.modality.value for ev in evidence})
    top_evidence = sorted(evidence, key=lambda ev: ev.weight, reverse=True)[:8]

    risk_summary: dict[str, object] = {
        "score": decision.score,
        "level": int(decision.level),
        "level_label": decision.level_label,
        "need_human": decision.need_human,
        "cap_applied": decision.cap_applied,
        "turns": turns,
        "text_count": text_count,
        "modalities": modalities,
    }
    if decision.script is not None:
        risk_summary["script"] = decision.script.name
        risk_summary["stage"] = decision.script.stage_label

    script_match: dict[str, object] = {}
    if decision.script is not None:
        script_match = {
            "script_id": decision.script.script_id,
            "name": decision.script.name,
            "stage_name": decision.script.stage_name,
            "stage_label": decision.script.stage_label,
            "stage_weight": decision.script.stage_score,
            "matched_signals": decision.script.matched_signals,
        }

    evidence_chain = [
        {
            "code": ev.code,
            "label": ev.label,
            "text": ev.text,
            "weight": ev.weight,
            "confidence": ev.confidence,
            "kind": ev.kind.value,
            "modality": ev.modality.value,
        }
        for ev in top_evidence
    ]

    advice = list(decision.script.advice) if decision.script else default_advice(decision.level)

    return Report(
        session_id=session_id,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        risk_summary=risk_summary,
        evidence_chain=evidence_chain,
        script_match=script_match,
        advice=advice,
        notifications=list(notifications),
        turns=turns,
    )
