"""报告：赛题里说"识别结论、证据链、防范建议、监护记录"，这里就四段。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Report(BaseModel):
    session_id: str
    generated_at: str
    risk_summary: dict[str, object] = Field(default_factory=dict)
    evidence_chain: list[dict[str, object]] = Field(default_factory=list)
    script_match: dict[str, object] = Field(default_factory=dict)
    advice: list[str] = Field(default_factory=list)
    notifications: list[dict[str, object]] = Field(default_factory=list)
    turns: int = 0
    disclaimer: str = "本报告由原型系统自动生成，仅用于演练与教学，不构成法律意见。"

    def is_complete(self) -> bool:
        return all(
            [
                bool(self.risk_summary),
                bool(self.evidence_chain),
                bool(self.advice),
            ]
        )
