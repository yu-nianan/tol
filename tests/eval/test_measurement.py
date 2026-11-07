"""T-05：40 条测评集校验与 P/R/F1 测量。"""

from __future__ import annotations

from app.pipelines.knowledge.evalcheck import (
    EVAL_SET_PATH,
    OFFICIAL_SET_PATH,
    load_eval_set,
    measure,
    validate_eval_set,
)

ROWS = load_eval_set(EVAL_SET_PATH)


def test_eval_set_is_valid() -> None:
    assert validate_eval_set(ROWS) == []


def test_official_set_loads_and_covers_ten_scripts() -> None:
    rows = load_eval_set(OFFICIAL_SET_PATH)
    assert validate_eval_set(rows, expected_count=20) == []
    covered = {row["script_id"] for row in rows if row["label"] == 1}
    assert len(covered) >= 10


def test_validate_rejects_missing_row() -> None:
    problems = validate_eval_set(ROWS[:-1])
    assert any("条数" in item for item in problems)


def test_validate_rejects_unbalanced_labels() -> None:
    rows = [dict(row) for row in ROWS]
    rows[0]["label"] = 0
    problems = validate_eval_set(rows)
    assert any("1:1" in item for item in problems)


def test_validate_rejects_unknown_script_id() -> None:
    rows = [dict(row) for row in ROWS]
    rows[0]["script_id"] = "S99"
    problems = validate_eval_set(rows)
    assert any("S99" in item for item in problems)


def test_measure_scores_eval_set() -> None:
    result = measure(ROWS, verbose=True)
    assert result["n"] == len(ROWS)
    assert result["tp"] + result["fp"] + result["tn"] + result["fn"] == result["n"]
    # 第 5 周目标 0.85；当前验收门槛 0.70，先如实记录，别改断言凑数
    assert result["accuracy"] >= 0.70
