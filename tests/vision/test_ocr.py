"""T-03 视觉链路：格式识别 / 尺寸读取 / 上限 / 引擎降级。

测试里一律用 base64 常量或手工字节构造最小图，不提交真实截图。
"""

from __future__ import annotations

import base64
import sys
import textwrap

import pytest

from app.pipelines.vision import ocr
from app.pipelines.vision.ocr import (
    ImageTooLarge,
    OcrResult,
    UnsupportedImageFormat,
    extract_text,
)

# 1x1 透明 PNG（base64 常量，非真实截图）
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_with_ihdr(width: int, height: int) -> bytes:
    """只拼 PNG 签名 + IHDR（本模块不校验 CRC，够读尺寸即可）。"""
    ihdr = b"IHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    return PNG_SIGNATURE + (13).to_bytes(4, "big") + ihdr + b"\x00\x00\x00\x00"


def _jpeg_with_sof(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + b"\x00" * 9
    sof0 = (
        b"\xff\xc0"
        + (17).to_bytes(2, "big")
        + b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


@pytest.fixture
def no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """确保探测不到任何 OCR 引擎（本机没装 tesseract）。"""
    monkeypatch.delenv("OCR_CLI", raising=False)
    monkeypatch.setattr(ocr.shutil, "which", lambda _name: None)


def test_png_1x1_size_and_not_implemented(no_engine: None) -> None:
    result = extract_text(PNG_1X1)

    assert isinstance(result, OcrResult)
    assert (result.width, result.height) == (1, 1)
    assert result.backend == "not-implemented"
    assert result.blocks == []
    assert result.text == ""
    assert result.confidence == 0.0


def test_jpeg_sof0_reads_size(no_engine: None) -> None:
    result = extract_text(_jpeg_with_sof(1080, 1920))

    assert (result.width, result.height) == (1080, 1920)
    assert result.backend == "not-implemented"


def test_jpeg_header_only_does_not_crash(no_engine: None) -> None:
    result = extract_text(b"\xff\xd8\xff")

    assert (result.width, result.height) == (0, 0)
    assert result.backend == "not-implemented"


def test_garbage_bytes_raise_unsupported() -> None:
    with pytest.raises(UnsupportedImageFormat):
        extract_text(b"not-an-image-at-all")


def test_empty_bytes_raise_unsupported() -> None:
    with pytest.raises(UnsupportedImageFormat):
        extract_text(b"")


def test_fake_5000px_ihdr_raises_too_large() -> None:
    with pytest.raises(ImageTooLarge):
        extract_text(_png_with_ihdr(5000, 5000))


def test_oversize_bytes_raise_too_large() -> None:
    payload = PNG_SIGNATURE + b"\x00" * (ocr.MAX_IMAGE_BYTES + 1)
    with pytest.raises(ImageTooLarge):
        extract_text(payload)


def test_ocr_cli_backend_and_blocks(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """monkeypatch OCR_CLI 到假脚本：backend 前缀正确，TSV 能解析成 Block。"""
    script = tmp_path / "fake_ocr.py"
    script.write_text(
        textwrap.dedent(
            """\
            import sys

            assert sys.argv[1].endswith(".png")
            print("level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\t"
                  "left\\ttop\\twidth\\theight\\tconf\\ttext")
            print("5\\t1\\t1\\t1\\t1\\t1\\t10\\t20\\t100\\t30\\t88.5\\tTransfer")
            print("5\\t1\\t1\\t1\\t1\\t2\\t120\\t20\\t80\\t30\\t91.5\\tConfirm")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OCR_CLI", f'"{sys.executable}" "{script}"')

    result = extract_text(PNG_1X1)

    assert result.backend.startswith("ocr-cli:")
    assert result.width == 1 and result.height == 1
    assert [block.text for block in result.blocks] == ["Transfer", "Confirm"]
    assert result.text == "Transfer\nConfirm"
    assert result.blocks[0].x == 10 and result.blocks[0].y == 20
    assert result.blocks[1].w == 80 and result.blocks[1].h == 30
    assert result.confidence == pytest.approx(0.9, abs=1e-4)


def test_ocr_cli_bad_output_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """CLI 输出不是 TSV：解析失败退化为空结果，不伪造识别内容。"""
    script = tmp_path / "bad_ocr.py"
    script.write_text("print('this is not tsv')\n", encoding="utf-8")
    monkeypatch.setenv("OCR_CLI", f'"{sys.executable}" "{script}"')

    result = extract_text(PNG_1X1)

    assert result.backend.startswith("ocr-cli:")
    assert result.blocks == []
    assert result.confidence == 0.0
