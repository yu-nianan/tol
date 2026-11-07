"""OCR 接入点（第 4 周由负责人 C 实现）。

契约：
    extract_text(image_bytes) -> str           # 纯文本
    analyze(image_bytes) -> list[Evidence]     # 结构化证据（含界面类型判断）

推荐实现：RapidOCR（onnxruntime，免编译）先出文本，再按"界面类型"抽字段：
来电界面 / 聊天界面 / 转账界面 / 短信界面。
"""

from __future__ import annotations

from app.schemas import Evidence

OCR_ENABLED = False
OCR_BACKEND = "not-implemented"


class OCRNotConfigured(RuntimeError):
    def __init__(self) -> None:
        super().__init__("OCR 未接入：第 4 周由负责人 C 接入 RapidOCR，并按界面类型抽字段")


def extract_text(image_bytes: bytes) -> str:
    raise OCRNotConfigured()


def analyze(image_bytes: bytes) -> list[Evidence]:
    raise OCRNotConfigured()
