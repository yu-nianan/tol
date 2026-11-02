"""证据：模块之间、模型与规则之间唯一的交接格式。

一条证据 = "在原文的哪一段、看到了什么、由谁给出、有多确信"。
打分器只读证据，不读原始文本 —— 这样换模型、换规则都不影响下游。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Modality(str, Enum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"


class SourceKind(str, Enum):
    RULE = "rule"          # 关键词/正则
    MODEL = "model"        # 大模型结构化输出
    CASE = "case"          # 知识库案例召回
    SCRIPT = "script"      # 剧本阶段命中
    PROFILE = "profile"    # 画像（年龄/职业）


class Evidence(BaseModel):
    """最小证据单元。所有字段都可直接进报告，不需要二次加工。"""

    code: str = Field(..., description="证据代号，如 impersonate_authority")
    label: str = Field("", description="给评委看的中文名")
    category: str = Field(
        "other",
        description="stage_authority / stage_transfer / entity / pressure / channel / profile / other",
    )
    text: str = Field("", description="命中的原文片段（脱敏后）")
    weight: float = Field(0.0, ge=0.0, le=1.0, description="该证据的强度")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="该证据的可信度")
    modality: Modality = Modality.TEXT
    kind: SourceKind = SourceKind.RULE
    meta: dict[str, object] = Field(default_factory=dict)

    def key(self) -> tuple[str, str]:
        return (self.code, self.text[:40])


def dedupe(evidences: list[Evidence]) -> list[Evidence]:
    """同一代号 + 同一片段只保留权重最高的一条，避免同类证据重复计分。"""
    best: dict[tuple[str, str], Evidence] = {}
    for ev in evidences:
        k = ev.key()
        if k not in best or ev.weight > best[k].weight:
            best[k] = ev
    return list(best.values())
