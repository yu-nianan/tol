"""Synthetic images only; no screenshot, real phone number or account is stored."""

from __future__ import annotations

import base64
import json
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from app.pipelines.media import image
from app.pipelines.media._records import MediaPreprocessError
from app.pipelines.vision.ocr import Block

_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQ"
    "DQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUF"
    "BQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAADAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQ"
    "EAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII"
    "0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4"
    "eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5"
    "ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBA"
    "QAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5Ok"
    "NERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tb"
    "a3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD8qqKKKAP/2Q=="
)
_COLORS = [
    [(255, 0, 0), (0, 255, 0)],
    [(0, 0, 255), (255, 255, 0)],
    [(0, 255, 255), (255, 0, 255)],
]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _tiff(orientation: int, endian: str = "<") -> bytes:
    return (
        (b"II" if endian == "<" else b"MM") + struct.pack(endian + "HIH", 42, 8, 1)
        + struct.pack(endian + "HHI", 0x112, 3, 1)
        + struct.pack(endian + "H", orientation) + b"\x00\x00" + b"\x00" * 4
    )


def _png(width: int = 2, height: int = 3, *, orientation: int | None = None, padding: int = 0) -> bytes:
    if (width, height) == (2, 3):
        raw = b"".join(b"\x00" + bytes(value for pixel in row for value in pixel) for row in _COLORS)
    else:
        raw = (b"\x00" + b"\x00" * width * 3) * height
    parts = [_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))]
    if orientation is not None:
        parts.append(_chunk(b"eXIf", _tiff(orientation)))
    if padding:
        parts.append(_chunk(b"tEXt", b"synthetic\x00" + b"a" * padding))
    parts.extend([_chunk(b"IDAT", zlib.compress(raw)), _chunk(b"IEND", b"")])
    return image._PNG_SIGNATURE + b"".join(parts)


def _png_pixels(data: bytes) -> list[list[tuple[int, int, int]]]:
    """Read 8-bit RGB(A) fixture output, independent of the preparation parser."""
    width, height = struct.unpack(">II", data[16:24])
    assert data[24] == 8 and data[25] in (2, 6) and data[28] == 0
    bpp = 3 if data[25] == 2 else 4
    position = 8
    compressed = b""
    while position + 12 <= len(data):
        size = int.from_bytes(data[position : position + 4], "big")
        if data[position + 4 : position + 8] == b"IDAT":
            compressed += data[position + 8 : position + 8 + size]
        position += size + 12
    raw = zlib.decompress(compressed)
    offset = 0
    previous = bytearray(width * bpp)
    result = []
    for _ in range(height):
        filtering = raw[offset]
        row = bytearray(raw[offset + 1 : offset + 1 + width * bpp])
        for index in range(len(row)):
            left = row[index - bpp] if index >= bpp else 0
            above = previous[index]
            upper_left = previous[index - bpp] if index >= bpp else 0
            if filtering == 1:
                predictor = left
            elif filtering == 2:
                predictor = above
            elif filtering == 3:
                predictor = (left + above) // 2
            elif filtering == 4:
                estimate = left + above - upper_left
                distances = [abs(estimate - value) for value in (left, above, upper_left)]
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            else:
                assert filtering == 0
                predictor = 0
            row[index] = (row[index] + predictor) & 255
        result.append([tuple(row[index : index + 3]) for index in range(0, len(row), bpp)])
        previous = row
        offset += 1 + width * bpp
    return result


@pytest.mark.parametrize("data,fmt", [(_png(), "png"), (_JPEG, "jpeg")])
def test_valid_image_preserves_bytes_and_records_only_metadata(tmp_path, data, fmt):
    prepared = image.prepare_image(data, audit_dir=tmp_path)
    assert prepared.data == data
    assert prepared.metadata["format"] == fmt
    assert prepared.metadata["output_width"] == 2
    assert prepared.metadata["output_height"] == 3
    assert prepared.metadata["operations"] == []
    assert prepared.record["status"] == "ready"
    assert prepared.metadata["truncated"] is False


@pytest.mark.parametrize("data", [b"", b"not-image", image._PNG_SIGNATURE + b"\x00" * 20, _JPEG[:-2]])
def test_invalid_image_rejected_with_failed_record(tmp_path, data):
    with pytest.raises(MediaPreprocessError) as raised:
        image.prepare_image(data, audit_dir=tmp_path)
    assert raised.value.code in ("invalid_image", "unsupported_image")
    assert raised.value.record["status"] == "rejected"


def test_png_broken_compressed_pixels_are_rejected(tmp_path):
    valid = _png()
    header = valid[:33]
    broken = header + _chunk(b"IDAT", b"not deflate") + _chunk(b"IEND", b"")
    with pytest.raises(MediaPreprocessError, match="损坏"):
        image.prepare_image(broken, audit_dir=tmp_path)


def test_jpeg_empty_scan_header_is_rejected(tmp_path):
    scan_start = _JPEG.index(b"\xff\xda")
    broken = _JPEG[:scan_start] + b"\xff\xda\x00\x02garbage\xff\xd9"
    with pytest.raises(MediaPreprocessError) as raised:
        image.prepare_image(broken, audit_dir=tmp_path)
    assert raised.value.code == "invalid_image"


def test_png_crc_and_incomplete_exif_are_rejected(tmp_path):
    broken = bytearray(_png())
    broken[29] ^= 1
    for data in [bytes(broken), _png()[:33] + _chunk(b"eXIf", b"II") + _png()[33:]]:
        with pytest.raises(MediaPreprocessError) as raised:
            image.prepare_image(data, audit_dir=tmp_path)
        assert raised.value.code == "invalid_image"


