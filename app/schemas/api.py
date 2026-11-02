"""HTTP 层契约：前端、冒烟脚本、评测脚本都只认这里的字段。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.schemas.alert import Alert, Decision
from app.schemas.report import Report


class DetectTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000, description="用户输入的文本")
    session_id: str = Field("default", min_length=1, max_length=64)
    role: str = Field("normal", description="normal / elder / child / student / finance")

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("文本不能为空或全为空白字符")
        return stripped

    @field_validator("role")
    @classmethod
    def _role_allowed(cls, value: str) -> str:
        allowed = {"normal", "elder", "child", "student", "finance"}
        if value not in allowed:
            raise ValueError(f"role 必须是 {sorted(allowed)} 之一")
        return value


class DetectResponse(BaseModel):
    session_id: str
    decision: Decision
    alert: Alert | None = None
    latency_ms: float = 0.0


class AckRequest(BaseModel):
    action: str = Field("ack", description="ack / dismiss / confirm_false_positive")
    note: str = Field("", max_length=200)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    kb_scripts: int = 0
    kb_cases: int = 0
    llm_enabled: bool = False
    asr_enabled: bool = False
    ocr_enabled: bool = False


class ReportResponse(BaseModel):
    report: Report


class ErrorResponse(BaseModel):
    code: str
    message: str
