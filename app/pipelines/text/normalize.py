"""文本归一化与脱敏：先把脏东西洗干净，后面所有模块都只处理干净文本。"""

from __future__ import annotations

import re
import unicodedata

_SPACE_RE = re.compile(r"\s+")
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)")
_ID_RE = re.compile(r"(?<!\d)(\d{4})\d{10}(\d{4})(?!\d)")
_SENTENCE_RE = re.compile(r"[。！？!?；;\n]+")
_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def normalize(text: str) -> str:
    """全角转半角、去多余空白。返回空串表示没有有效内容。"""
    cleaned = unicodedata.normalize("NFKC", text or "")
    cleaned = cleaned.replace("\u3000", " ").replace("\xa0", " ")
    return _SPACE_RE.sub(" ", cleaned).strip()


def mask_sensitive(text: str) -> str:
    """手机号 / 身份证 / 银行卡脱敏。演示与报告都只用脱敏后的文本。

    顺序很重要：身份证（18 位）会先被银行卡规则（16–19 位）吃掉，
    所以必须先遮身份证，再遮银行卡。
    """
    masked = _PHONE_RE.sub(r"\1****\2", text)
    masked = _ID_RE.sub(r"\1**********\2", masked)
    return _CARD_RE.sub(r"\1****\2", masked)


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]


def tokenize(text: str) -> list[str]:
    """中文按字 + 双字切，英文数字按词切。

    刻意不引入 jieba：零依赖、规则可解释，足够支撑案例检索。
    """
    lowered = text.lower()
    tokens = [m.group(0) for m in _WORD_RE.finditer(lowered)]
    cjk = "".join(_CJK_RE.findall(lowered))
    tokens.extend(cjk)
    tokens.extend(cjk[i : i + 2] for i in range(len(cjk) - 1))
    return tokens
