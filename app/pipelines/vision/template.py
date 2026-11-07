"""跨模态矛盾：截图版面偏离模板的启发式检测（T-10 / FR-2.4b）。

思路：银行/支付转账页、公检法通知页都有比较固定的版面锚点
（"转账金额"、"收款人"、"确认转账"、"公章"……）。把 OCR 出来的文本块
和 ``app/kb/anchors.json`` 里的锚点对一遍：

- 关键锚点缺失（尤其是页面底部的"确认转账"按钮）；
- 锚点出现在不该出现的位置；
- 模板要求的关键动作词一个都没有。

命中越多，越像"截图被动过/页面是仿的"。

**这只是启发式，输出的是「疑似」，不是深度伪造检测器。**
锚点表只覆盖少量演示模板，不能当官方模板库用。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

from app.pipelines.vision.ocr import Block
from app.schemas import Evidence, Modality, SourceKind

LOGGER = logging.getLogger(__name__)

ANCHORS_PATH = Path(__file__).resolve().parents[2] / "kb" / "anchors.json"
MISSING_WEIGHT = 0.70
OFF_POSITION_WEIGHT = 0.60
REQUIRED_MISSING_BONUS = 0.20
MAX_CONFIDENCE = 0.95
NOTE = "启发式，疑似，不是深度伪造检测器"


def template_deviation(blocks: Sequence[Block], anchors: dict | None = None) -> Evidence:
    """根据 OCR 文本块判断版面是否偏离已知模板。

    ``anchors`` 不传时加载 ``app/kb/anchors.json``；传空 dict 可显式关闭模板检查。
    没有文本块、没有命中任何锚点时 confidence=0.0，不抛异常。
    """
    data = _load_anchors() if anchors is None else anchors
    note = str(data.get("note", NOTE))
    meta: dict = {"template": None, "matched": [], "missing": [], "off_position": [], "note": note}
    usable = [block for block in blocks if block.text and block.w > 0 and block.h > 0]
    if not usable:
        meta["reason"] = "没有可用的 OCR 文本块"
        return _evidence(0.0, "没有可用的 OCR 文本块", meta)

    templates = data.get("templates") or []
    if not templates:
        meta["reason"] = "锚点表为空"
        return _evidence(0.0, "锚点表为空", meta)

    width = max(block.x + block.w for block in usable)
    height = max(block.y + block.h for block in usable)
    tolerance = float(data.get("position_tolerance", 0.12))
    best: tuple[float, int, dict, list[str], list[str], list[str], bool] | None = None
    for template in templates:
        matched: list[str] = []
        missing: list[str] = []
        off_position: list[str] = []
        weights: dict[str, float] = {}
        for anchor in template.get("anchors") or []:
            anchor_text = str(anchor.get("text", "")).strip()
            if not anchor_text:
                continue
            weights[anchor_text] = float(anchor.get("weight", 0.0))
            hit = _find_block(anchor_text, usable)
            if hit is None:
                missing.append(anchor_text)
                continue
            matched.append(anchor_text)
            if not _position_ok(hit, anchor.get("position"), width, height, tolerance):
                off_position.append(anchor_text)
        score = MISSING_WEIGHT * sum(weights.get(text, 0.0) for text in missing)
        score += OFF_POSITION_WEIGHT * sum(weights.get(text, 0.0) for text in off_position)
        required = [str(text) for text in template.get("required_any") or []]
        required_missing = bool(required) and not any(_find_block(text, usable) for text in required)
        if required_missing:
            score += REQUIRED_MISSING_BONUS
        if not matched:
            score = 0.0
        score = min(MAX_CONFIDENCE, score)
        candidate = (score, len(matched), template, matched, missing, off_position, required_missing)
        if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and candidate[1] > best[1]):
            best = candidate

    if best is None:
        meta["reason"] = "没有可用的模板锚点"
        return _evidence(0.0, "没有可用的模板锚点", meta)

    score, _matched_count, template, matched, missing, off_position, required_missing = best
    if not matched:
        meta["reason"] = "未命中任何模板锚点，无法判断"
        return _evidence(0.0, "未命中任何模板锚点", meta)

    meta.update(
        {
            "template": str(template.get("id", "")),
            "template_label": str(template.get("label", "")),
            "matched": matched,
            "missing": missing,
            "off_position": off_position,
            "signals": {
                "missing_anchors": len(missing),
                "off_position_anchors": len(off_position),
                "required_missing": required_missing,
            },
        }
    )
    if score <= 0:
        text = f"版面符合模板「{template.get('label', '')}」"
    else:
        parts = []
        if missing:
            parts.append("缺少 " + "、".join(missing))
        if off_position:
            parts.append("位置异常 " + "、".join(off_position))
        text = f"疑似偏离模板「{template.get('label', '')}」：" + "；".join(parts)
    return _evidence(score, text, meta)


def _load_anchors() -> dict:
    try:
        return json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("锚点表加载失败，按空表处理：%s", exc)
        return {}


def _find_block(anchor_text: str, blocks: Sequence[Block]) -> Block | None:
    needle = anchor_text.lower()
    for block in blocks:
        if needle and needle in block.text.lower():
            return block
    return None


def _position_ok(block: Block, position, width: int, height: int, tolerance: float) -> bool:
    if not position or len(position) != 4 or width <= 0 or height <= 0:
        return True
    center_x = (block.x + block.w / 2) / width
    center_y = (block.y + block.h / 2) / height
    left, top, right, bottom = (float(value) for value in position)
    return (
        left - tolerance <= center_x <= right + tolerance
        and top - tolerance <= center_y <= bottom + tolerance
    )


def _evidence(confidence: float, text: str, meta: dict) -> Evidence:
    confidence = max(0.0, min(1.0, float(confidence)))
    return Evidence(
        code="template_deviation",
        label="疑似截图模板被篡改",
        category="channel",
        text=text,
        weight=confidence,
        confidence=confidence,
        modality=Modality.IMAGE,
        kind=SourceKind.CROSS_MODAL,
        meta=meta,
    )
