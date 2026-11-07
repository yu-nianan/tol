"""T-10：合成语音痕迹启发式（音频包络统计）。"""

from __future__ import annotations

import random

from app.pipelines.audio.artifacts import audio_artifacts
from app.pipelines.audio.asr import Segment, Transcript
from app.schemas import Modality, SourceKind


def _tts_like_envelope() -> list[float]:
    """合成音形态：等长平台期 + 等长停顿，且没有爆破音。"""
    values: list[float] = []
    for _ in range(5):
        values.extend([0.5] * 20)
        values.extend([0.0] * 20)
    return values


def _natural_envelope() -> list[float]:
    """接近真人的形态：停顿长短不一、有爆破音、能量有起伏。"""
    rng = random.Random(7)
    values = [rng.uniform(0.08, 0.55) for _ in range(300)]
    for start, length in ((40, 12), (120, 25), (230, 45)):
        for index in range(start, start + length):
            values[index] = 0.0
    for index in range(20, 300, 20):
        if values[index] == 0.0:
            continue
        values[index - 1] = 0.005
        values[index] = 0.85
    return values


def test_audio_artifacts_tts_like_envelope_fires_high_confidence() -> None:
    evidence = audio_artifacts(_tts_like_envelope())

    assert evidence.confidence >= 0.6
    assert evidence.kind == SourceKind.CROSS_MODAL
    assert evidence.modality == Modality.AUDIO
    assert "启发式" in evidence.meta["note"]
    assert evidence.meta["signals"]


def test_audio_artifacts_natural_envelope_stays_low() -> None:
    evidence = audio_artifacts(_natural_envelope())

    assert evidence.confidence <= 0.2
    assert evidence.kind == SourceKind.CROSS_MODAL


def test_audio_artifacts_all_silent_returns_zero() -> None:
    evidence = audio_artifacts([0.0] * 100)

    assert evidence.confidence == 0.0
    assert evidence.meta["reason"].startswith("全片静音")


def test_audio_artifacts_empty_input_returns_zero() -> None:
    for envelope in (None, [], [0.0] * 5):
        evidence = audio_artifacts(envelope)
        assert evidence.confidence == 0.0
        assert evidence.text


def test_audio_artifacts_transcript_segments_are_flagged() -> None:
    transcript = Transcript(
        text="",
        segments=[Segment(0.0, 1.0, 0.5), Segment(2.0, 3.0, 0.5)],
        duration_s=4.0,
    )

    evidence = audio_artifacts(transcript)

    assert evidence.confidence >= 0.4
    assert evidence.meta["source"] == "transcript"
