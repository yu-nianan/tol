from __future__ import annotations

from app.pipelines.decision.scoring import DIM_WEIGHTS, evaluate
from app.schemas import CAP_WITHOUT_EVIDENCE, Evidence, Level, ScriptHit, level_for


def make_script(stage_weight: float = 0.95) -> ScriptHit:
    return ScriptHit(
        script_id="S01",
        name="冒充公检法",
        stage_name="transfer",
        stage_label="诱导转账",
        stage_weight=stage_weight,
        risk_base=95,
        advice=["挂断并拨打 96110"],
        matched_signals=["安全账户"],
    )


def test_level_thresholds() -> None:
    assert level_for(0) == Level.L0
    assert level_for(34.9) == Level.L0
    assert level_for(35) == Level.L1
    assert level_for(59.9) == Level.L1
    assert level_for(60) == Level.L2
    assert level_for(85) == Level.L3


def test_weights_sum_to_one() -> None:
    assert abs(sum(DIM_WEIGHTS.values()) - 1.0) < 1e-9


def test_script_and_transfer_hit_reaches_high() -> None:
    evidence = [
        Evidence(code="transfer_demand", label="诱导转账", category="stage_transfer", weight=0.95, confidence=0.9),
        Evidence(code="pressure", label="施压", category="pressure", weight=0.65, confidence=0.9),
    ]
    score, reasons, dims, cap_applied = evaluate(evidence, make_script(), "elder")
    assert score >= 60
    assert not cap_applied
    assert dims["stage"] >= 0.85
    assert any("剧本" in r for r in reasons)


def test_cap_without_kb_support() -> None:
    evidence = [
        Evidence(code="pressure", label="施压", category="pressure", weight=0.65, confidence=0.9),
        Evidence(code="channel_url", label="链接", category="channel", weight=0.55, confidence=0.95),
    ]
    score, reasons, _dims, cap_applied = evaluate(evidence, None, "normal")
    assert cap_applied
    assert score <= CAP_WITHOUT_EVIDENCE
    assert any("封顶" in r for r in reasons)


def test_role_bias_raises_score() -> None:
    evidence = [Evidence(code="isolation", label="隔离", category="stage_isolation", weight=0.75, confidence=0.9)]
    normal, *_ = evaluate(evidence, None, "normal")
    elder, *_ = evaluate(evidence, None, "elder")
    assert elder > normal


def test_no_evidence_is_low() -> None:
    score, reasons, _dims, _cap = evaluate([], None, "normal")
    assert score < 35
    assert reasons
