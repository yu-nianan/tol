from __future__ import annotations

from app.pipelines.memory import DEFAULT_WHITELIST, match_whitelist


def test_96110_matches_its_own_rule() -> None:
    reason = match_whitelist("你先打 96110 核实一下")

    assert reason is not None
    assert "96110" in reason
    assert "全国反诈专线" in reason


def test_normal_text_does_not_match() -> None:
    assert match_whitelist("明天下午三点在图书馆三楼讨论") is None
    assert match_whitelist("") is None


def test_digit_boundary_prevents_false_positive() -> None:
    assert match_whitelist("订单号 123110045") is None


def test_custom_entries_replace_defaults() -> None:
    entries = (("400-800-1234", "公司官方客服"),)

    reason = match_whitelist("请拨打 400-800-1234 找客服", entries=entries)

    assert reason is not None
    assert "400-800-1234" in reason
    assert "公司官方客服" in reason
    assert match_whitelist("请拨打 96110", entries=entries) is None


def test_default_whitelist_is_not_empty() -> None:
    assert DEFAULT_WHITELIST
    assert all(pattern and reason for pattern, reason in DEFAULT_WHITELIST)
