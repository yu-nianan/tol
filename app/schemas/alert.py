"""分级与决策：阈值、画像偏移、无证据封顶，都集中在这里。

改阈值只改这一处 —— 测试与文档都以本文件为准。
"""

from __future__ import annotations

from enum import Enum, IntEnum

from pydantic import BaseModel, Field

from app.schemas.evidence import Evidence


class Level(IntEnum):
    L0 = 0  # 只记录
    L1 = 1  # 提醒
    L2 = 2  # 警告
    L3 = 3  # 紧急（通知监护人）

    @property
    def label(self) -> str:
        return {
            Level.L0: "L0 仅记录",
            Level.L1: "L1 提醒",
            Level.L2: "L2 警告",
            Level.L3: "L3 紧急",
        }[self]


# 分数 ≥ 阈值即进入该级；从高到低匹配
LEVEL_THRESHOLD: tuple[tuple[float, Level], ...] = (
    (85.0, Level.L3),
    (60.0, Level.L2),
    (35.0, Level.L1),
)

# 同一分数，不同人群的实际风险不同 —— 用偏移表达，而不是写死四套阈值
ROLE_BIAS: dict[str, float] = {
    "elder": 8.0,
    "child": 10.0,
    "student": 5.0,
    "finance": -3.0,
    "normal": 0.0,
}

# 没有剧本/案例证据支撑时，分数不允许越过此线（压幻觉）
CAP_WITHOUT_EVIDENCE = 60.0


def level_for(score: float) -> Level:
    for threshold, level in LEVEL_THRESHOLD:
        if score >= threshold:
            return level
    return Level.L0


class ScriptHit(BaseModel):
    """命中的诈骗剧本与所处阶段 —— 报告和答辩里最常用的一句解释。"""

    script_id: str
    name: str
    stage_name: str
    stage_label: str
    stage_weight: float = Field(..., ge=0.0, le=1.0)
    risk_base: int = 90
    advice: list[str] = Field(default_factory=list)
    matched_signals: list[str] = Field(default_factory=list)

    @property
    def stage_score(self) -> float:
        return round(self.stage_weight, 3)


class Decision(BaseModel):
    score: float = Field(..., ge=0.0, le=100.0)
    level: Level
    script: ScriptHit | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    cap_applied: bool = False
    need_human: bool = False
    # 阶段序号 0=未命中剧本，1..4=接触/立威/隔离/诱导转账（T-07）
    stage_index: int = Field(0, ge=0, le=4)
    # 本次判定引用的历史案例 id（T-08）；无引用时为空
    cited_case_ids: list[str] = Field(default_factory=list)

    @property
    def level_label(self) -> str:
        return self.level.label


class AlertStatus(str, Enum):
    OPEN = "open"
    ACKED = "acked"
    DISMISSED = "dismissed"


class Alert(BaseModel):
    id: str
    session_id: str
    score: float
    level: Level
    script_name: str = ""
    created_at: str = ""
    status: AlertStatus = AlertStatus.OPEN
    actions: list[str] = Field(default_factory=list)

    @property
    def level_label(self) -> str:
        return self.level.label
