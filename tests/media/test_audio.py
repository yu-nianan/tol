"""纯合成波形验收；不保存真实录音或个人信息。"""

from __future__ import annotations

import io
import math
import struct
import sys
import time
import wave
from array import array

import pytest

from app.pipelines.audio.asr import transcribe
from app.pipelines.media._records import MediaPreprocessError
from app.pipelines.media.audio import prepare_audio


def _wav(samples: list[int], rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    output = io.BytesIO()
    if width == 2:
        encoded = array("h", samples)
        if sys.byteorder != "little":
            encoded.byteswap()
        raw = encoded.tobytes()
    else:
        raw = b"".join(value.to_bytes(width, "little", signed=width != 1) for value in samples)
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes(raw)
    return output.getvalue()


def _read(data: bytes) -> tuple[wave._wave_params, list[int]]:
    with wave.open(io.BytesIO(data), "rb") as reader:
        params = reader.getparams()
        raw = reader.readframes(reader.getnframes())
    return params, [value[0] for value in struct.iter_unpack("<h", raw)]


def test_48k_stereo_converts_to_mono_16k_and_keeps_speech_segments(tmp_path):
    rate = 48000
    # 三秒合成录音，静音前后夹着一秒有声波形。
    mono = [0] * rate + [int(6000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(rate)] + [0] * rate
    stereo = [value for sample in mono for value in (sample, sample // 2)]
    result = prepare_audio(_wav(stereo, rate, 2), audit_dir=tmp_path)
    params, samples = _read(result.data)
    assert (params.framerate, params.nchannels, params.sampwidth, params.nframes) == (16000, 1, 2, 48000)
    assert max(abs(value) for value in samples) <= 28000
    assert samples[:16000] == [0] * 16000
    transcript = transcribe(result.data)
    assert transcript.duration_s == 3.0
    assert len(transcript.segments) == 1
    assert 0.9 <= transcript.segments[0].start_s <= 1.1
    assert 1.9 <= transcript.segments[0].end_s <= 2.1
    assert result.metadata["operations"] == ["downmix_mono", "resample_16000hz", "normalize_peak"]
    assert result.metadata["source_channels"] == 2


def test_silence_stays_silent_and_does_not_create_speech(tmp_path):
    result = prepare_audio(_wav([0] * 16000), audit_dir=tmp_path)
    _, samples = _read(result.data)
    assert samples == [0] * 16000
    assert result.metadata["gain"] == 1.0
    assert transcribe(result.data).segments == []


@pytest.mark.parametrize("width,values", [(1, [0, 128, 255]), (2, [-32768, 0, 32767]),
                                           (3, [-8388608, 0, 8388607]), (4, [-2147483648, 0, 2147483647])])
def test_integer_pcm_widths_are_normalized_without_clipping(tmp_path, width, values):
    result = prepare_audio(_wav(values * 100, width=width), audit_dir=tmp_path)
    params, samples = _read(result.data)
    assert params.sampwidth == 2
    assert max(abs(value) for value in samples) == 28000
    assert min(samples) < 0 < max(samples)


def test_44k_resampling_preserves_duration(tmp_path):
    result = prepare_audio(_wav([1000, -1000] * 22050, rate=44100), audit_dir=tmp_path)
    params, _ = _read(result.data)
    assert params.nframes == 16000
    assert result.metadata["duration_s"] == 1.0


@pytest.mark.parametrize("rate", [44100, 48000, 192000])
def test_single_frame_high_rate_audio_still_has_one_output_frame(tmp_path, rate):
    result = prepare_audio(_wav([1000], rate=rate), audit_dir=tmp_path)
    params, samples = _read(result.data)
    assert params.nframes == 1
    assert samples and samples[0] > 0


def test_five_minute_recording_is_explicitly_limited_to_three_minutes(tmp_path):
    # 用 8k 静音控制合成素材体积；应读取头部原时长而只输出前 180 秒。
    result = prepare_audio(_wav([0] * (8000 * 300), rate=8000), audit_dir=tmp_path)
    params, _ = _read(result.data)
    assert params.nframes == 16000 * 180
    assert result.metadata["source_duration_s"] == 300.0
    assert result.metadata["duration_s"] == 180.0
    assert result.metadata["truncated"] is True
    assert "只处理前 3 分钟" in result.metadata["warnings"][0]


@pytest.mark.parametrize("data,suffix,code", [(b"", ".wav", "empty_audio"),
    (b"not audio", ".wav", "invalid_audio"), (b"m4a bytes", ".m4a", "unsupported_audio"),
    (b"mp3 bytes", ".mp3", "unsupported_audio")])
def test_invalid_or_compressed_audio_reports_actionable_error_and_audits(tmp_path, data, suffix, code):
    with pytest.raises(MediaPreprocessError) as captured:
        prepare_audio(data, suffix, audit_dir=tmp_path)
    assert captured.value.code == code
    assert captured.value.record is not None
    if suffix != ".wav":
        assert "PCM WAV" in str(captured.value)
        assert "16000Hz" in str(captured.value)
        assert "先转码" in str(captured.value)


def test_truncated_wav_cannot_be_mistaken_for_a_short_success(tmp_path):
    data = _wav([1000] * 16000)
    with pytest.raises(MediaPreprocessError, match="截断"):
        prepare_audio(data[:-100], audit_dir=tmp_path)


def test_partial_frame_is_rejected_even_when_riff_length_is_consistent(tmp_path):
    data = bytearray(_wav([1000] * 10))
    # data 长度改成奇数，RIFF 同步修改，模拟损坏的最后半个采样。
    data[4:8] = (len(data) - 9).to_bytes(4, "little")
    data[40:44] = (19).to_bytes(4, "little")
    with pytest.raises(MediaPreprocessError, match="采样帧"):
        prepare_audio(bytes(data[:-1]), audit_dir=tmp_path)


def test_thirty_seconds_stereo_prepares_in_under_ten_seconds(tmp_path):
    raw = struct.pack("<hh", 4000, -2000) * (48000 * 30)
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(48000)
        writer.writeframes(raw)
    started = time.perf_counter()
    result = prepare_audio(output.getvalue(), audit_dir=tmp_path)
    assert time.perf_counter() - started < 10
    assert result.metadata["duration_s"] == 30.0
