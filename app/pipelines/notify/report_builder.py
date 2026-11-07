"""报告生成：五段（风险说明 / 证据链 / 剧本匹配 / 建议 / 通知记录）+ 可打印 HTML。

HTML 是单文件：CSS 内联、无 CDN、无 JS，浏览器"打印 → 另存为 PDF"即可交付。
报告里所有字符串统一走脱敏（NFR-6），不出现完整手机号 / 身份证 / 卡号。
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape

from app.pipelines.notify.sanitize import mask_data
from app.schemas import Decision, Level, Report

_RISK_LABELS = {
    "score": "综合评分",
    "level": "风险等级",
    "level_label": "等级说明",
    "need_human": "需人工介入",
    "cap_applied": "是否封顶",
    "turns": "会话轮次",
    "text_count": "文本条数",
    "modalities": "涉及模态",
    "script": "命中剧本",
    "stage": "剧本阶段",
    "stage_index": "阶段序号",
}

_SCRIPT_LABELS = {
    "script_id": "剧本编号",
    "name": "剧本",
    "stage_name": "阶段代号",
    "stage_label": "阶段名称",
    "stage_weight": "阶段权重",
    "matched_signals": "命中信号",
}

_EVIDENCE_COLUMNS = (
    ("code", "代号"),
    ("label", "名称"),
    ("text", "命中片段"),
    ("weight", "权重"),
    ("modality", "模态"),
)

_CSS = (
    'body{margin:0;padding:28px;background:#f3f4f6;color:#111827;'
    'font:14px/1.7 "Microsoft YaHei","PingFang SC",sans-serif}'
    ".sheet{max-width:860px;margin:0 auto;background:#fff;padding:36px 44px;"
    "border:1px solid #d1d5db;border-radius:8px}"
    "header{border-bottom:3px solid #1d4ed8;padding-bottom:12px;margin-bottom:22px}"
    "h1{margin:0 0 6px;font-size:22px;color:#1d4ed8}"
    ".meta{color:#6b7280;font-size:13px}"
    ".badge{display:inline-block;padding:2px 10px;border-radius:999px;"
    "background:#fee2e2;color:#b91c1c;font-weight:600}"
    "section{margin:22px 0}"
    "h2{font-size:16px;margin:0 0 10px;padding-left:10px;border-left:4px solid #1d4ed8}"
    "table{width:100%;border-collapse:collapse;font-size:13px}"
    "th,td{border:1px solid #d1d5db;padding:6px 8px;text-align:left;vertical-align:top}"
    "th{background:#f3f4f6;white-space:nowrap}"
    ".kv th{width:140px}"
    ".empty{color:#6b7280}"
    "pre{white-space:pre-wrap;word-break:break-all;background:#f9fafb;"
    "border:1px solid #e5e7eb;padding:10px;font-size:12px}"
    "ol{margin:0;padding-left:22px}"
    "footer{margin-top:28px;padding-top:12px;border-top:1px dashed #d1d5db;"
    "color:#6b7280;font-size:12px}"
    "@media print{body{padding:0;background:#fff}"
    ".sheet{max-width:none;border:0;border-radius:0;padding:0}.no-print{display:none}}"
)


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
        "stage_index": decision.stage_index,
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

    report = Report(
        session_id=session_id,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        risk_summary=risk_summary,
        evidence_chain=evidence_chain,
        script_match=script_match,
        advice=advice,
        notifications=list(notifications),
        turns=turns,
    )
    # 报告是给人看/归档的，落盘前统一脱敏；不做二次加工，字段契约不变
    return report.model_copy(
        update={
            "risk_summary": mask_data(report.risk_summary),
            "evidence_chain": mask_data(report.evidence_chain),
            "script_match": mask_data(report.script_match),
            "advice": mask_data(report.advice),
            "notifications": mask_data(report.notifications),
        }
    )


def render_report_html(report: Report) -> str:
    """渲染单文件可打印 HTML；五段齐全，所有文本先 HTML 转义再输出。"""
    risk = mask_data(report.risk_summary)
    evidence = mask_data(report.evidence_chain)
    script = mask_data(report.script_match)
    advice = mask_data(report.advice)
    notifications = mask_data(report.notifications)
    level_label = _cell(risk.get("level_label", "未分级"))
    score = _cell(risk.get("score", "-"))
    session_id = _cell(report.session_id)

    return "".join(
        [
            "<!DOCTYPE html>\n",
            '<html lang="zh-CN">\n',
            "<head>\n",
            '<meta charset="utf-8">\n',
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n',
            f"<title>反诈风险分析报告 - {session_id}</title>\n",
            f"<style>{_CSS}</style>\n",
            "</head>\n",
            "<body>\n",
            '<main class="sheet">\n',
            "<header>\n",
            "<h1>反诈风险分析报告</h1>\n",
            f'<div class="meta">会话：{session_id}　生成时间：{_cell(report.generated_at)}　'
            f'轮次：{_cell(report.turns)}</div>\n',
            f'<div class="meta">结论：<span class="badge">{level_label}</span>　综合评分 {score}</div>\n',
            "</header>\n",
            f"<section><h2>一、风险说明</h2>{_kv_table(risk, _RISK_LABELS)}</section>\n",
            f"<section><h2>二、证据链</h2>{_evidence_table(evidence)}</section>\n",
            f"<section><h2>三、剧本匹配</h2>{_script_block(script)}</section>\n",
            f"<section><h2>四、防范建议</h2>{_advice_list(advice)}</section>\n",
            f"<section><h2>五、通知记录</h2>{_notifications_block(notifications)}</section>\n",
            f"<footer>{_cell(report.disclaimer)}<br>报告五段：风险说明 / 证据链 / 剧本匹配 / 防范建议 / 通知记录</footer>\n",
            "</main>\n",
            "</body>\n",
            "</html>\n",
        ]
    )


def _cell(value: object) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return "-"
    if isinstance(value, list):
        return "、".join(_cell(item) for item in value) if value else "无"
    if isinstance(value, dict):
        return escape(json.dumps(value, ensure_ascii=False))
    return escape(str(value))


def _kv_table(data: dict[str, object], labels: dict[str, str]) -> str:
    if not data:
        return '<p class="empty">无</p>'
    rows = "".join(
        f"<tr><th>{escape(labels.get(key, key))}</th><td>{_cell(value)}</td></tr>"
        for key, value in data.items()
    )
    return f'<table class="kv"><tbody>{rows}</tbody></table>'


def _evidence_table(items: list[dict[str, object]]) -> str:
    if not items:
        return '<p class="empty">无</p>'
    header = "".join(f"<th>{escape(title)}</th>" for _, title in _EVIDENCE_COLUMNS)
    rows = "".join(
        "<tr>"
        + "".join(f"<td>{_cell(item.get(key))}</td>" for key, _ in _EVIDENCE_COLUMNS)
        + "</tr>"
        for item in items
    )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>"


def _script_block(script: dict[str, object]) -> str:
    if not script:
        return '<p class="empty">未命中剧本（无可用剧本匹配证据）</p>'
    return _kv_table(script, _SCRIPT_LABELS)


def _advice_list(advice: list[str]) -> str:
    if not advice:
        return '<p class="empty">无</p>'
    items = "".join(f"<li>{_cell(item)}</li>" for item in advice)
    return f"<ol>{items}</ol>"


def _notifications_block(notifications: list[dict[str, object]]) -> str:
    if not notifications:
        return '<p class="empty">本次没有触发通知（或通知通道均未配置）</p>'
    payload = json.dumps(notifications, ensure_ascii=False, indent=2)
    return f"<pre>{escape(payload)}</pre>"
