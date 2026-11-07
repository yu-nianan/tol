"""测评集校验与指标计算（T-05）。

口径：
- 黑样本 ``label=1``、白样本 ``label=0``；
- 引擎判到 ``Level.L2`` 及以上才算「判为诈骗」；
- 精确率/召回率把「判为诈骗」当正类：TP=黑样本判出、FP=白样本误报。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.core.config import KB_DIR
from app.pipelines.decision.engine import get_engine
from app.schemas import Level

EVAL_SET_PATH = KB_DIR / "eval_set.csv"
OFFICIAL_SET_PATH = KB_DIR / "eval_set_official.csv"


def load_eval_set(path: Path) -> list[dict]:
    """读取测评集 CSV；跳过空行与以 ``#`` 开头的注释行。"""
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as fh:
        lines = [line for line in fh if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines)
    fields = set(reader.fieldnames or [])
    missing = {"id", "text", "label", "script_id", "stage"} - fields
    if missing:
        raise ValueError(f"测评集缺少列：{sorted(missing)}")
    rows: list[dict] = []
    for raw in reader:
        rows.append(
            {
                "id": raw["id"].strip(),
                "text": raw["text"].strip(),
                "label": int(raw["label"]),
                "script_id": (raw.get("script_id") or "").strip(),
                "stage": (raw.get("stage") or "").strip(),
                "source": (raw.get("source") or "").strip(),
            }
        )
    return rows


def _known_script_ids() -> set[str]:
    data = json.loads((KB_DIR / "scripts.json").read_text(encoding="utf-8"))
    return {str(item["id"]) for item in data["scripts"]}


def validate_eval_set(rows: list[dict], expected_count: int = 40) -> list[str]:
    """逐条校验测评集，返回问题列表；空列表表示合规。"""
    problems: list[str] = []
    if len(rows) != expected_count:
        problems.append(f"条数应为 {expected_count}，实际 {len(rows)}")

    labels = [int(row.get("label", -1)) for row in rows]
    black, white = labels.count(1), labels.count(0)
    if black != white:
        problems.append(f"黑白样本应 1:1，实际 {black}:{white}")
    if any(label not in (0, 1) for label in labels):
        problems.append("label 只能是 0 或 1")

    known = _known_script_ids()
    for row in rows:
        rid = str(row.get("id", ""))
        text = str(row.get("text", "")).strip()
        if not rid:
            problems.append("存在空 id")
        if len(text) < 10:
            problems.append(f"{rid}: text 少于 10 字")
        if int(row.get("label", 0)) == 1:
            if row.get("script_id") not in known:
                problems.append(f"{rid}: script_id {row.get('script_id')!r} 不在 scripts.json")
            if not row.get("stage"):
                problems.append(f"{rid}: 黑样本 stage 为空")

    seen: set[str] = set()
    for row in rows:
        text = str(row.get("text", "")).strip()
        if text in seen:
            problems.append(f"{row.get('id', '')}: text 与前面的样本重复")
        seen.add(text)
    return problems


def measure(rows: list[dict], verbose: bool = False) -> dict:
    """跑一遍真实引擎，返回 n/tp/fp/tn/fn 与 P/R/F1/accuracy。

    ``verbose=True`` 时打印 markdown 明细表（一次遍历同时出表与指标）。
    每条样本用独立的 ``session_id``，避免多轮上下文互相污染。
    """
    engine = get_engine()
    tp = fp = tn = fn = 0
    details: list[tuple[str, int, int, float, bool]] = []
    for row in rows:
        _alert, decision, _latency = engine.detect_text(
            row["text"], session_id=f"eval-{row['id']}", role="normal"
        )
        predicted = int(decision.level) >= int(Level.L2)
        actual = int(row["label"]) == 1
        if actual and predicted:
            tp += 1
        elif actual and not predicted:
            fn += 1
        elif predicted and not actual:
            fp += 1
        else:
            tn += 1
        details.append(
            (row["id"], int(row["label"]), int(decision.level), float(decision.score), actual == predicted)
        )

    n = len(rows)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / n if n else 0.0

    if verbose:
        print("| id | label | level | score | 判对? |")
        print("| --- | --- | --- | --- | --- |")
        for rid, label, level, score, correct in details:
            print(f"| {rid} | {label} | L{level} | {score:.1f} | {'✓' if correct else '✗'} |")
        print()
        print(
            f"n={n} tp={tp} fp={fp} tn={tn} fn={fn} "
            f"P={precision:.3f} R={recall:.3f} F1={f1:.3f} accuracy={accuracy:.3f}"
        )

    return {
        "n": n,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "accuracy": round(accuracy, 3),
    }
