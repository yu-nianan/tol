"""识别前的音频整理：标准库 PCM WAV → 16kHz / 单声道 / PCM16。

压缩录音不冒充已转码；调用者收到带留痕的明确错误后，可先在外部转为 WAV。
本模块只整理波形，不做转写、VAD 或诈骗判定，也不保存原始录音。
"""

from __future__ import annotations

import io
import struct
import sys
import wave
from array import array
from pathlib import Path

from ._records import MediaPreprocessError, MediaResult, _record

TARGET_RATE = 16000
MAX_DURATION_SECONDS = 180
MAX_INPUT_BYTES = 128 * 1024 * 1024
TARGET_PEAK = 28000
MAX_GAIN = 8.0
_COMPRESSED_SUFFIXES = {".m4a", ".aac", ".mp3", ".ogg", ".amr", ".silk", ".caf", ".flac"}
_CONVERSION_ADVICE = "请先转码为 PCM WAV（16bit、16000Hz、单声道）再上传；本次未进行识别。"


def _read_pcm(data: bytes) -> tuple[int, int, int, int, bytes]:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise MediaPreprocessError("invalid_audio", f"不是完整的 WAV 文件。{_CONVERSION_ADVICE}")
    container_end = int.from_bytes(data[4:8], "little") + 8
    if container_end > len(data) or container_end < 12:
        raise MediaPreprocessError("invalid_audio", "WAV 文件被截断或长度标记损坏，请重新导出完整录音。")
    try:
        with wave.open(io.BytesIO(data[:container_end]), "rb") as reader:
            rate, channels = reader.getframerate(), reader.getnchannels()
            width, frames = reader.getsampwidth(), reader.getnframes()
            if reader.getcomptype() != "NONE" or width not in (1, 2, 3, 4):
                raise MediaPreprocessError("unsupported_audio", f"仅支持整数 PCM WAV。{_CONVERSION_ADVICE}")
            if not 8000 <= rate <= 192000 or not 1 <= channels <= 8:
                raise MediaPreprocessError(
                    "unsupported_audio", f"仅支持 8–192kHz、1–8 声道的 PCM WAV。{_CONVERSION_ADVICE}"
                )
            if frames <= 0:
                raise MediaPreprocessError("empty_audio", "WAV 没有音频采样，请重新录制。")
            # wave 按整帧取整；另查 data 块，不能把半帧或缺失数据当成有效录音。
            position = 12
            while position + 8 <= container_end:
                size = int.from_bytes(data[position + 4 : position + 8], "little")
                chunk_end = position + 8 + size
                if chunk_end > container_end:
                    raise MediaPreprocessError("invalid_audio", "WAV 数据块不完整，请重新导出完整录音。")
                if data[position : position + 4] == b"data":
                    if size % (channels * width):
                        raise MediaPreprocessError("invalid_audio", "WAV 含不完整的采样帧，请重新导出。")
                    break
                position = chunk_end + size % 2
            selected_frames = min(frames, MAX_DURATION_SECONDS * rate)
            raw = reader.readframes(selected_frames)
            if len(raw) != selected_frames * channels * width:
                raise MediaPreprocessError("invalid_audio", "WAV 音频数据被截断，请重新导出完整录音。")
    except (wave.Error, EOFError, struct.error) as exc:
        raise MediaPreprocessError("invalid_audio", f"无法解析 WAV。{_CONVERSION_ADVICE}") from exc
    return rate, channels, width, frames, raw


def _mono_samples(raw: bytes, channels: int, width: int) -> array:
    if width == 2:
        samples = array("h")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()
    elif width == 1:
        samples = array("h", ((value - 128) * 256 for value in raw))
    else:
        shift = (width - 2) * 8
        samples = array(
            "h",
            (int.from_bytes(raw[index : index + width], "little", signed=True) >> shift
             for index in range(0, len(raw), width)),
        )
    if channels == 1:
        return samples
    return array("h", (int(sum(samples[index : index + channels]) / channels)
                       for index in range(0, len(samples), channels)))


