"""冒烟测试：服务能不能起、能不能判别、能不能在 10 秒内返回。

只用标准库。用法：
    python scripts/smoke.py                     # 默认 http://127.0.0.1:8000
    $env:SMOKE_BASE_URL=http://127.0.0.1:8123; python scripts/smoke.py

判定口径（写死在脚本里，避免"感觉能跑"）：
    1. /health 返回 200 且知识库已加载
    2. 诈骗文本 → score ≥ 60 且 level ≥ 2
    3. 正常文本 → level ≤ 1
    4. 单次检测端到端 < 10 秒
    5. 空文本 → 422
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

SCAM = (
    "您好，我是市局经侦支队的，你的银行卡涉嫌洗钱，现在需要你配合资金审查，"
    "不要告诉任何人，把存款转到我们的安全账户，半小时内完成，否则后果自负。"
)
SCAM2 = "亲，这个订单异常可以双倍退款，你加一下客服微信，打开屏幕共享我帮你操作。"
NORMAL = "明天下午三点在图书馆三楼讨论，记得带笔记本和充电器。"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")


def request(method: str, path: str, payload: dict | None = None, timeout: float = 15.0):
    url = f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else None), (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed, (time.perf_counter() - started) * 1000


def detect(text: str, session_id: str = "smoke", role: str = "normal"):
    return request("POST", "/api/v1/detect/text", {"text": text, "session_id": session_id, "role": role})


def main() -> int:
    try:
        status, body, _ = request("GET", "/health")
    except urllib.error.URLError as exc:
        print(f"[FAIL] 连不上 {BASE}：{exc.reason}")
        print("       先在另一个终端跑：python -m uvicorn app.main:app --port 8000")
        return 1

    ok = status == 200 and bool(body) and body.get("kb_scripts", 0) > 0
    check("1/5 health", ok, f"status={status} kb_scripts={(body or {}).get('kb_scripts')}")

    status, body, ms = detect(SCAM, "smoke-1", "elder")
    decision = (body or {}).get("decision", {}) or {}
    ok = status == 200 and decision.get("score", 0) >= 60 and decision.get("level", 0) >= 2
    check("2/5 诈骗文本判为高危", ok, f"status={status} score={decision.get('score')} level={decision.get('level')}")

    status, body, _ = detect(NORMAL, "smoke-2")
    decision = (body or {}).get("decision", {}) or {}
    ok = status == 200 and decision.get("level", 9) <= 1
    check("3/5 正常文本不误报", ok, f"status={status} score={decision.get('score')} level={decision.get('level')}")

    status, body, ms = detect(SCAM2, "smoke-3", "student")
    check("4/5 端到端 < 10s", status == 200 and ms < 10000, f"latency={ms:.0f}ms")

    status, body, _ = detect("   ", "smoke-4")
    check("5/5 空文本被拒", status == 422, f"status={status}")

    failed = [name for name, ok, _ in results if not ok]
    print()
    if failed:
        print(f"结果：{len(results) - len(failed)}/{len(results)} 通过，失败：{', '.join(failed)}")
        return 1
    print(f"结果：{len(results)}/{len(results)} 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
