"""画像：把 PROFILE 证据 + 角色 + 历史告警次数，折算成阈值偏移与可解释理由。

偏移由 engine 加到分数上（阈值不变），理由直接进 Decision.reasons，
所以报告里能看到"为什么这个人的分被调高/调低"，而不是一个黑盒数字。
"""

from __future__ import annotations

from app.schemas import ROLE_BIAS, Evidence, SourceKind

# 每多一次历史告警加多少分、最多加多少
EXTRA_PER_ALERT = 2.0
MAX_ALERT_ADJUST = 8.0
# 合计偏移再封一个顶，避免画像把分数顶飞
MAX_TOTAL_OFFSET = 18.0


def build_profile(
    evidences: list[Evidence],
    role: str,
    alert_count: int = 0,
) -> dict[str, object]:
    """返回 {role, facts, bias, extra, offset, alert_count, reasons}。

    facts 来自 kind=PROFILE 的证据：约定 ``meta={"key": ..., "value": ...}``；
    没有 meta 时退回用 evidence.code / evidence.text。
    """
    facts: dict[str, str] = {}
    for evidence in evidences:
        if evidence.kind != SourceKind.PROFILE:
            continue
        key = str(evidence.meta.get("key") or evidence.code or "").strip()
        value = str(evidence.meta.get("value") or evidence.text or "").strip()
        if key and value:
            facts[key] = value

    normalized = role if role in ROLE_BIAS else "normal"
    bias = ROLE_BIAS[normalized]
    extra = min(max(alert_count, 0) * EXTRA_PER_ALERT, MAX_ALERT_ADJUST)
    offset = round(max(min(bias + extra, MAX_TOTAL_OFFSET), -MAX_TOTAL_OFFSET), 1)

    reasons: list[str] = []
    if role != normalized:
        reasons.append(f"未知角色 {role!r}，按 {normalized} 的画像偏移处理")
    reasons.append(f"画像角色 {normalized}：阈值偏移 {bias:+.1f}")
    if extra > 0:
        reasons.append(f"近 30 天历史告警 {alert_count} 次：追加阈值偏移 {extra:+.1f}")
    if facts:
        labels = "、".join(f"{key}={value}" for key, value in facts.items())
        reasons.append(f"画像要点：{labels}")

    return {
        "role": normalized,
        "facts": facts,
        "bias": round(bias, 1),
        "extra": round(extra, 1),
        "offset": offset,
        "alert_count": max(alert_count, 0),
        "reasons": reasons,
    }
