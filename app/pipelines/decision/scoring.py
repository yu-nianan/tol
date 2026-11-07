"""打分器：把证据折成一个 0–100 的分，并给出人话解释。

规则刻意做成"可审计"的加权和：
- 每个维度都在 0–1，权重固定（见 DIM_WEIGHTS），改权重只需改这里；
- 缺失的维度（如纯文本时没有多模态一致性）不参与归一化，避免拉低分数；
- 没有剧本/案例证据时分数封顶，压住模型幻觉带来的虚高。
"""

from __future__ import annotations

from app.schemas import CAP_WITHOUT_EVIDENCE, ROLE_BIAS, Evidence, ScriptHit, SourceKind

DIM_WEIGHTS: dict[str, float] = {
    "stage": 0.30,
    "entity": 0.20,
    "pressure": 0.15,
    "cross": 0.15,
    "channel": 0.10,
    "profile": 0.10,
}

# 画像只影响"敏感度"，不改阈值表，便于解释与测试
ROLE_PROFILE: dict[str, float] = {
    "elder": 1.0,
    "child": 1.0,
    "student": 0.6,
    "finance": 0.2,
    "normal": 0.3,
}

# 剧本阶段 → 会话进度（T-07）：0=未命中，1..4=接触/立威/隔离/诱导转账。
# 不同剧本的阶段名不一样（S02 是 recruit/small_gain/pay/trap），所以这里优先按
# 阶段权重折算，真正的序号由引擎按剧本内位置精确计算。
STAGE_WEIGHT_STEPS: tuple[float, ...] = (0.35, 0.6, 0.8)
# 进入「隔离/垫付」阶段以后，不再等出现转账字样才升级（T-07 的核心改动）
STAGE_FLOOR_FROM = 3
STAGE_FLOOR_SCORE = 60.0
# 阶段相似度低于该系数时，剧本命中不足以单独撑起 stage 维度
STAGE_MIN_SIM = 0.6
# 整段对话至少命中该数量的剧本信号，才认定"进了某个剧本"（防单一通用词误判）
STAGE_MIN_HITS = 2

# 案例召回门禁：相似度低于它的案例不进证据链。0.2 → 0.25 的原因见 docs/modules/decision.md：
# "词覆盖率"在短句上分辨率只到 0.2 的台阶（3/15 个通用词重叠就能到 0.2），
# 会把"我在地铁上，信号不太好，晚点回你电话"这类白样本推成 L2。
CASE_MIN_SIM = 0.25


def stage_index(script: ScriptHit | None) -> int:
    """按阶段权重估一个 0–4 的序号；引擎会用剧本内真实位置覆盖它。"""
    if script is None:
        return 0
    for position, threshold in enumerate(STAGE_WEIGHT_STEPS, start=1):
        if script.stage_weight <= threshold:
            return position
    return 4


def _has_code(evidences: list[Evidence], code: str) -> bool:
    return any(ev.code == code for ev in evidences)


def evaluate(
    evidences: list[Evidence],
    script: ScriptHit | None,
    role: str = "normal",
    stage_floor: float = 0.0,
) -> tuple[float, list[str], dict[str, float | None], bool]:
    """打分。``stage_floor`` 由引擎按会话历史传入（T-07 的单调阶段下限）。"""
    reasons: list[str] = []
    dims: dict[str, float | None] = {}

    # 1) 阶段：剧本走得越深越危险；直接的转账指令单列，因为它不需要剧本也能判定
    stage = 0.0
    if script is not None:
        # 阶段相似度 = stage_score / stage_weight（0.6–1.0）；低于下界说明只是擦边命中
        stage_sim = script.stage_score / script.stage_weight if script.stage_weight else 0.0
        if stage_sim >= STAGE_MIN_SIM:
            stage = script.stage_weight
            first_signal = script.matched_signals[0] if script.matched_signals else ""
            reasons.append(f"命中剧本「{script.name}」的“{script.stage_label}”阶段（如：{first_signal}）")
    if _has_code(evidences, "transfer_demand"):
        stage = max(stage, 0.85)
        reasons.append("出现“转账 / 验证码 / 安全账户”类直接指令")
    elif _has_code(evidences, "isolation"):
        stage = max(stage, 0.6)
        reasons.append("出现“保密 / 不许告诉他人”的隔离要求")

    # 话术链闭环：身份 + 隔离 + 转账同时出现，说明剧本已完整走完一遍
    chain = {"impersonate_authority", "isolation", "transfer_demand"}
    if sum(1 for code in chain if _has_code(evidences, code)) >= 3:
        stage = max(stage, 0.95)
        reasons.append("身份、隔离、转账三类话术同时出现（完整话术链）")

    case_similarities = [
        float(ev.meta.get("similarity", 0.0)) for ev in evidences if ev.kind == SourceKind.CASE
    ]
    if case_similarities:
        best_similarity = max(case_similarities)
        stage = max(stage, 0.55 + 0.4 * best_similarity)
        reasons.append(f"召回历史案例（相似度 {best_similarity:.0%}）")
    dims["stage"] = min(stage, 1.0)

    # 2) 可核验要素：链接 / 号码 / 卡号 / 引导加好友
    channel_evidences = [ev for ev in evidences if ev.category == "channel"]
    if channel_evidences:
        names = "、".join(ev.label for ev in channel_evidences)
        reasons.append(f"出现可核验要素：{names}")
        dims["entity"] = min(1.0, 0.5 * len(channel_evidences))
        dims["channel"] = 0.8
    else:
        dims["entity"] = None
        dims["channel"] = None

    # 3) 施压与催促
    pressure_evidences = [ev for ev in evidences if ev.category == "pressure"]
    if pressure_evidences:
        reasons.append("出现催促 / 限时 / 后果施压")
        dims["pressure"] = min(1.0, 0.34 * len(pressure_evidences))
    else:
        dims["pressure"] = None

    # 4) 多模态一致性：只有真的有两种以上模态时才计入
    modalities = {ev.modality for ev in evidences}
    if len(modalities) >= 2:
        dims["cross"] = min(1.0, 0.6 + 0.15 * (len(modalities) - 1))
        reasons.append(f"跨 {len(modalities)} 种模态证据互相印证")
    else:
        dims["cross"] = None

    # 5) 人群画像
    dims["profile"] = ROLE_PROFILE.get(role, ROLE_PROFILE["normal"])

    available = {key: value for key, value in dims.items() if value is not None}
    total_weight = sum(DIM_WEIGHTS[key] for key in available) or 1.0
    raw = sum(DIM_WEIGHTS[key] * float(value) for key, value in available.items()) / total_weight
    score = raw * 100 + ROLE_BIAS.get(role, 0.0)
    score = max(0.0, min(100.0, score))

    # 阶段下限：会话只要进过「隔离」阶段，本轮分数不低于 L2 门槛（单调不回退）
    if stage_floor > 0 and score < stage_floor:
        score = stage_floor
        reasons.append(f"会话已进入隔离/转账阶段，按阶段下限给到 {stage_floor:.0f} 分（不等转账字样）")

    cap_applied = False
    has_kb_support = script is not None or bool(case_similarities)
    if not has_kb_support:
        score = min(score, CAP_WITHOUT_EVIDENCE)
        cap_applied = True
        reasons.append(f"无剧本 / 案例证据支撑，分数封顶 {CAP_WITHOUT_EVIDENCE:.0f}")

    if not reasons:
        reasons.append("未发现明显诈骗特征")

    return round(score, 1), reasons, dims, cap_applied
