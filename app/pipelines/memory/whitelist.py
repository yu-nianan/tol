"""白名单：命中可信号码/官方渠道时，直接降为 L0，并留下可解释的原因。

默认表是演示用的公开号码；真实部署应从配置或数据库加载，别把用户通讯录写进代码。
"""

from __future__ import annotations

import re

DEFAULT_WHITELIST: tuple[tuple[str, str], ...] = (
    ("96110", "全国反诈专线"),
    ("12381", "工信部反诈预警专线"),
    ("95588", "银行官方客服（演示号码，可替换）"),
    ("110", "报警电话"),
)


def match_whitelist(
    text: str,
    entries: tuple[tuple[str, str], ...] | None = None,
) -> str | None:
    """命中返回原因（含号码与说明），未命中返回 None。

    ``entries`` 可整体替换，方便测试或以后从配置加载。
    """
    if not text:
        return None
    whitelist = entries if entries is not None else DEFAULT_WHITELIST
    for pattern, reason in whitelist:
        if not pattern:
            continue
        # 数字号码要求两侧不是数字，避免 96110 里的 110 误命中
        regex = rf"(?<!\d){re.escape(pattern)}(?!\d)"
        if re.search(regex, text):
            return f"命中白名单 {pattern}：{reason}"
    return None
