"""案例库形状校验：把"数据有没有写歪"变成可被测试直接调用的纯函数。

刻意不依赖 KnowledgeBase：校验函数只认原始 dict（或带同名属性的对象），
这样新增/导入案例时可以先校验再入库，避免半成品数据污染检索。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_FIELDS: tuple[str, ...] = ("id", "script_id", "title", "text", "level")
VALID_LEVELS: frozenset[str] = frozenset({"L0", "L1", "L2", "L3"})
TEXT_MIN = 20
TEXT_MAX = 80
_SCRIPTS_PATH = Path(__file__).resolve().parents[2] / "kb" / "scripts.json"


def _get(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _script_ids() -> set[str]:
    payload = json.loads(_SCRIPTS_PATH.read_text(encoding="utf-8"))
    return {str(script.get("id", "")) for script in payload.get("scripts", [])}


def validate_cases(cases: list[Any], script_ids: set[str] | None = None) -> list[str]:
    """返回问题列表；空列表表示案例库形状合规。

    覆盖：必填字段、id 唯一、script_id 指向真实剧本、level 合法、
    文本长度（20–80 字）、文本重复。内容是否"像真人说的话"不在这里判断。
    """
    if not cases:
        return ["案例列表为空"]

    known_scripts = _script_ids() if script_ids is None else set(script_ids)
    issues: list[str] = []
    seen_ids: set[str] = set()
    seen_texts: set[str] = set()

    for index, item in enumerate(cases):
        position = index + 1
        missing = [field for field in REQUIRED_FIELDS if _get(item, field) in (None, "")]
        if missing:
            issues.append(f"第 {position} 条案例缺少字段：{', '.join(missing)}")
            continue

        case_id = str(_get(item, "id"))
        script_id = str(_get(item, "script_id"))
        level = str(_get(item, "level"))
        text = str(_get(item, "text"))

        if case_id in seen_ids:
            issues.append(f"第 {position} 条案例 id 重复：{case_id}")
        seen_ids.add(case_id)

        if script_id not in known_scripts:
            issues.append(f"第 {position} 条案例 script_id 不存在：{script_id}")

        if level not in VALID_LEVELS:
            issues.append(f"第 {position} 条案例 level 不合法：{level}")

        if not TEXT_MIN <= len(text) <= TEXT_MAX:
            issues.append(f"第 {position} 条案例 text 长度 {len(text)}，应在 {TEXT_MIN}–{TEXT_MAX} 字")

        if text in seen_texts:
            issues.append(f"第 {position} 条案例 text 重复：{text[:16]}…")
        seen_texts.add(text)

    return issues
