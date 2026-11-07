"""知识库形状校验：只校验"结构对不对"，不判断"内容像不像真话术"。

T-01 的验收口径：
- 剧本 15 类、每类 4 阶段（contact/authority/isolate/transfer）、weight 0.3/0.55/0.75/0.95；
- 案例 50 条、每类 ≥3 条、text 20–80 字；
- 至少 5 条带噪声的案例（错别字/多余空格/全角符号/表情）。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from app.pipelines.knowledge.validate import TEXT_MAX, TEXT_MIN, validate_cases

KB_DIR = Path(__file__).resolve().parents[2] / "app" / "kb"
EXPECTED_SCRIPT_IDS = [f"S{i:02d}" for i in range(1, 16)]
EXPECTED_CASE_IDS = [f"C{i:03d}" for i in range(1, 51)]
STAGE_NAMES = ["contact", "authority", "isolate", "transfer"]
STAGE_WEIGHTS = [0.3, 0.55, 0.75, 0.95]
NOISE_RE = re.compile(r"[😊～【】]|  ")
VALID_LEVELS = {"L0", "L1", "L2", "L3"}


def load_scripts() -> list[dict]:
    return json.loads((KB_DIR / "scripts.json").read_text(encoding="utf-8"))["scripts"]


def load_cases() -> list[dict]:
    return json.loads((KB_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]


def test_scripts_are_fifteen_and_ids_continuous() -> None:
    scripts = load_scripts()
    assert len(scripts) == 15
    ids = [script["id"] for script in scripts]
    assert ids == EXPECTED_SCRIPT_IDS
    assert len(set(ids)) == len(ids)
    names = [script["name"] for script in scripts]
    assert len(set(names)) == len(names)


def test_each_script_has_four_increasing_stages() -> None:
    for script in load_scripts():
        assert 80 <= script["risk_base"] <= 95, script["id"]
        assert len(script["advice"]) >= 2, script["id"]
        stages = script["stages"]
        assert len(stages) == 4, script["id"]
        weights = [stage["weight"] for stage in stages]
        assert all(left < right for left, right in zip(weights, weights[1:], strict=False)), script["id"]


def test_new_scripts_use_canonical_stage_names_and_weights() -> None:
    scripts = {script["id"]: script for script in load_scripts()}
    for script_id in ("S11", "S12", "S13", "S14", "S15"):
        assert 80 <= scripts[script_id]["risk_base"] <= 95, script_id
        stages = scripts[script_id]["stages"]
        assert [stage["name"] for stage in stages] == STAGE_NAMES, script_id
        assert [stage["weight"] for stage in stages] == STAGE_WEIGHTS, script_id


def test_each_stage_has_three_unique_signals() -> None:
    for script in load_scripts():
        for stage in script["stages"]:
            signals = stage["signals"]
            assert len(signals) >= 3, (script["id"], stage["name"])
            assert len(set(signals)) == len(signals), (script["id"], stage["name"])
            assert all(signal.strip() for signal in signals), (script["id"], stage["name"])


def test_cases_are_fifty_and_every_script_has_three() -> None:
    scripts = load_scripts()
    cases = load_cases()
    assert len(cases) == 50
    case_ids = [case["id"] for case in cases]
    assert case_ids == EXPECTED_CASE_IDS
    assert len(set(case_ids)) == len(case_ids)

    script_ids = {script["id"] for script in scripts}
    for case in cases:
        assert case["script_id"] in script_ids, case["id"]

    counts = {script_id: 0 for script_id in script_ids}
    for case in cases:
        counts[case["script_id"]] += 1
    for script_id, count in counts.items():
        assert count >= 3, script_id


def test_case_text_level_and_noise() -> None:
    cases = load_cases()
    for case in cases:
        assert case["title"].strip(), case["id"]
        assert case["level"] in VALID_LEVELS, case["id"]
        assert TEXT_MIN <= len(case["text"]) <= TEXT_MAX, case["id"]

    levels = {case["level"] for case in cases}
    assert {"L1", "L2", "L3"} <= levels

    noisy = [case for case in cases if NOISE_RE.search(case["text"])]
    assert len(noisy) >= 5


def test_real_cases_pass_validate() -> None:
    assert validate_cases(load_cases()) == []


def test_validate_reports_missing_field() -> None:
    broken = copy.deepcopy(load_cases()[0])
    broken.pop("text")
    issues = validate_cases([broken])
    assert any("缺少字段" in issue and "text" in issue for issue in issues)


def test_validate_reports_invalid_level() -> None:
    broken = copy.deepcopy(load_cases()[0])
    broken["level"] = "L9"
    issues = validate_cases([broken])
    assert any("level 不合法" in issue for issue in issues)


def test_validate_reports_unknown_script_id() -> None:
    broken = copy.deepcopy(load_cases()[0])
    broken["script_id"] = "S99"
    issues = validate_cases([broken])
    assert any("script_id 不存在" in issue for issue in issues)
