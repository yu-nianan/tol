r"""T-01 检索自检（手动跑，不进 pytest 收集）：

用每条案例的原文去检索，看 Top-1 是否命中它自己的 script_id。
目标 ≥85%；把输出贴进回执。运行方式（仓库根目录）：

    $env:PYTHONPATH="."; .\.venv\Scripts\python.exe tests\knowledge\selfcheck_retrieval.py
"""

from __future__ import annotations

from collections import Counter

from app.core.config import KB_DIR
from app.pipelines.knowledge.store import KnowledgeBase


def main() -> int:
    kb = KnowledgeBase(KB_DIR)
    hits = 0
    misses: list[tuple[str, str, str, str]] = []
    per_script: dict[str, list[int]] = {}

    for case in kb.cases:
        results = kb.search_cases(case.text, top_k=1)
        top_script = results[0][0].script_id if results else "-"
        ok = top_script == case.script_id
        hits += int(ok)
        per_script.setdefault(case.script_id, [0, 0])[0] += int(ok)
        per_script[case.script_id][1] += 1
        if not ok:
            misses.append((case.id, case.script_id, top_script, case.text))

    total = len(kb.cases)
    print(f"scripts={kb.script_count} cases={total}")
    print(f"Top-1 自命中：{hits}/{total} = {hits / total:.1%}")
    for script_id in sorted(per_script):
        ok, count = per_script[script_id]
        print(f"  {script_id}: {ok}/{count}")
    if misses:
        print("未命中明细：")
        for case_id, expected, got, text in misses:
            print(f"  {case_id} 期望 {expected} 实得 {got}  {text}")
    print("script_id 分布：", dict(sorted(Counter(c.script_id for c in kb.cases).items())))
    return 0 if hits / total >= 0.85 else 1


if __name__ == "__main__":
    raise SystemExit(main())
