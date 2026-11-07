"""脱敏工具：报告、日志、webhook 载荷统一走这里（NFR-6）。

手机号 / 身份证 / 银行卡都用 ``mask_sensitive`` 打码，只保留前 3 后 4。
"""

from __future__ import annotations

from typing import Any

from app.pipelines.text.normalize import mask_sensitive


def mask_text(value: str) -> str:
    """单段文本脱敏；空值原样返回空串。"""
    return mask_sensitive(value or "")


def mask_data(value: Any) -> Any:
    """递归脱敏 dict / list / tuple / str；数字与布尔值原样返回。"""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {key: mask_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_data(item) for item in value)
    return value