def test_long_screenshot_gets_exact_resize_and_file_size_advice(tmp_path):
    with pytest.raises(MediaPreprocessError) as raised:
        image.prepare_image(_png(1000, 5000, padding=5 * 1024 * 1024), audit_dir=tmp_path)
    assert raised.value.code == "image_too_large"
    assert "800×4000px" in str(raised.value)
    assert "4194304" in str(raised.value)


@pytest.mark.parametrize("orientation", range(2, 9))
def test_orientation_without_tool_never_returns_wrong_pixels(tmp_path, monkeypatch, orientation):
    monkeypatch.setattr(image.shutil, "which", lambda _: None)
    with pytest.raises(MediaPreprocessError) as raised:
        image.prepare_image(_png(orientation=orientation), audit_dir=tmp_path)
    assert raised.value.code == "unable_to_orient"
    assert "清除 EXIF" in str(raised.value)
    assert raised.value.record["status"] == "rejected"


def test_orientation_timeout_cleans_temp_files_and_records_advice(tmp_path, monkeypatch):
    monkeypatch.setattr(image.sys, "platform", "win32")
    monkeypatch.setattr(image.shutil, "which", lambda _: "existing-powershell")
    paths = []

    def timeout(command, **kwargs):
        source = Path(kwargs["env"]["MEDIA_PREP_INPUT"])
        assert source.is_file()
        paths.append(source.parent)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(image.subprocess, "run", timeout)
    with pytest.raises(MediaPreprocessError) as raised:
        image.prepare_image(_png(orientation=6), audit_dir=tmp_path)
    assert raised.value.code == "image_tool_timeout"
    assert paths and not paths[0].exists()
    assert raised.value.record["metadata"]["warnings"]


def test_orientation_temp_io_failure_is_classified_and_recorded(tmp_path, monkeypatch):
    def io_failure(*args):
        raise OSError("synthetic private path")

    monkeypatch.setattr(image, "_orient_with_tool", io_failure)
    with pytest.raises(MediaPreprocessError) as raised:
        image.prepare_image(_png(orientation=6), audit_dir=tmp_path)
    assert raised.value.code == "image_tool_io_error"
    assert raised.value.record["status"] == "rejected"
    assert "synthetic private path" not in json.dumps(raised.value.record)


@pytest.mark.parametrize("endian", ["<", ">"])
def test_jpeg_exif_orientation_is_detected_before_recognition(tmp_path, monkeypatch, endian):
    monkeypatch.setattr(image.shutil, "which", lambda _: None)
    exif = b"Exif\x00\x00" + _tiff(6, endian)
    jpeg = _JPEG[:2] + b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + _JPEG[2:]
    with pytest.raises(MediaPreprocessError) as raised:
        image.prepare_image(jpeg, audit_dir=tmp_path)
    assert raised.value.code == "unable_to_orient"


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"), reason="existing Windows image tool required")
@pytest.mark.parametrize("orientation", range(2, 9))
def test_installed_tool_corrects_actual_pixels_and_removes_exif(tmp_path, orientation):
    prepared = image.prepare_image(_png(orientation=orientation), audit_dir=tmp_path)
    rows = _COLORS
    clockwise = [list(row) for row in zip(*rows[::-1], strict=True)]
    counterclockwise = [list(row) for row in zip(*rows, strict=True)][::-1]
    expected = {
        2: [row[::-1] for row in rows],
        3: [row[::-1] for row in rows[::-1]],
        4: rows[::-1],
        5: [list(row) for row in zip(*rows, strict=True)],
        6: clockwise,
        7: [row[::-1] for row in counterclockwise],
        8: counterclockwise,
    }[orientation]
    assert _png_pixels(prepared.data) == expected
    assert b"eXIf" not in prepared.data
    assert prepared.metadata["output_width"] == len(expected[0])
    assert prepared.metadata["output_height"] == len(expected)
    assert prepared.metadata["operations"] == [f"exif_orientation_{orientation}_to_1"]


def test_phone_card_markers_are_conservative_clipped_and_contain_no_text():
    phone = "138****0000"
    card = "0000 0000 0000 0000"
    blocks = [Block(phone, -5, 10, 100, 30), Block(card, 20, 90, 100, 20), Block("普通聊天", 0, 0, 50, 10)]
    marks = image.mark_sensitive_regions(blocks, 100, 100)
    assert len(marks) == 2
    assert marks[0] == {
        "kinds": ["phone"], "block_index": 0, "x": 0, "y": 10, "w": 95, "h": 30,
        "coordinate_space": "prepared_image", "granularity": "whole_block",
    }
    assert marks[1]["kinds"] == ["card"]
    assert marks[1]["h"] == 10
    assert phone not in json.dumps(marks) and card not in json.dumps(marks)


@pytest.mark.parametrize("width,height", [(0, 100), (-1, 100), (100, True), (1.5, 100)])
def test_marking_rejects_invalid_image_dimensions(width, height):
    with pytest.raises(MediaPreprocessError) as raised:
        image.mark_sensitive_regions([], width, height)
    assert raised.value.code == "invalid_coordinates"


def test_marking_empty_unrelated_outside_and_bad_boxes():
    assert image.mark_sensitive_regions([], 100, 100) == []
    assert image.mark_sensitive_regions([Block("普通聊天", 0, 0, 10, 10)], 100, 100) == []
    assert image.mark_sensitive_regions([Block("138****0000", 200, 0, 10, 10)], 100, 100) == []
    with pytest.raises(MediaPreprocessError):
        image.mark_sensitive_regions([Block("138****0000", 0, 0, 0, 10)], 100, 100)
