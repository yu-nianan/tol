from __future__ import annotations

from app.pipelines.memory import build_profile
from app.schemas import ROLE_BIAS, Evidence, SourceKind


def _profile_evidence(code: str, key: str, value: str) -> Evidence:
    return Evidence(
        code=code,
        label="画像",
        category="profile",
        text=value,
        weight=0.4,
        confidence=0.8,
        kind=SourceKind.PROFILE,
        meta={"key": key, "value": value},
    )


def test_build_profile_reads_profile_evidence_only() -> None:
    rule = Evidence(code="impersonate_authority", label="规则", kind=SourceKind.RULE)

    profile = build_profile([_profile_evidence("p_age", "age_group", "elder"), rule], "elder")

    assert profile["facts"] == {"age_group": "elder"}
    assert profile["bias"] == ROLE_BIAS["elder"]
    assert profile["offset"] == round(ROLE_BIAS["elder"], 1)
    assert any("age_group=elder" in reason for reason in profile["reasons"])
    assert any("画像角色 elder" in reason for reason in profile["reasons"])


def test_history_alert_count_adds_capped_offset() -> None:
    profile = build_profile([], "student", alert_count=10)

    assert profile["extra"] == 8.0
    assert profile["offset"] == round(ROLE_BIAS["student"] + 8.0, 1)
    assert any("历史告警 10 次" in reason for reason in profile["reasons"])


def test_unknown_role_falls_back_to_normal_with_reason() -> None:
    profile = build_profile([], "hacker")

    assert profile["role"] == "normal"
    assert profile["offset"] == 0.0
    assert any("未知角色" in reason for reason in profile["reasons"])


def test_negative_alert_count_is_clamped() -> None:
    profile = build_profile([], "normal", alert_count=-3)

    assert profile["alert_count"] == 0
    assert profile["extra"] == 0.0
    assert not any("历史告警" in reason for reason in profile["reasons"])


def test_no_profile_evidence_still_returns_role_bias() -> None:
    profile = build_profile([], "finance")

    assert profile["facts"] == {}
    assert profile["offset"] == ROLE_BIAS["finance"]
    assert profile["reasons"]
