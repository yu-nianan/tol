"""跨模态矛盾：语音合成痕迹的启发式检测（T-10 / FR-2.4b）。

纯标准库，不联网、不训练模型，只看能量包络的统计形态：

- 静音段占比过高：TTS 拼接出来的音频常常"说话—停顿"分得太干净；
- 能量平台期过长：真实人声有起伏，合成音容易长时间贴在同一个电平；
- 爆破音缺失：正常语音里 p/t/k 之类的瞬态会让能量从近静音跳到高值；
- 停顿等长：真人停顿长短差异大，合成音的停顿往往长度接近。

**这只是启发式，输出的是「疑似」，不是深度伪造检测器。**
单一信号不足以定性，只有多个信号叠加时 confidence 才会明显升高。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.pipelines.audio.asr import Transcript
from app.schemas import Evidence, Modality, SourceKind

FRAME_MS = 30  # 与 asr.py 的 FRAME_MS 对齐，包络按 30ms 一帧
SILENCE_CUT = 0.02  # 帧能量低于峰值的 2% 算静音
SILENCE_RATIO_HIGH = 0.45
PLATEAU_CUT = 0.90  # 帧能量 ≥ 峰值 90% 算平台期
PLATEAU_RATIO_HIGH = 0.60
MIN_PAUSE_FRAMES = 10  # 300ms 以上的连续静音才算一个停顿
MIN_PAUSES = 3
PAUSE_CV_LOW = 0.25  # 停顿长度的变异系数低于它 → 疑似等长
TRANSIENT_PREV_CUT = 0.08  # 爆破音：前一帧接近静音
TRANSIENT_CUT = 0.50  # 本帧冲到峰值的一半以上
MAX_ONSET_GAP_FRAMES = 2  # 只有 ≤60ms 的短间隙起振才算，长停顿后的开口音不算
TRANSIENT_RATE_LOW = 0.4  # 每秒爆破音次数低于它 → 疑似缺失
MAX_CONFIDENCE = 0.95

# 每个信号的加权；四个全中 = 0.90，不做"一票定性"
SIGNAL_WEIGHTS = {
    "silence_ratio_high": 0.30,
    "plateau_ratio_high": 0.25,
    "plosive_missing": 0.20,
    "pause_uniformity": 0.15,
}
NOTE = "启发式，疑似，不是深度伪造检测器"


def audio_artifacts(envelope: Sequence[float] | Transcript | None) -> Evidence:
    """根据帧能量包络给出「疑似合成音」证据。

    ``envelope`` 可以是 30ms 一帧的归一化能量序列，也可以是 T-02 的 ``Transcript``
    （函数只读公开字段 ``duration_s`` / ``segments``，不碰 asr 的内部实现）。
    没有输入或全是静音时返回 confidence=0.0 的证据，不抛异常。
    """
    values, source = _to_envelope(envelope)
    meta: dict = {"source": source, "note": NOTE, "signal": "heuristic"}
    if len(values) < MIN_PAUSE_FRAMES:
        meta["reason"] = "包络为空或过短"
        return _evidence(0.0, "没有可分析的音频包络", meta)

    peak = max(values)
    if peak <= 0:
        meta["reason"] = "全片静音，无法判断"
        return _evidence(0.0, "音频全片静音", meta)

    silent = [value <= peak * SILENCE_CUT for value in values]
    silence_ratio = sum(silent) / len(values)
    active_count = len(values) - sum(silent)
    plateau_count = sum(
        1 for index, value in enumerate(values) if not silent[index] and value >= peak * PLATEAU_CUT
    )
    plateau_ratio = plateau_count / active_count if active_count else 0.0
    pauses = _silence_runs(silent, min_frames=MIN_PAUSE_FRAMES)
    pause_cv = _cv(pauses)
    duration_s = len(values) * FRAME_MS / 1000
    transient_count = _transient_count(values, peak, silent)
    transient_rate = transient_count / duration_s if duration_s else 0.0

    fired: list[str] = []
    if silence_ratio >= SILENCE_RATIO_HIGH:
        fired.append("silence_ratio_high")
    if plateau_ratio >= PLATEAU_RATIO_HIGH:
        fired.append("plateau_ratio_high")
    if transient_rate < TRANSIENT_RATE_LOW:
        fired.append("plosive_missing")
    if len(pauses) >= MIN_PAUSES and pause_cv <= PAUSE_CV_LOW:
        fired.append("pause_uniformity")

    confidence = min(MAX_CONFIDENCE, sum(SIGNAL_WEIGHTS[name] for name in fired))
    meta.update(
        {
            "frames": len(values),
            "duration_s": round(duration_s, 2),
            "silence_ratio": round(silence_ratio, 3),
            "plateau_ratio": round(plateau_ratio, 3),
            "transient_rate": round(transient_rate, 3),
            "pause_count": len(pauses),
            "pause_cv": None if pause_cv is None else round(pause_cv, 3),
            "signals": fired,
            "signal_detail": {
                name: {
                    "fired": name in fired,
                    "weight": SIGNAL_WEIGHTS[name],
                }
                for name in SIGNAL_WEIGHTS
            },
        }
    )
    text = (
        f"静音占比 {silence_ratio:.0%}、平台期 {plateau_ratio:.0%}、"
        f"爆破音 {transient_rate:.1f} 次/秒、停顿 {len(pauses)} 段"
    )
    return _evidence(confidence, text, meta)


def _to_envelope(envelope: Sequence[float] | Transcript | None) -> tuple[list[float], str]:
    if envelope is None:
        return [], "empty"
    if isinstance(envelope, Transcript):
        return _envelope_from_transcript(envelope), "transcript"
    values = [max(0.0, float(value)) for value in envelope]
    return values, "envelope"


def _envelope_from_transcript(transcript: Transcript) -> list[float]:
    """把 SpeechSegment 的时间段铺回 30ms 帧：段内取 rms，段间为 0。"""
    frames = int(round(max(0.0, float(transcript.duration_s)) * 1000 / FRAME_MS))
    if frames <= 0:
        return []
    values = [0.0] * frames
    for segment in transcript.segments:
        start = max(0, int(round(float(segment.start_s) * 1000 / FRAME_MS)))
        end = min(frames, int(round(float(segment.end_s) * 1000 / FRAME_MS)))
        level = max(0.0, float(segment.rms))
        for index in range(start, end):
            values[index] = level
    return values


def _silence_runs(silent: list[bool], min_frames: int) -> list[int]:
    runs: list[int] = []
    length = 0
    for is_silent in silent:
        if is_silent:
            length += 1
        elif length:
            if length >= min_frames:
                runs.append(length)
            length = 0
    if length >= min_frames:
        runs.append(length)
    return runs


def _transient_count(values: list[float], peak: float, silent: list[bool]) -> int:
    """统计"爆破音"式瞬态：短促静音（≤60ms）后一帧冲到峰值一半以上。

    只算短间隙的起振，长停顿后的正常开口音不算——否则 TTS 的每个音节开头都会被当成爆破音。
    """
    count = 0
    silent_run = 0
    for index in range(1, len(values)):
        if silent[index - 1]:
            silent_run += 1
        else:
            silent_run = 0
        if silent[index]:
            continue
        if values[index] < peak * TRANSIENT_CUT:
            continue
        if values[index - 1] > peak * TRANSIENT_PREV_CUT:
            continue
        if silent_run <= MAX_ONSET_GAP_FRAMES:
            count += 1
    return count


def _cv(values: list[int]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return None
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return (variance**0.5) / mean


def _evidence(confidence: float, text: str, meta: dict) -> Evidence:
    confidence = max(0.0, min(1.0, float(confidence)))
    return Evidence(
        code="audio_synthetic_artifact",
        label="疑似合成语音痕迹",
        category="other",
        text=text,
        weight=confidence,
        confidence=confidence,
        modality=Modality.AUDIO,
        kind=SourceKind.CROSS_MODAL,
        meta=meta,
    )
