from __future__ import annotations

from app.pipelines.text.rules import extract

SCAM = (
    "我是市局经侦支队的，你的银行卡涉嫌洗钱，不要告诉任何人，"
    "把存款转到我们的安全账户，半小时内完成，否则后果自负，加我微信。"
)
NORMAL = "明天下午三点在图书馆三楼讨论，记得带笔记本和充电器。"


def test_extract_authority_and_transfer() -> None:
    codes = {ev.code for ev in extract(SCAM)}
    assert "impersonate_authority" in codes
    assert "transfer_demand" in codes
    assert "isolation" in codes


def test_extract_pressure_and_channel() -> None:
    codes = {ev.code for ev in extract(SCAM)}
    assert "pressure" in codes
    assert "channel_im_app" in codes


def test_normal_text_has_no_high_risk_signal() -> None:
    codes = {ev.code for ev in extract(NORMAL)}
    assert "transfer_demand" not in codes
    assert "impersonate_authority" not in codes


def test_each_rule_only_fires_once() -> None:
    evidences = extract(SCAM)
    codes = [ev.code for ev in evidences]
    assert len(codes) == len(set(codes))


def test_evidence_weights_within_range() -> None:
    for ev in extract(SCAM):
        assert 0.0 <= ev.weight <= 1.0
        assert 0.0 <= ev.confidence <= 1.0
