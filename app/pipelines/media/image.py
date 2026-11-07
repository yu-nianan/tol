"""Image preparation, without OCR or a new Python dependency.

PNG/JPEG containers and EXIF are checked before passing bytes downstream. On
Windows, the existing PowerShell/System.Drawing tool can correct EXIF 2..8;
other environments explicitly request manual rotation rather than return wrong
coordinates. No image or OCR text is retained in the audit record.
"""

from __future__ import annotations

import base64
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from ._records import MediaPreprocessError, MediaResult, _record

if TYPE_CHECKING:
    from app.pipelines.vision.ocr import Block

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_SIDE = 4000
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PHONE = re.compile(r"(?<!\d)1[3-9]\d(?:[ -]?\d){8}(?!\d)")
_MASKED_PHONE = re.compile(r"(?<!\d)1[3-9]\d[ -]?(?:[*xX\u00d7\u2022][ -]?){4}\d{4}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_MASKED_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){4}(?:[*xX\u00d7\u2022][ -]?){4,12}(?:\d[ -]?){4}(?!\d)")

_ORIENT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$image = $null
$canvas = $null
$graphics = $null
try {
    $image = [System.Drawing.Image]::FromFile($env:MEDIA_PREP_INPUT)
    $mode = switch ([int]$env:MEDIA_PREP_ORIENTATION) {
        2 { [System.Drawing.RotateFlipType]::RotateNoneFlipX }
        3 { [System.Drawing.RotateFlipType]::Rotate180FlipNone }
        4 { [System.Drawing.RotateFlipType]::RotateNoneFlipY }
        5 { [System.Drawing.RotateFlipType]::Rotate90FlipX }
        6 { [System.Drawing.RotateFlipType]::Rotate90FlipNone }
        7 { [System.Drawing.RotateFlipType]::Rotate270FlipX }
        8 { [System.Drawing.RotateFlipType]::Rotate270FlipNone }
        default { throw 'Invalid EXIF orientation' }
    }
    $image.RotateFlip($mode)
    $canvas = [System.Drawing.Bitmap]::new($image.Width, $image.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $graphics.DrawImageUnscaled($image, 0, 0)
    $canvas.Save($env:MEDIA_PREP_OUTPUT, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    if ($graphics) { $graphics.Dispose() }
    if ($canvas) { $canvas.Dispose() }
    if ($image) { $image.Dispose() }
}
"""


def _invalid() -> MediaPreprocessError:
    return MediaPreprocessError("invalid_image", "图片文件或 EXIF 数据损坏，请重新导出完整的 PNG/JPEG 后上传")


def _orientation(tiff: bytes) -> int:
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        raise _invalid()
    endian = "little" if tiff[:2] == b"II" else "big"

    def integer(offset: int, size: int) -> int:
        if offset < 0 or offset + size > len(tiff):
            raise _invalid()
        return int.from_bytes(tiff[offset : offset + size], endian)

    if integer(2, 2) != 42:
        raise _invalid()
    start = integer(4, 4)
    if start < 8:
        raise _invalid()
    count = integer(start, 2)
    if start + 2 + count * 12 + 4 > len(tiff):
        raise _invalid()
    orientations = []
    for index in range(count):
        entry = start + 2 + index * 12
        if integer(entry, 2) == 0x112:
            if integer(entry + 2, 2) != 3 or integer(entry + 4, 4) != 1:
                raise _invalid()
            orientations.append(integer(entry + 8, 2))
    if len(orientations) > 1 or any(value not in range(1, 9) for value in orientations):
        raise _invalid()
    return orientations[0] if orientations else 1


def _png_info(data: bytes) -> tuple[int, int, int]:
    position = 8
    width = height = 0
    orientation = 1
    seen_exif = False
    saw_data = False
    while position + 12 <= len(data):
        size = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        end = position + 12 + size
        if end > len(data):
            raise _invalid()
        payload = data[position + 8 : end - 4]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != int.from_bytes(data[end - 4 : end], "big"):
            raise _invalid()
        if position == 8 and kind != b"IHDR":
            raise _invalid()
        if kind == b"IHDR":
            if position != 8 or size != 13:
                raise _invalid()
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            valid_depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if (
                not width or not height or color not in valid_depths or depth not in valid_depths[color]
                or compression != 0 or filtering != 0 or interlace not in (0, 1)
            ):
                raise _invalid()
        elif kind == b"eXIf":
            if seen_exif:
                raise _invalid()
            orientation = _orientation(payload)
            seen_exif = True
        elif kind == b"IDAT":
            saw_data = saw_data or bool(payload)
        elif kind == b"IEND":
            if size or not saw_data or end != len(data):
                raise _invalid()
            return width, height, orientation
        position = end
    raise _invalid()


def _jpeg_info(data: bytes) -> tuple[int, int, int]:
    position = 2
    width = height = 0
    orientation = 1
    seen_exif = False
    components: set[int] = set()
    while position < len(data):
        if data[position] != 0xFF:
            raise _invalid()
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            raise _invalid()
        marker = data[position]
        position += 1
        if marker in (0, 0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            raise _invalid()
        if marker == 1:
            continue
        if position + 2 > len(data):
            raise _invalid()
        size = int.from_bytes(data[position : position + 2], "big")
        end = position + size
        if size < 2 or end > len(data):
            raise _invalid()
        payload = data[position + 2 : end]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            if seen_exif:
                raise _invalid()
            orientation = _orientation(payload[6:])
            seen_exif = True
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if len(payload) < 6 or width:
                raise _invalid()
            height = int.from_bytes(payload[1:3], "big")
            width = int.from_bytes(payload[3:5], "big")
            if not width or not height or not payload[5] or len(payload) != 6 + 3 * payload[5]:
                raise _invalid()
            components = set(payload[6::3])
            if len(components) != payload[5] or not 1 <= payload[0] <= 16:
                raise _invalid()
        if marker == 0xDA:
            # This validates the container, not entropy-decoded JPEG pixels.
            # Requiring scan bytes + EOI prevents header-only inputs succeeding.
            if not width or not height or end + 2 >= len(data) or not data.endswith(b"\xff\xd9"):
                raise _invalid()
            if len(payload) < 6 or not payload[0] or len(payload) != 4 + 2 * payload[0]:
                raise _invalid()
            scan_components = payload[1 : 1 + 2 * payload[0] : 2]
            if len(set(scan_components)) != len(scan_components) or not set(scan_components) <= components:
                raise _invalid()
            return width, height, orientation
        position = end
    raise _invalid()


def _inspect(data: bytes) -> tuple[str, int, int, int]:
    if data.startswith(_PNG_SIGNATURE):
        return "png", *_png_info(data)
    if data.startswith(b"\xff\xd8"):
        return "jpeg", *_jpeg_info(data)
    raise MediaPreprocessError("unsupported_image", "当前只支持完整 PNG/JPEG；请先导出为 PNG 或 JPEG 后上传")


def _validate_png_pixels(data: bytes, width: int, height: int) -> None:
    """Bound deflate output using validated dimensions; reject broken scanlines."""
    depth, color, interlace = data[24], data[25], data[28]
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = [(0, 0, 1, 1)] if not interlace else [
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
    ]
    rows = []
    for start_x, start_y, step_x, step_y in passes:
        pass_width = max(0, (width - start_x + step_x - 1) // step_x)
        pass_height = max(0, (height - start_y + step_y - 1) // step_y)
        if pass_width and pass_height:
            rows.extend([(pass_width * channels * depth + 7) // 8 + 1] * pass_height)
    expected = sum(rows)
    compressed = []
    position = 8
    while position + 12 <= len(data):
        size = int.from_bytes(data[position : position + 4], "big")
        if data[position + 4 : position + 8] == b"IDAT":
            compressed.append(data[position + 8 : position + 8 + size])
        position += size + 12
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(b"".join(compressed), expected + 1)
    except zlib.error as exc:
        raise _invalid() from exc
    if len(raw) != expected or not decoder.eof or decoder.unused_data:
        raise _invalid()
    offset = 0
    for row_size in rows:
        if raw[offset] > 4:
            raise _invalid()
        offset += row_size


def _check_limits(data: bytes, width: int, height: int) -> None:
    if len(data) > MAX_IMAGE_BYTES or max(width, height) > MAX_IMAGE_SIDE:
        ratio = min(1.0, MAX_IMAGE_SIDE / max(width, height))
        target_width = max(1, math.floor(width * ratio))
        target_height = max(1, math.floor(height * ratio))
        raise MediaPreprocessError(
            "image_too_large",
            f"图片当前 {width}×{height}px、{len(data)} 字节；请裁剪或缩小到不超过 "
            f"{target_width}×{target_height}px，并导出到 4MiB（{MAX_IMAGE_BYTES} 字节）以内后重传",
        )


def _orient_with_tool(data: bytes, orientation: int) -> bytes:
    tool = shutil.which("powershell") if sys.platform == "win32" else None
    if tool is None:
        raise MediaPreprocessError(
            "unable_to_orient",
            f"图片 EXIF 方向为 {orientation}，当前没有可用的像素旋转工具；"
            "请在相册中旋转/镜像摆正，重新导出并清除 EXIF 方向后上传",
        )
    with tempfile.TemporaryDirectory(prefix="media-orient-") as directory:
        source = Path(directory) / "input.image"
        output = Path(directory) / "output.png"
        source.write_bytes(data)
        environment = os.environ.copy()
        environment.update(
            MEDIA_PREP_INPUT=str(source), MEDIA_PREP_OUTPUT=str(output),
            MEDIA_PREP_ORIENTATION=str(orientation),
        )
        try:
            result = subprocess.run(
                [tool, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand",
                 base64.b64encode(_ORIENT_SCRIPT.encode("utf-16le")).decode("ascii")],
                env=environment, capture_output=True, timeout=8, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaPreprocessError("image_tool_timeout", "图片方向纠正超时，请手动摆正并重新导出后上传") from exc
        except OSError as exc:
            raise MediaPreprocessError("unable_to_orient", "像素旋转工具无法启动，请手动摆正并清除 EXIF 方向后上传") from exc
        if result.returncode != 0 or not output.is_file():
            raise MediaPreprocessError("unable_to_orient", "像素旋转工具处理失败，请手动摆正并清除 EXIF 方向后上传")
        return output.read_bytes()


def _orient(data: bytes, orientation: int) -> bytes:
    try:
        return _orient_with_tool(data, orientation)
    except OSError as exc:
        raise MediaPreprocessError(
            "image_tool_io_error", "图片临时文件读写或清理失败，请检查磁盘空间与临时目录权限后重试"
        ) from exc


def prepare_image(image_bytes: bytes, *, audit_dir: Path | None = None) -> MediaResult:
    """Validate PNG/JPEG and correct EXIF pixels when the installed tool is available.

    Oversized images receive precise re-export guidance. ``ready`` indicates
    preparation, not successful OCR. Container checks do not replace a decoder.
    """
    metadata: dict = {"operations": [], "warnings": [], "truncated": False}
    try:
        fmt, width, height, orientation = _inspect(image_bytes)
        metadata.update(format=fmt, width=width, height=height, orientation=orientation)
        _check_limits(image_bytes, width, height)
        if fmt == "png":
            _validate_png_pixels(image_bytes, width, height)
        output = image_bytes
        if orientation != 1:
            output = _orient(image_bytes, orientation)
            out_fmt, out_width, out_height, out_orientation = _inspect(output)
            expected = (height, width) if orientation in (5, 6, 7, 8) else (width, height)
            if (out_width, out_height) != expected or out_orientation != 1:
                raise MediaPreprocessError("orientation_failed", "图片旋转结果校验失败，请手动摆正后重新导出")
            _check_limits(output, out_width, out_height)
            if out_fmt == "png":
                _validate_png_pixels(output, out_width, out_height)
            metadata.update(output_format=out_fmt, output_width=out_width, output_height=out_height)
            metadata["operations"].append(f"exif_orientation_{orientation}_to_1")
            metadata["warnings"].append("方向纠正后输出为 PNG，EXIF 已移除；OCR 坐标以输出图片为准")
        else:
            metadata.update(output_format=fmt, output_width=width, output_height=height)
    except MediaPreprocessError as exc:
        metadata["error_code"] = exc.code
        metadata["warnings"].append(str(exc))
        record = _record(image_bytes, "image", status="rejected", metadata=metadata, audit_dir=audit_dir)
        exc.record = record
        raise
    record = _record(image_bytes, "image", status="ready", metadata=metadata, audit_dir=audit_dir)
    return MediaResult(data=output, metadata=metadata, record=record)


def mark_sensitive_regions(blocks: Sequence[Block], width: int, height: int) -> list[dict]:
    """Conservatively mark whole OCR blocks containing phone/card candidates.

    Coordinates refer to the prepared, upright image. Values/text are excluded
    from the result. Numbers split across different blocks require future OCR
    line grouping; this function only matches inside each supplied block.
    """
    if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, int) or not isinstance(height, int):
        raise MediaPreprocessError("invalid_coordinates", "图片宽高必须是正整数像素")
    if width <= 0 or height <= 0:
        raise MediaPreprocessError("invalid_coordinates", "图片宽高必须是正整数像素")
    regions = []
    for index, block in enumerate(blocks):
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (block.x, block.y, block.w, block.h)):
            raise MediaPreprocessError("invalid_coordinates", "文字框坐标必须是整数像素")
        if block.w <= 0 or block.h <= 0:
            raise MediaPreprocessError("invalid_coordinates", "文字框宽高必须为正数")
        kinds = []
        if _PHONE.search(block.text) or _MASKED_PHONE.search(block.text):
            kinds.append("phone")
        if _CARD.search(block.text) or _MASKED_CARD.search(block.text):
            kinds.append("card")
        left, top = max(0, block.x), max(0, block.y)
        right, bottom = min(width, block.x + block.w), min(height, block.y + block.h)
        if kinds and right > left and bottom > top:
            regions.append({
                "kinds": kinds, "block_index": index,
                "x": left, "y": top, "w": right - left, "h": bottom - top,
                "coordinate_space": "prepared_image", "granularity": "whole_block",
            })
    return regions
