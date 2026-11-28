"""检测入口：文本 / 音频 / 图片共用一条 Decision 链路。

音频与图片都先走本模块的处理链（VAD 切段 / OCR），拿到文本后再进同一个引擎；
没有转写或识别引擎时返回 501 并说明原因，**不编造内容**。

上传限制（三层，实现在 ``app/core/limits.py``）：

1. 中间件看 ``Content-Length``，超上限在进路由前就 413；
2. 本模块用 ``read_limited`` 按上限读，**不把整个大文件读进内存**；
3. 读到的字节按魔数判类型，扩展名撒谎（如 zip 改名 .png）一律 415。

本模块**不碰** ``app/pipelines/audio/`` 下的任何东西：音频切分与分段识别归 T-13。
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from app.core.errors import AppError
from app.core.limits import (
    AUDIO_MAGIC,
    IMAGE_MAGIC,
    MAX_AUDIO_BYTES,
    MAX_IMAGE_BYTES,
    has_magic,
    read_limited,
)
from app.pipelines.audio.asr import UnsupportedAudioFormat, transcribe
from app.pipelines.decision.engine import get_engine
from app.pipelines.vision.ocr import (
    ImageTooLarge,
    UnsupportedImageFormat,
    extract_text,
)
from app.schemas import DetectResponse, DetectTextRequest

router = APIRouter(prefix="/api/v1", tags=["detect"])


def _detect(text: str, session_id: str, role: str) -> DetectResponse:
    engine = get_engine()
    alert, decision, latency_ms = engine.detect_text(text=text, session_id=session_id, role=role)
    return DetectResponse(
        session_id=session_id,
        decision=decision,
        alert=alert,
        latency_ms=round(latency_ms, 1),
    )


def _suffix_of(filename: str | None, fallback: str) -> str:
    if not filename or "." not in filename:
        return fallback
    return "." + filename.rsplit(".", 1)[-1].lower()


@router.post("/detect/text", response_model=DetectResponse, summary="文本检测")
def detect_text(payload: DetectTextRequest) -> DetectResponse:
    return _detect(payload.text, payload.session_id, payload.role)


@router.post("/detect/audio", response_model=DetectResponse, summary="音频检测（VAD 切段 + 可选 ASR）")
async def detect_audio(
    file: UploadFile = File(..., description="录音文件，wav"),
    session_id: str = Form("default"),
    role: str = Form("normal"),
) -> DetectResponse:
    data = await read_limited(file, MAX_AUDIO_BYTES)
    if not has_magic(data, AUDIO_MAGIC):
        raise AppError(
            "不是合法的 wav 文件（缺少 RIFF 文件头）；扩展名不能作为格式依据",
            code="unsupported_audio_format",
            status=415,
        )
    suffix = _suffix_of(file.filename, ".wav")
    try:
        transcript = transcribe(data, suffix=suffix)
    except UnsupportedAudioFormat as exc:
        raise AppError(str(exc), code="unsupported_audio_format", status=415) from exc
    if not transcript.text.strip():
        raise AppError(
            f"音频已切出 {transcript.segment_count} 段，但未接入 ASR 模型（backend={transcript.backend}），"
            "无法转写；请改用文本检测或配置 ASR",
            code="asr_not_configured",
            status=501,
        )
    return _detect(transcript.text, session_id, role)


@router.post("/detect/image", response_model=DetectResponse, summary="图片检测（OCR + 可选版面）")
async def detect_image(
    file: UploadFile = File(..., description="截图，png/jpg"),
    session_id: str = Form("default"),
    role: str = Form("normal"),
) -> DetectResponse:
    data = await read_limited(file, MAX_IMAGE_BYTES)
    if not has_magic(data, IMAGE_MAGIC):
        raise AppError(
            "只支持 PNG / JPEG（按文件头判断）；扩展名不能作为格式依据",
            code="unsupported_image_format",
            status=415,
        )
    try:
        result = extract_text(data)
    except UnsupportedImageFormat as exc:
        raise AppError(str(exc), code="unsupported_image_format", status=415) from exc
    except ImageTooLarge as exc:
        raise AppError(str(exc), code="image_too_large", status=413) from exc
    if not result.text.strip():
        raise AppError(
            f"图片 {result.width}x{result.height} 已解析，但未接入 OCR 引擎（backend={result.backend}），"
            "无法识别文字；请安装 tesseract 或设置 OCR_CLI",
            code="ocr_not_configured",
            status=501,
        )
    return _detect(result.text, session_id, role)
