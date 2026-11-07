"""打分器 v2（T-07）的行为测试：阶段进度、单调性、阶段下限、两条预警曲线。"""

from __future__ import annotations

import pytest

from app.core.config import KB_DIR
from app.pipelines.decision.engine import DetectionEngine
from app.pipelines.decision.scoring import STAGE_FLOOR_SCORE, stage_index
from app.pipelines.knowledge.store import KnowledgeBase, Script, Stage
from app.pipelines.text import rules
from app.pipelines.text.normalize import mask_sensitive, normalize
from app.schemas import Level, ScriptHit

CURVE_SAMPLES = 20


def _engine() -> DetectionEngine:
    return DetectionEngine(KnowledgeBase(KB_DIR))


def _stage_text(script, position: int) -> str:
    return "。".join(script.stages[position - 1].signals)


def test_stage_index_by_weight() -> None:
    def hit(weight: float) -> ScriptHit:
        return ScriptHit(
            script_id="S01",
            name="冒充公检法",
            stage_name="whatever",
            stage_label="阶段",
            stage_weight=weight,
            risk_base=90,
            advice=[],
            matched_signals=["x"],
        )

    assert stage_index(None) == 0
    assert stage_index(hit(0.30)) == 1
    assert stage_index(hit(0.55)) == 2
    assert stage_index(hit(0.75)) == 3
    assert stage_index(hit(0.95)) == 4


def test_session_stage_is_monotonic() -> None:
    engine = _engine()
    script = engine.kb.scripts[0]
    assert len(script.stages) == 4

    for position in (1, 2, 3, 4):
        _, decision, _ = engine.detect_text(_stage_text(script, position), session_id="mono", role="normal")
        assert decision.stage_index >= position
    assert decision.stage_index == 4

    # 回落到"正常消息"时，阶段与分数都不许往回退
    _, decision, _ = engine.detect_text("明天下午三点在图书馆讨论，记得带笔记本", session_id="mono", role="normal")
    assert decision.stage_index == 4
    assert decision.score >= STAGE_FLOOR_SCORE


def test_isolate_stage_reaches_l2_before_transfer() -> None:
    engine = _engine()
    script = engine.kb.scripts[0]
    _, decision, _ = engine.detect_text(_stage_text(script, 3), session_id="iso", role="normal")
    assert decision.stage_index == 3
    assert decision.score >= STAGE_FLOOR_SCORE
    assert decision.level >= Level.L2
    assert decision.need_human is True


def test_stage_below_isolate_has_no_floor() -> None:
    engine = _engine()
    script = engine.kb.scripts[0]
    _, decision, _ = engine.detect_text(_stage_text(script, 1), session_id="contact", role="normal")
    assert decision.stage_index == 1
    assert decision.score < STAGE_FLOOR_SCORE


def test_no_round_bonus_within_session() -> None:
    engine = _engine()
    script = engine.kb.scripts[0]
    text = _stage_text(script, 1)
    scores = [engine.detect_text(text, session_id="flat", role="normal")[1].score for _ in range(5)]
    assert len(set(scores)) == 1, f"同一句话重复出现不应因轮次涨分：{scores}"


