"""T-10：截图模板偏离启发式。"""

from __future__ import annotations

from app.pipelines.vision.ocr import Block
from app.pipelines.vision.template import template_deviation
from app.schemas import Modality, SourceKind


def _block(text: str, x: int, y: int, width: int = 400, height: int = 40) -> Block:
    return Block(text=text, x=x, y=y, w=width, h=height)


def _normal_transfer_blocks() -> list[Block]:
    return [
        _block("转账金额 ¥1,000.00", 50, 100),
        _block("收款人 张*", 50, 350),
        _block("收款账户 6222****1234", 50, 420),
        _block("确认转账", 300, 820),
    ]


def test_template_deviation_complete_transfer_page_returns_zero() -> None:
    evidence = template_deviation(_normal_transfer_blocks())

    assert evidence.confidence == 0.0
    assert evidence.meta["template"] == "bank_transfer"
    assert evidence.kind == SourceKind.CROSS_MODAL
    assert evidence.modality == Modality.IMAGE
    assert "启发式" in evidence.meta["note"]


def test_template_deviation_missing_confirm_button_fires() -> None:
    blocks = _normal_transfer_blocks()[:-1]

    evidence = template_deviation(blocks)

    assert evidence.confidence >= 0.4
    assert "确认转账" in evidence.meta["missing"]
    assert evidence.meta["signals"]["required_missing"] is True


def test_template_deviation_confirm_button_off_position_fires() -> None:
    blocks = _normal_transfer_blocks()[:-1] + [_block("确认转账", 300, 40)]

    evidence = template_deviation(blocks)

    assert evidence.confidence >= 0.2
    assert "确认转账" in evidence.meta["off_position"]
    assert "位置异常" in evidence.text


def test_template_deviation_empty_blocks_returns_zero() -> None:
    evidence = template_deviation([])

    assert evidence.confidence == 0.0
    assert "没有可用的 OCR 文本块" in evidence.text


def test_template_deviation_empty_anchor_table_returns_zero() -> None:
    evidence = template_deviation(_normal_transfer_blocks(), anchors={})

    assert evidence.confidence == 0.0
    assert "锚点表为空" in evidence.text
