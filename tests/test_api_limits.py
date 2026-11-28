"""上传体积与类型：三层防护各测一遍，且不破坏现有的 501 行为。"""

from __future__ import annotations

import io
import wave

from fastapi.testclient import TestClient

from app.core.limits import MAX_AUDIO_BYTES, MAX_IMAGE_BYTES, MAX_REQUEST_BYTES
from app.main import app

client = TestClient(app)


def _wav_bytes(samples: list[int], rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in samples))
    return buffer.getvalue()


def _pad(payload: bytes, size: int) -> bytes:
    """把 payload 补零到指定字节数，用来造"刚好超上限"的文件。"""
    assert size >= len(payload)
    return payload + b"\x00" * (size - len(payload))


def test_audio_over_limit_returns_413() -> None:
    payload = _pad(_wav_bytes([0] * 8), MAX_AUDIO_BYTES + 4)
    response = client.post(
        "/api/v1/detect/audio",
        files={"file": ("big.wav", payload, "audio/wav")},
        data={"session_id": "limit-audio", "role": "normal"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_image_over_limit_returns_413() -> None:
    payload = _pad(b"\x89PNG\r\n\x1a\n", MAX_IMAGE_BYTES + 4)
    response = client.post(
        "/api/v1/detect/image",
        files={"file": ("big.png", payload, "image/png")},
        data={"session_id": "limit-image", "role": "normal"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_audio_without_riff_header_returns_415() -> None:
    response = client.post(
        "/api/v1/detect/audio",
        files={"file": ("fake.wav", b"hello", "audio/wav")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_audio_format"


def test_zip_renamed_as_png_returns_415() -> None:
    response = client.post(
        "/api/v1/detect/image",
        files={"file": ("fake.png", b"PK\x03\x04" + b"\x00" * 32, "image/png")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_image_format"


def test_small_wav_still_returns_501_not_configured() -> None:
    """限制不能改变原有行为：合法小文件仍走 VAD，没有 ASR 就如实 501。"""
    response = client.post(
        "/api/v1/detect/audio",
        files={"file": ("ok.wav", _wav_bytes([0, 8000, -8000, 0] * 400), "audio/wav")},
        data={"session_id": "limit-ok-audio", "role": "elder"},
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "asr_not_configured"


def test_small_png_still_returns_501_not_configured() -> None:
    """1x1 的合法 PNG：解析得出来，但没装 OCR → 501。"""
    png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\x0d\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = client.post(
        "/api/v1/detect/image",
        files={"file": ("ok.png", png, "image/png")},
        data={"session_id": "limit-ok-image", "role": "normal"},
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "ocr_not_configured"


def test_request_body_over_limit_rejected_before_route() -> None:
    """中间件兜底：既不是音频也不是图片的路由，超大请求体一样 413。"""
    oversized = b"x" * (MAX_REQUEST_BYTES + 1)
    response = client.post(
        "/api/v1/kb/cases",
        content=oversized,
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