def test_curve_stage_vs_keyword() -> None:
    """20 条黑样本：阶段法 vs 关键词法，各自在第几轮第一次到 L2。"""
    engine = _engine()
    scripts = [engine.kb.scripts[i % len(engine.kb.scripts)] for i in range(CURVE_SAMPLES)]
    keyword_rounds: list[int] = []
    stage_rounds: list[int] = []
    qualifying = 0
    earlier = 0

    for index, script in enumerate(scripts):
        session = f"curve-{index}"
        keyword_round = 0
        stage_round = 0
        for position, _stage in enumerate(script.stages, start=1):
            text = _stage_text(script, position)
            # 关键词法：只看这一轮是否出现"转账/验证码/安全账户"这类直接指令
            codes = {ev.code for ev in rules.extract(mask_sensitive(normalize(text)))}
            if not keyword_round and "transfer_demand" in codes:
                keyword_round = position
            _, decision, _ = engine.detect_text(text, session_id=session, role="normal")
            if not stage_round and decision.level >= Level.L2:
                stage_round = position
        keyword_rounds.append(keyword_round or 99)
        stage_rounds.append(stage_round or 99)
        # FR-2.2 口径：只在"确实出现转账意图"的样本上比较（4 轮内没转账意图的样本无从比较）
        if keyword_round:
            qualifying += 1
            earlier += int(stage_round < keyword_round)

    mean_keyword = sum(keyword_rounds) / len(keyword_rounds)
    mean_stage = sum(stage_rounds) / len(stage_rounds)
    ratio = earlier / qualifying if qualifying else 0.0
    print(f"stage_rounds={stage_rounds}")
    print(f"keyword_rounds={keyword_rounds}")
    print(f"mean_stage={mean_stage:.2f} mean_keyword={mean_keyword:.2f}")
    print(f"earlier={earlier}/{qualifying} ratio={ratio:.3f}")

    assert qualifying >= 15, f"可比较样本不足：{qualifying}"
    assert all(round_ <= 3 for round_ in stage_rounds), "阶段法应在隔离/垫付阶段（第 3 轮）前就报警"
    assert ratio >= 0.9, f"黑样本预警轮次早于转账意图的比例只有 {ratio:.0%}（要求 ≥90%）"
    assert mean_keyword - mean_stage >= 1.0, "阶段法平均应比关键词法提前至少 1 轮"


def test_hallucination_cap_without_cited_case() -> None:
    """FR-2.7：一条检索案例都引用不到时，分数封顶 60（最高 L2）。"""
    engine = _engine()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(engine.kb, "search_cases", lambda text, top_k=2: [])
    try:
        _, decision, _ = engine.detect_text(
            "我是警察，你涉嫌洗钱，现在把钱转到安全账户", session_id="cap-1", role="elder"
        )
    finally:
        monkeypatch.undo()
    assert decision.cited_case_ids == []
    assert decision.score <= 60
    assert decision.level == Level.L2
    assert decision.cap_applied is True
    assert any("封顶" in reason for reason in decision.reasons)


def test_high_score_allowed_when_case_cited() -> None:
    engine = _engine()
    case = engine.kb.cases[0]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(engine.kb, "search_cases", lambda text, top_k=2: [(case, 0.95, "hybrid")])
    try:
        _, decision, _ = engine.detect_text(
            "我是警察，你涉嫌洗钱，马上把钱转到安全账户，不许告诉家人", session_id="case-1", role="elder"
        )
    finally:
        monkeypatch.undo()
    assert decision.cited_case_ids == [case.id]
    assert decision.score > 60
    assert decision.cap_applied is False


def test_stage_similarity_gate_rejects_weak_hit() -> None:
    """T-07：单一通用词（1 个信号）不算命中剧本，避免跨剧本抢词误判阶段。"""
    engine = _engine()

    def weak_hit(ratio_hits: int) -> ScriptHit:
        return ScriptHit(
            script_id="S01",
            name="冒充公检法",
            stage_name="transfer",
            stage_label="诱导转账",
            stage_weight=0.95,
            risk_base=95,
            advice=[],
            matched_signals=["转账"] * ratio_hits,
        )

    fake = Script(
        id="S01",
        name="冒充公检法",
        risk_base=95,
        advice=[],
        stages=[
            Stage(name="contact", label="接触", weight=0.30, signals=["公安", "派出所", "警官", "专案组"]),
            Stage(name="authority", label="立威", weight=0.55, signals=["涉嫌洗钱", "涉嫌犯罪", "通缉", "传唤", "办案"]),
            Stage(name="isolate", label="隔离", weight=0.75, signals=["不许告诉", "保密", "单独", "别挂电话"]),
            Stage(name="transfer", label="诱导转账", weight=0.95, signals=["转账", "安全账户", "验证码", "资金核查"]),
        ],
    )
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(engine.kb, "scripts", [fake])

        assert engine._match_script("涉嫌洗钱。") is None, "1/4 信号的擦边命中不应认定剧本"

        hit = engine._match_script("你涉嫌洗钱，现在别挂电话")
        assert hit is not None
        assert hit.stage_name == "isolate", "命中 2 个信号、跨两个阶段时应取走得最远的阶段"
        assert hit.script_id == "S01"

        full = engine._match_script("我是警官，你涉嫌洗钱，不许告诉家人，把钱转到安全账户")
        assert full is not None
        assert full.stage_name == "transfer"
    finally:
        monkeypatch.undo()