def _resample(samples: array, rate: int) -> array:
    if rate == TARGET_RATE:
        return samples
    count = max(1, round(len(samples) * TARGET_RATE / rate))
    # 48k → 16k 等整数降采样先平均，避免简单丢帧放大高频失真。
    if rate > TARGET_RATE and rate % TARGET_RATE == 0:
        step = rate // TARGET_RATE
        return array("h", (int(sum(samples[index : index + step]) / min(step, len(samples) - index))
                           for index in range(0, len(samples), step)))[:count]
    output = array("h")
    last = len(samples) - 1
    for index in range(count):
        position = index * rate / TARGET_RATE
        left = min(last, int(position))
        fraction = position - left
        value = samples[left] * (1 - fraction) + samples[min(last, left + 1)] * fraction
        output.append(round(value))
    return output


def prepare_audio(audio_bytes: bytes, suffix: str = ".wav", *, audit_dir: Path | None = None) -> MediaResult:
    """返回可送入现有 transcribe 的 WAV 与留痕；失败同样留痕并明确报错。

    超过 180 秒仅保留前 180 秒，并在 metadata.warnings / truncated 中显式说明。
    增益以整段峰值计算、最多放大八倍；不会把静音变成人声或生成转写文本。
    """
    metadata: dict = {"operations": [], "truncated": False, "warnings": []}
    try:
        if not audio_bytes:
            raise MediaPreprocessError("empty_audio", "音频内容为空，请重新上传。")
        if len(audio_bytes) > MAX_INPUT_BYTES:
            raise MediaPreprocessError("audio_too_large", "录音超过 128MiB，请分段后上传，每段不超过 3 分钟。")
        suffix = suffix.lower()
        if suffix not in (".wav", ".wave"):
            label = suffix if suffix in _COMPRESSED_SUFFIXES else "此格式"
            raise MediaPreprocessError("unsupported_audio", f"{label} 需要先转码。{_CONVERSION_ADVICE}")
        rate, channels, width, frames, raw = _read_pcm(audio_bytes)
        samples = _resample(_mono_samples(raw, channels, width), rate)
        peak = max(abs(value) for value in samples)
        gain = min(MAX_GAIN, TARGET_PEAK / peak) if peak else 1.0
        if gain != 1.0:
            samples = array("h", (round(value * gain) for value in samples))
        operations = []
        if width != 2:
            operations.append("convert_pcm16")
        if channels != 1:
            operations.append("downmix_mono")
        if rate != TARGET_RATE:
            operations.append("resample_16000hz")
        if gain != 1.0:
            operations.append("normalize_peak")
        truncated = frames > MAX_DURATION_SECONDS * rate
        warnings = ["录音超过 3 分钟，只处理前 3 分钟；其余部分请分段上传。"] if truncated else []
        if truncated:
            operations.append("truncate_180s")
        metadata.update(
            source_format="wav", source_sample_rate=rate, source_channels=channels,
            source_sample_width=width, source_duration_s=round(frames / rate, 6),
            sample_rate=TARGET_RATE, channels=1, sample_width=2,
            duration_s=round(len(samples) / TARGET_RATE, 6),
            gain=round(gain, 6), operations=operations, truncated=truncated, warnings=warnings,
        )
        if sys.byteorder != "little":
            samples.byteswap()
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(TARGET_RATE)
            writer.writeframes(samples.tobytes())
        result = output.getvalue()
    except MediaPreprocessError as exc:
        metadata["error_code"] = exc.code
        metadata["warnings"] = [str(exc)]
        record = _record(audio_bytes, "audio", status="rejected", metadata=metadata, audit_dir=audit_dir)
        raise MediaPreprocessError(exc.code, str(exc), record) from exc
    record = _record(audio_bytes, "audio", status="ready", metadata=metadata, audit_dir=audit_dir)
    return MediaResult(result, metadata, record)
