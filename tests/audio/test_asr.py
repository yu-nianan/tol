"""T-02 验收：wav → 能量 VAD 切段 → Transcript 契约（无模型时诚实降级）。"""

from __future__ import annotations

import io
import math
import wave
from array import array

import pytest

from app.pipelines.audio.asr import (
    MAX_SEGMENTS,
    Segment,
    Transcript,
    UnsupportedAudioFormat,
    transcribe,
)

SAMPLE_RATE = 16000


def _wav_bytes(
    samples: list[int],
    *,
    rate: int = SAMPLE_RATE,
    channels: int = 1,
    sampwidth: int = 2,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sampwidth)
        writer.setframerate(rate)
        writer.writeframes(array("h", samples).tobytes() if sampwidth == 2 else bytes(samples))
    return buffer.getvalue()


def _sine(
    duration_s: float,
    *,
    rate: int = SAMPLE_RATE,
    freq: float = 440.0,
    amplitude: int = 32767,
) -> list[int]:
    count = int(duration_s * rate)
    return [int(amplitude * math.sin(2 * math.pi * freq * index / rate)) for index in range(count)]


def _silence(duration_s: float, *, rate: int = SAMPLE_RATE) -> list[int]:
    return [0] * int(duration_s * rate)


def test_transcribe_sine_returns_single_segment_without_fake_text() -> None:
    transcript = transcribe(_wav_bytes(_sine(1.0)))

    assert isinstance(transcript, Transcript)
    assert transcript.text == ""  # 没模型绝不编造文本
    assert transcript.backend == "energy-vad-only"
    assert transcript.confidence == 0.0
    assert len(transcript.segments) == 1
    segment = transcript.segments[0]
    assert isinstance(segment, Segment)
    assert segment.start_s == 0.0
    assert abs(segment.end_s - 1.0) <= 0.02
    assert segment.rms > 0.6
    assert abs(transcript.duration_s - 1.0) < 1e-6


def test_transcribe_all_silence_has_no_speech_segment() -> None:
    transcript = transcribe(_wav_bytes(_silence(1.0)))

    assert len(transcript.segments) <= 1
    assert transcript.text == ""
    assert transcript.confidence == 0.0
    assert abs(transcript.duration_s - 1.0) < 0.02


def test_transcribe_garbage_bytes_raises_unsupported_audio_format() -> None:
    with pytest.raises(UnsupportedAudioFormat):
        transcribe(b"\x00\x01not-a-wav\xff" * 8)


def test_transcribe_empty_bytes_raises_unsupported_audio_format() -> None:
    with pytest.raises(UnsupportedAudioFormat):
        transcribe(b"")


def test_transcribe_non_wav_suffix_raises_unsupported_audio_format() -> None:
    with pytest.raises(UnsupportedAudioFormat):
        transcribe(_wav_bytes(_sine(0.2)), suffix=".mp3")


def test_transcribe_8bit_wav_raises_unsupported_audio_format() -> None:
    with pytest.raises(UnsupportedAudioFormat):
        transcribe(_wav_bytes([128] * 8000, rate=8000, sampwidth=1))


def test_transcribe_48k_stereo_stays_within_duration_tolerance() -> None:
    left = _sine(1.5, rate=48000)
    interleaved: list[int] = []
    for value in left:
        interleaved.extend((value, value))

    transcript = transcribe(_wav_bytes(interleaved, rate=48000, channels=2))

    assert abs(transcript.duration_s - 1.5) / 1.5 < 0.05
    assert len(transcript.segments) == 1
    assert transcript.text == ""


def test_transcribe_tone_silence_tone_splits_into_two_segments() -> None:
    samples = _sine(0.5) + _silence(0.5) + _sine(0.5)

    transcript = transcribe(_wav_bytes(samples))

    assert len(transcript.segments) == 2
    assert transcript.segments[0].end_s <= 0.51
    assert transcript.segments[1].start_s >= 0.99


def test_transcribe_60s_silence_plus_tone_is_a_single_segment() -> None:
    transcript = transcribe(_wav_bytes(_silence(60.0) + _sine(1.0)))

    assert len(transcript.segments) <= MAX_SEGMENTS
    assert len(transcript.segments) == 1
    assert abs(transcript.duration_s - 61.0) < 0.05


def test_transcribe_many_bursts_never_exceeds_segment_cap() -> None:
    samples: list[int] = []
    for _ in range(220):
        samples.extend(_sine(0.1))
        samples.extend(_silence(0.4))

    transcript = transcribe(_wav_bytes(samples))

    assert len(transcript.segments) == MAX_SEGMENTS
