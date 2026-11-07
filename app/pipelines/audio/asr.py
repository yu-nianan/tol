"""音频链路骨架：wav → 静音切段 → 转写契约。

纯标准库（wave / array / struct），不引入任何第三方依赖。
没接模型时只做能量 VAD：``backend="energy-vad-only"``、``text=""``、``confidence=0.0``，
绝不编造转写结果；模型接入是后续任务单的事。

契约（冻结，接口层按这个调）::

    @dataclass
    class Segment:
        start_s: float
        end_s: float
        rms: float

    @dataclass
    class Transcript:
        text: str
        segments: list[Segment]
        duration_s: float
        backend: str        # "energy-vad-only" / "funasr" / "mock"
        confidence: float   # 没接模型时必须是 0.0

    def transcribe(audio_bytes: bytes, suffix: str = ".wav") -> Transcript: ...
"""

from __future__ import annotations

import io
import math
import sys
import wave
from array import array
from dataclasses import dataclass, field

# 统一到 16k 单声道：后面的切段、模型都只认这一种输入
TARGET_SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = TARGET_SAMPLE_RATE * FRAME_MS // 1000  # 480
SILENCE_MS = 300
SILENCE_SAMPLES = TARGET_SAMPLE_RATE * SILENCE_MS // 1000
MAX_SEGMENTS = 200
# 阈值 = 全片峰值能量的 0.15 倍；低于它的帧算静音
PEAK_RATIO = 0.15
SUPPORTED_SUFFIXES = (".wav", ".wave")

# 没接模型：接口/健康检查用这两个常量，别让下游误以为 ASR 已启用
ASR_ENABLED = False
ASR_BACKEND = "energy-vad-only"


class UnsupportedAudioFormat(ValueError):
    """音频格式不支持：非 wav、非 PCM、非 16bit 都走这里。"""


class ASRNotConfigured(RuntimeError):
    """兼容旧接口层的异常名：本骨架不再抛它，但接口 import 不能断。"""

    def __init__(self) -> None:
        super().__init__("ASR 模型未接入：当前只有能量 VAD 与切段骨架（见 docs/tickets/T-02）")


@dataclass
class Segment:
    """一段连续有声区间。"""

    start_s: float
    end_s: float
    rms: float

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)


@dataclass
class Transcript:
    """转写结果。没接模型时 text=""、confidence=0.0，segments 仍可用于定位。"""

    text: str
    segments: list[Segment] = field(default_factory=list)
    duration_s: float = 0.0
    backend: str = ASR_BACKEND
    confidence: float = 0.0

    @property
    def segment_count(self) -> int:
        return len(self.segments)


def transcribe(audio_bytes: bytes, suffix: str = ".wav") -> Transcript:
    """把音频切成静音段并返回契约对象。

    没接模型时不会抛异常：返回 ``backend="energy-vad-only"``、空文本、置信度 0。
    格式不支持（非 wav / 非 PCM / 非 16bit / 乱码字节）才抛 ``UnsupportedAudioFormat``。
    """
    if not audio_bytes:
        raise UnsupportedAudioFormat("音频内容为空")
    if suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedAudioFormat(f"暂不支持 {suffix}：当前只解析 PCM 16bit wav")

    rate, channels, samples = _read_wav(audio_bytes)
    if not samples:
        return Transcript(text="", segments=[], duration_s=0.0)

    mono = _to_mono(samples, channels)
    resampled = _resample(mono, rate, TARGET_SAMPLE_RATE)
    duration_s = round(len(resampled) / TARGET_SAMPLE_RATE, 3)
    frame_rms = [
        _frame_rms(resampled, start) for start in range(0, len(resampled), FRAME_SAMPLES)
    ]
    segments = _split_segments(frame_rms, len(resampled))
    # 模型未接入：诚实返回空文本，segments 只表达"哪里有人声"
    return Transcript(
        text="",
        segments=segments,
        duration_s=duration_s,
        backend=ASR_BACKEND,
        confidence=0.0,
    )


