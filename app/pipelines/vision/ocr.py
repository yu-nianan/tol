"""视觉链路骨架：图片校验 → 文本块抽取 → 可降级。

契约（任务单 T-03 冻结）：

    extract_text(image_bytes) -> OcrResult

设计原则：
- 纯标准库：不装 PIL / pytesseract，不调用任何在线 OCR；
- 先校验再尝试：格式不对 → ``UnsupportedImageFormat``；太大 → ``ImageTooLarge``；
- 引擎探测顺序：环境变量 ``OCR_CLI`` → ``shutil.which("tesseract")`` → 都没有时
  ``backend="not-implemented"``、``blocks=[]``、``confidence=0.0``，**返回而不是抛**；
- CLI 输出解析失败时返回空结果（不伪造识别内容）。

CLI 约定：``OCR_CLI`` 是一整条命令（如 ``"rapidocr_onnxruntime"``），图片路径会被追加为
最后一个参数；输出需为 tesseract TSV（表头含 ``level ... conf text``）。``tesseract`` 走官方
``<image> stdout tsv`` 用法。
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# 上限（任务单冻结）：4MB / 4000px
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_SIDE = 4000
CLI_TIMEOUT_SECONDS = 30

PNG_SIGNATURE = b"\x89PNG"
JPEG_SIGNATURE = b"\xff\xd8\xff"


class OcrError(RuntimeError):
    """视觉链路失败的基类。"""


class UnsupportedImageFormat(OcrError):
    """不是 PNG / JPEG（或文件头不完整，判断不了）。"""


class ImageTooLarge(OcrError):
    """>4MB 或宽/高 >4000px。"""


class OCRNotConfigured(OcrError):
    """保留给旧调用方：当前进程没有任何 OCR 引擎。

    注意：``extract_text`` 在没引擎时**不会**抛这个异常，而是返回
    ``backend="not-implemented"`` 的空结果。
    """

    def __init__(self) -> None:
        super().__init__("OCR 未接入：设置 OCR_CLI 或安装 tesseract 后可用")


@dataclass
class Block:
    """一个文本块（像素坐标系，原点左上）。"""

    text: str
    x: int
    y: int
    w: int
    h: int


@dataclass
class OcrResult:
    """OCR 结果。没引擎时各项为空/零，不伪造识别内容。"""

    text: str = ""
    blocks: list[Block] = field(default_factory=list)
    backend: str = "not-implemented"
    confidence: float = 0.0
    width: int = 0
    height: int = 0


def _detect_format(image_bytes: bytes) -> str:
    if image_bytes.startswith(PNG_SIGNATURE):
        return "png"
    if image_bytes.startswith(JPEG_SIGNATURE):
        return "jpeg"
    raise UnsupportedImageFormat("不支持的图片格式：只接受 PNG（89 50 4E 47）或 JPEG（FF D8 FF）")


def _png_size(image_bytes: bytes) -> tuple[int, int]:
    """读 PNG 的 IHDR 宽高；读不到就返回 (0, 0)，不抛。"""
    # 8 字节签名 + 4 字节长度 + 4 字节类型 + 4 字节宽 + 4 字节高
    if len(image_bytes) < 24 or image_bytes[12:16] != b"IHDR":
        return 0, 0
    width = int.from_bytes(image_bytes[16:20], "big")
    height = int.from_bytes(image_bytes[20:24], "big")
    return width, height


def _jpeg_size(image_bytes: bytes) -> tuple[int, int]:
    """扫 JPEG 的 SOF0/SOF2（含其他 SOF）段读宽高；扫不到就返回 (0, 0)，不抛。"""
    total = len(image_bytes)
    pos = 2  # 跳过 SOI
    while pos + 4 <= total:
        if image_bytes[pos] != 0xFF:
            pos += 1
            continue
        marker = image_bytes[pos + 1]
        # 无长度字段的标记：TEM(01)、RST0-7(D0-D7)、SOI(D8)
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            pos += 2
            continue
        seg_len = int.from_bytes(image_bytes[pos + 2 : pos + 4], "big")
        if seg_len < 2:
            return 0, 0
        # SOF0..SOF15，排除 DHT(C4) / JPG(C8) / DAC(CC)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if pos + 9 > total:
                return 0, 0
            height = int.from_bytes(image_bytes[pos + 5 : pos + 7], "big")
            width = int.from_bytes(image_bytes[pos + 7 : pos + 9], "big")
            return width, height
        if marker == 0xDA:  # SOS：扫描数据开始，后面不会再出现 SOF
            return 0, 0
        pos += 2 + seg_len
    return 0, 0


def _read_size(image_bytes: bytes, fmt: str) -> tuple[int, int]:
    if fmt == "png":
        return _png_size(image_bytes)
    return _jpeg_size(image_bytes)


def _split_cli(command: str) -> list[str]:
    """把 OCR_CLI 拆成 argv；Windows 下带引号/空格的路径也能处理。"""
    command = command.strip()
    if len(command) >= 2 and command[0] == command[-1] and command[0] in "\"'":
        unquoted = command[1:-1]
        if os.path.isfile(unquoted):
            return [unquoted]
    if os.path.isfile(command):
        return [command]
    argv = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        argv = [
            token[1:-1]
            if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
            else token
            for token in argv
        ]
    return argv


def _resolve_engine() -> tuple[str, list[str] | None]:
    """返回 (backend, argv 前缀)。没引擎时返回 ("not-implemented", None)。"""
    raw_cli = os.environ.get("OCR_CLI", "").strip()
    if raw_cli:
        argv = _split_cli(raw_cli)
        if argv and (os.path.isfile(argv[0]) or shutil.which(argv[0])):
            return f"ocr-cli:{raw_cli}", argv

    tesseract = shutil.which("tesseract")
    if tesseract:
        return "tesseract-cli", [tesseract]
    return "not-implemented", None


# 兼容 app/api/health.py 的只读探测（模块导入时算一次；请求时以 extract_text 为准）
OCR_BACKEND = _resolve_engine()[0]
OCR_ENABLED = OCR_BACKEND != "not-implemented"


def _parse_tsv(stdout: str) -> tuple[list[Block], float]:
    """解析 tesseract TSV；表头/列数不对就返回 ([], 0.0)。"""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return [], 0.0
    header = [col.strip().lower() for col in lines[0].split("\t")]
    if "text" not in header or "conf" not in header:
        return [], 0.0

    try:
        idx_left = header.index("left")
        idx_top = header.index("top")
        idx_width = header.index("width")
        idx_height = header.index("height")
        idx_conf = header.index("conf")
        idx_text = header.index("text")
        needed = max(idx_left, idx_top, idx_width, idx_height, idx_conf, idx_text)
    except ValueError:
        return [], 0.0

    blocks: list[Block] = []
    confidences: list[float] = []
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) <= needed:
            continue
        try:
            left = int(cols[idx_left])
            top = int(cols[idx_top])
            width = int(cols[idx_width])
            height = int(cols[idx_height])
            conf = float(cols[idx_conf])
        except ValueError:
            continue
        text = "\t".join(cols[idx_text:]).strip()
        if not text:
            continue
        blocks.append(Block(text=text, x=left, y=top, w=width, h=height))
        if conf >= 0:
            confidences.append(conf)

    confidence = 0.0
    if confidences:
        confidence = round(sum(confidences) / len(confidences) / 100.0, 4)
    return blocks, confidence


def _run_cli(argv: list[str], image_path: str, backend: str) -> tuple[list[Block], float]:
    """调用外部 CLI；超时/非零退出/解析失败都退化为空结果。"""
    if backend == "tesseract-cli":
        command = [*argv, image_path, "stdout", "tsv"]
    else:
        command = [*argv, image_path]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("OCR CLI 调用失败：%s", exc)
        return [], 0.0
    if proc.returncode != 0:
        logger.warning("OCR CLI 退出码 %s：%s", proc.returncode, proc.stderr.strip()[:200])
        return [], 0.0
    return _parse_tsv(proc.stdout)


def _suffix_for(fmt: str) -> str:
    return ".png" if fmt == "png" else ".jpg"


def extract_text(image_bytes: bytes) -> OcrResult:
    """校验图片 → 探测引擎 → 返回 OcrResult（没引擎不抛，返回空结果）。"""
    if not image_bytes:
        raise UnsupportedImageFormat("空文件：不是图片")

    fmt = _detect_format(image_bytes)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ImageTooLarge(
            f"图片过大：{len(image_bytes)} 字节 > 上限 {MAX_IMAGE_BYTES} 字节（4MB）"
        )

    width, height = _read_size(image_bytes, fmt)
    if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
        raise ImageTooLarge(f"图片尺寸过大：{width}x{height}，单边上限 {MAX_IMAGE_SIDE}px")

    backend, argv = _resolve_engine()
    if argv is None:
        return OcrResult(width=width, height=height)

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=_suffix_for(fmt)) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name
        blocks, confidence = _run_cli(argv, tmp_path, backend)
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    text = "\n".join(block.text for block in blocks)
    return OcrResult(
        text=text,
        blocks=blocks,
        backend=backend,
        confidence=confidence,
        width=width,
        height=height,
    )


def analyze(image_bytes: bytes) -> list:
    """旧占位：结构化证据不在 T-03 范围内，保持显式失败。"""
    raise OCRNotConfigured()
