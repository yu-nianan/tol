"""音频/图片入口：没有模型时必须明确 501，且不许编造识别文本。"""

from __future__ import annotations

import io
import wave

from fastapi.testclient import TestClient

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


def test_audio_without_asr_returns_501_not_fake_text() -> None:
    payload = _wav_bytes([0, 8000, -8000, 0] * 400)
    response = client.post(
        "/api/v1/detect/audio",
        files={"file": ("sample.wav", payload, "audio/wav")},
        data={"session_id": "audio-1", "role": "elder"},
    )
    assert response.status_code == 501
    body = response.json()["error"]
    assert body["code"] == "asr_not_configured"
    assert "energy-vad-only" in body["message"]


def test_audio_bad_container_returns_415() -> None:
    response = client.post(
        "/api/v1/detect/audio",
        files={"file": ("sample.mp3", b"ID3\x03\x00\x00\x00", "audio/mpeg")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_audio_format"


def test_image_without_ocr_returns_501_not_fake_text() -> None:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    response = client.post(
        "/api/v1/detect/image",
        files={"file": ("shot.png", png, "image/png")},
        data={"session_id": "img-1", "role": "normal"},
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "ocr_not_configured"


def test_image_bad_format_returns_415() -> None:
    response = client.post(
        "/api/v1/detect/image",
        files={"file": ("note.bmp", b"BM\x00\x00\x00\x00", "image/bmp")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_image_format"


def test_report_lists_text_and_media_turns(tmp_path) -> None:  # type: ignore[no-untyped-def]
    text_response = client.post(
        "/api/v1/detect/text",
        json={"text": "我是警察，你涉嫌洗钱，现在把钱转到安全账户", "session_id": "mix-1", "role": "elder"},
    )
    assert text_response.status_code == 200
    report = client.get("/api/v1/report/mix-1")
    assert report.status_code == 200
    payload = report.json()["report"]
    assert payload["turns"] >= 1
    assert payload["evidence_chain"]
