"""规则层：把"看得见的话术"变成结构化证据。

这一层刻意保持朴素（关键词 + 正则），因为：
1. 它是模型超时/不可用时的兜底，必须永远可用；
2. 评委问"这句话为什么被判成高危"，答案必须能指到具体证据。
模型接入后只负责"补充证据"，不替代这一层。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import Evidence, Modality, SourceKind


@dataclass(frozen=True)
class RuleSpec:
    code: str
    label: str
    category: str
    weight: float
    patterns: tuple[str, ...]


RULES: tuple[RuleSpec, ...] = (
    RuleSpec(
        "impersonate_authority",
        "冒用公检法身份",
        "stage_authority",
        0.85,
        ("公安", "派出所", "检察院", "法院", "经侦", "警官", "专案组", "通缉", "传唤", "涉嫌洗钱", "涉嫌犯罪"),
    ),
    RuleSpec(
        "isolation",
        "要求保密与隔离",
        "stage_isolation",
        0.75,
        ("不许告诉", "不要告诉", "别告诉家人", "保密", "一个人", "不许挂", "不要挂断", "身边有人吗"),
    ),
    RuleSpec(
        "transfer_demand",
        "诱导转账或索要验证码",
        "stage_transfer",
        0.95,
        ("安全账户", "资金审查", "转账", "汇款", "验证码", "保证金", "解冻费", "刷流水", "垫付"),
    ),
    RuleSpec("brushing", "刷单返利话术", "script_kw", 0.8, ("刷单", "返利", "佣金", "接单", "日结", "做任务")),
    RuleSpec(
        "fake_invest",
        "虚假投资话术",
        "script_kw",
        0.8,
        ("稳赚", "内幕", "带单", "收益翻倍", "杀猪盘", "虚拟币", "理财课", "投资群"),
    ),
    RuleSpec(
        "fake_service",
        "冒充客服退款",
        "script_kw",
        0.7,
        ("退款", "理赔", "订单异常", "屏幕共享", "远程协助", "客服"),
    ),
    RuleSpec("fake_loan", "虚假贷款话术", "script_kw", 0.7, ("无抵押", "秒批", "流水包装", "征信修复", "贷款额度")),
    RuleSpec("acquaintance", "冒充熟人领导", "script_kw", 0.7, ("领导", "老板", "换号", "急用钱", "帮我转", "在开会")),
    RuleSpec("prize", "虚假中奖或快递理赔", "script_kw", 0.6, ("中奖", "领奖", "快递理赔", "礼品", "抽奖")),
    RuleSpec("campus", "校园贷与助学金骗局", "script_kw", 0.6, ("助学金", "校园贷", "学费退款", "奖学金")),
    RuleSpec(
        "pressure",
        "施压与催促",
        "pressure",
        0.65,
        ("立即", "马上", "限时", "半小时内", "后果自负", "追究", "逾期", "不许告诉任何人"),
    ),
)

CHANNEL_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("url", "出现外部链接", re.compile(r"(?:https?://|www\.)[^\s，。；]+", re.IGNORECASE)),
    ("phone", "出现手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("bank_card", "出现银行卡号", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("im_app", "引导加即时通讯", re.compile(r"(?:加|添加)(?:我|你)?(?:QQ|微信|VX|vx)", re.IGNORECASE)),
)


def _snippet(text: str, start: int, length: int, radius: int = 8) -> str:
    left = max(0, start - radius)
    right = min(len(text), start + length + radius)
    return text[left:right].strip()


def extract(text: str) -> list[Evidence]:
    """返回命中的证据列表（同一规则只取第一次命中，避免堆叠刷分）。"""
    evidences: list[Evidence] = []
    for spec in RULES:
        for pattern in spec.patterns:
            index = text.find(pattern)
            if index >= 0:
                evidences.append(
                    Evidence(
                        code=spec.code,
                        label=spec.label,
                        category=spec.category,
                        text=_snippet(text, index, len(pattern)),
                        weight=spec.weight,
                        confidence=0.9,
                        modality=Modality.TEXT,
                        kind=SourceKind.RULE,
                    )
                )
                break

    for code, label, pattern in CHANNEL_PATTERNS:
        match = pattern.search(text)
        if match:
            evidences.append(
                Evidence(
                    code=f"channel_{code}",
                    label=label,
                    category="channel",
                    text=_snippet(text, match.start(), len(match.group(0))),
                    weight=0.55,
                    confidence=0.95,
                    kind=SourceKind.RULE,
                    meta={"matched": match.group(0)[:32]},
                )
            )
    return evidences
