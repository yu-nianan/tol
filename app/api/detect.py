"""检测入口：文本已通，音频/图片留了明确 501 的占位（不假装支持）。"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from app.core.errors import AppError
from app.pipelines.audio.asr import ASRNotConfigured, transcribe
from app.pipelines.decision.engine import get_engine
from app.pipelines.vision.ocr import OCRNotConfigured, extract_text
from app.schemas import DetectResponse, DetectTextRequest

router = APIRouter(prefix="/api/v1", tags=["detect"])


@router.post("/detect/text", response_model=DetectResponse, summary="文本检测")
def detect_text(payload: DetectTextRequest) -> DetectResponse:
    engine = get_engine()
    alert, decision, latency_ms = engine.detect_text(
        text=payload.text,
        session_id=payload.session_id,
        role=payload.role,
    )
    return DetectResponse(
        session_id=payload.session_id,
        decision=decision,
        alert=alert,
        latency_ms=round(latency_ms, 1),
    )


@router.post("/detect/audio", response_model=DetectResponse, summary="音频检测（待接入 ASR）")
async def detect_audio(
    file: UploadFile = File(..., description="录音文件，wav/mp3"),
    session_id: str = Form("default"),
    role: str = Form("normal"),
) -> DetectResponse:
    data = await file.read()
    try:
        text = transcribe(data)
    except ASRNotConfigured as exc:
        raise AppError(str(exc), code="asr_not_configured", status=501) from exc
    engine = get_engine()
    alert, decision, latency_ms = engine.detect_text(text=text, session_id=session_id, role=role)
    return DetectResponse(
        session_id=session_id,
        decision=decision,
        alert=alert,
        latency_ms=round(latency_ms, 1),
    )


@router.post("/detect/image", response_model=DetectResponse, summary="图片检测（待接入 OCR）")
async def detect_image(
    file: UploadFile = File(..., description="截图，png/jpg"),
    session_id: str = Form("default"),
    role: str = Form("normal"),
) -> DetectResponse:
    data = await file.read()
    try:
        text = extract_text(data)
    except OCRNotConfigured as exc:
        raise AppError(str(exc), code="ocr_not_configured", status=501) from exc
    engine = get_engine()
    alert, decision, latency_ms = engine.detect_text(text=text, session_id=session_id, role=role)
    return DetectResponse(
        session_id=session_id,
        decision=decision,
        alert=alert,
        latency_ms=round(latency_ms, 1),
    )
