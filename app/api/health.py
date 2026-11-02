"""健康检查：给 Docker、冒烟脚本、以及"服务到底起没起"这个问题一个确定答案。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.pipelines.audio.asr import ASR_ENABLED
from app.pipelines.decision.engine import get_engine
from app.pipelines.vision.ocr import OCR_ENABLED
from app.schemas import HealthResponse

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse, summary="健康检查")
def health() -> HealthResponse:
    engine = get_engine()
    return HealthResponse(
        status="ok",
        version=settings.version,
        kb_scripts=engine.kb.script_count,
        kb_cases=engine.kb.case_count,
        llm_enabled=settings.llm_enabled,
        asr_enabled=ASR_ENABLED,
        ocr_enabled=OCR_ENABLED,
    )