def _read_wav(audio_bytes: bytes) -> tuple[int, int, array]:
    """读 wav 头 + 原始采样；非 PCM / 非 16bit / 坏文件都抛 UnsupportedAudioFormat。"""
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as reader:
            if reader.getcomptype() != "NONE":
                raise UnsupportedAudioFormat(
                    f"只支持 PCM，收到压缩格式 {reader.getcomptype()}"
                )
            if reader.getsampwidth() != 2:
                raise UnsupportedAudioFormat(
                    f"只支持 16bit，收到 {reader.getsampwidth() * 8}bit"
                )
            rate = reader.getframerate()
            channels = reader.getnchannels()
            raw = reader.readframes(reader.getnframes())
    except (wave.Error, EOFError) as exc:
        raise UnsupportedAudioFormat(f"不是合法的 wav 文件：{exc}") from exc

    if rate <= 0 or channels <= 0:
        raise UnsupportedAudioFormat(f"wav 头异常：rate={rate} channels={channels}")

    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return rate, channels, samples


def _to_mono(samples: array, channels: int) -> array:
    """立体声（或多声道）按算术平均混成单声道。"""
    if channels == 1:
        return samples
    mono = array("h")
    for index in range(0, len(samples) - channels + 1, channels):
        total = 0
        for offset in range(channels):
            total += samples[index + offset]
        mono.append(int(total / channels))
    return mono


def _resample(samples: array, source_rate: int, target_rate: int) -> array:
    """最近邻重采样：够用，不追求音质，也不引入依赖。"""
    if source_rate == target_rate or not samples:
        return samples
    count = max(1, round(len(samples) * target_rate / source_rate))
    last = len(samples) - 1
    return array(
        "h",
        (
            samples[min(last, int(index * source_rate / target_rate))]
            for index in range(count)
        ),
    )


def _frame_rms(samples: array, start: int) -> float:
    """一帧（30ms）的 RMS，归一化到 0..1。"""
    end = min(start + FRAME_SAMPLES, len(samples))
    if end <= start:
        return 0.0
    total = 0
    for value in samples[start:end]:
        total += value * value
    return math.sqrt(total / (end - start)) / 32768.0


def _split_segments(frame_rms: list[float], total_samples: int) -> list[Segment]:
    """能量 VAD：连续静音 ≥300ms 切一刀，段数封顶 200。"""
    peak = max(frame_rms) if frame_rms else 0.0
    if peak <= 0.0:
        # 全静音：没有可切的有声段
        return []
    threshold = peak * PEAK_RATIO
    silence_frames = max(1, SILENCE_SAMPLES // FRAME_SAMPLES)

    segments: list[Segment] = []
    start_frame: int | None = None
    last_active = 0
    silent_run = 0
    for index, value in enumerate(frame_rms):
        if value >= threshold:
            if start_frame is None:
                start_frame = index
            last_active = index
            silent_run = 0
            continue
        if start_frame is None:
            continue
        silent_run += 1
        if silent_run >= silence_frames:
            segments.append(
                _build_segment(frame_rms, start_frame, last_active, total_samples)
            )
            start_frame = None
            silent_run = 0
            if len(segments) >= MAX_SEGMENTS:
                return segments

    if start_frame is not None:
        segments.append(_build_segment(frame_rms, start_frame, last_active, total_samples))
    return segments[:MAX_SEGMENTS]


def _build_segment(
    frame_rms: list[float], start_frame: int, last_active: int, total_samples: int
) -> Segment:
    start_s = round(start_frame * FRAME_SAMPLES / TARGET_SAMPLE_RATE, 3)
    end_sample = min((last_active + 1) * FRAME_SAMPLES, total_samples)
    end_s = round(end_sample / TARGET_SAMPLE_RATE, 3)
    window = frame_rms[start_frame : last_active + 1]
    rms = round(sum(window) / len(window), 3) if window else 0.0
    return Segment(start_s=start_s, end_s=end_s, rms=rms)
