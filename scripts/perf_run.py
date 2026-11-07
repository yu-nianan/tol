"""HTTP 压测（纯标准库，threading + urllib）——默认口径 10 并发 × 10 分钟。

对应 NFR-1 / NFR-2、验收用例 TC-6.5：成功率 ≥ 99%，P95 < 10s。

用法（服务已起在 8000 端口）：

    python scripts/perf_run.py                          # 正式口径：10 并发 × 600 秒
    python scripts/perf_run.py --concurrency 3 --duration 10   # 短跑自检

口径说明：
- 请求：``POST /api/v1/detect/text``，body 为内置的无隐私样例文本；
- 成功率：HTTP 200 且响应里有 ``decision`` 字段的请求占比；
- 耗时：单请求端到端毫秒；P50/P95/P99 由原始样本排序后线性插值取；
- 吞吐：成功请求数 / 实际压测时长。
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ENDPOINT = "/api/v1/detect/text"
DEFAULT_CONCURRENCY = 10
DEFAULT_DURATION_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = 10

# 无隐私样例：一条正常消息 + 一条冒充公检法
SAMPLES = (
    "明天下午三点在图书馆三楼讨论，记得带笔记本和充电器。",
    "您好，我是市局经侦支队的，你的银行卡涉嫌洗钱，请把存款转到我们的安全账户，不要告诉任何人。",
    "您的快递已到小区门口，麻烦下楼取一下。",
    "我是客服，您的订单异常可以双倍退款，请打开屏幕共享并把验证码发给我。",
)


def _post_json(url: str, payload: dict[str, object], timeout: float) -> tuple[int, dict[str, object], float]:
    """发一个 JSON POST，返回 (状态码, JSON 体, 耗时毫秒)；网络错误向上抛。"""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return response.status, json.loads(body.decode("utf-8")), elapsed_ms


def _percentile(sorted_values: list[float], percent: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * percent / 100.0
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _worker(
    url: str,
    timeout: float,
    deadline: float,
    result: dict[str, object],
    lock: threading.Lock,
    worker_index: int,
) -> None:
    latencies: list[float] = []
    successes = 0
    failures = 0
    errors: dict[str, int] = {}
    sent = 0
    while time.monotonic() < deadline:
        payload = {
            "text": SAMPLES[(worker_index + sent) % len(SAMPLES)],
            "session_id": f"perf-{worker_index}-{sent}",
            "role": "normal",
        }
        sent += 1
        try:
            status, body, elapsed_ms = _post_json(url, payload, timeout)
            ok = status == 200 and isinstance(body.get("decision"), dict)
            if ok:
                successes += 1
                latencies.append(elapsed_ms)
            else:
                failures += 1
                key = f"http_{status}_or_bad_body"
                errors[key] = errors.get(key, 0) + 1
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            failures += 1
            key = type(exc).__name__
            errors[key] = errors.get(key, 0) + 1

    with lock:
        result["latencies"].extend(latencies)  # type: ignore[union-attr]
        result["successes"] = int(result["successes"]) + successes
        result["failures"] = int(result["failures"]) + failures
        all_errors = result["errors"]
        assert isinstance(all_errors, dict)
        for key, count in errors.items():
            all_errors[key] = int(all_errors.get(key, 0)) + count


def run(base_url: str, concurrency: int, duration: float, timeout: float, endpoint: str) -> dict[str, object]:
    url = base_url.rstrip("/") + endpoint
    result: dict[str, object] = {
        "latencies": [],
        "successes": 0,
        "failures": 0,
        "errors": {},
    }
    lock = threading.Lock()
    started = time.monotonic()
    deadline = started + duration
    workers = [
        threading.Thread(
            target=_worker,
            args=(url, timeout, deadline, result, lock, index),
            name=f"perf-{index}",
            daemon=True,
        )
        for index in range(concurrency)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    elapsed = time.monotonic() - started

    latencies = sorted(result["latencies"])  # type: ignore[arg-type]
    successes = int(result["successes"])
    failures = int(result["failures"])
    total = successes + failures
    return {
        "url": url,
        "concurrency": concurrency,
        "requested_duration_seconds": duration,
        "elapsed_seconds": round(elapsed, 3),
        "total_requests": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "latency_ms": {
            "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "p50": round(_percentile(latencies, 50), 2),
            "p95": round(_percentile(latencies, 95), 2),
            "p99": round(_percentile(latencies, 99), 2),
            "max": round(latencies[-1], 2) if latencies else 0.0,
        },
        "throughput_rps": round(successes / elapsed, 2) if elapsed > 0 else 0.0,
        "errors": result["errors"],
    }


def _verdict(summary: dict[str, object]) -> tuple[bool, bool]:
    success_rate = float(summary["success_rate"])
    latencies = summary["latency_ms"]
    assert isinstance(latencies, dict)
    p95 = float(latencies["p95"])
    return success_rate >= 0.99, p95 < 10_000.0


def main() -> int:
    parser = argparse.ArgumentParser(description="纯标准库 HTTP 压测（默认 10 并发 × 10 分钟）")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_SECONDS, help="压测时长（秒）")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="单请求超时（秒）")
    parser.add_argument("--json", action="store_true", help="只输出一行 JSON，便于写入评估报告")
    args = parser.parse_args()

    if args.concurrency < 1:
        parser.error("--concurrency 必须 >= 1")
    if args.duration <= 0:
        parser.error("--duration 必须 > 0")

    summary = run(args.base_url, args.concurrency, args.duration, args.timeout, args.endpoint)
    ok_rate, ok_p95 = _verdict(summary)
    summary["verdict"] = {
        "success_rate_ge_99pct": ok_rate,
        "p95_lt_10s": ok_p95,
        "passed": ok_rate and ok_p95,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if ok_rate and ok_p95 else 2

    latencies = summary["latency_ms"]
    assert isinstance(latencies, dict)
    print("=" * 62)
    print(f"压测口径：{summary['concurrency']} 并发 × {summary['requested_duration_seconds']:g} 秒")
    print(f"目标：{summary['url']}")
    print('=' * 62)
    print(
        "请求总数 {total}，成功 {successes}，失败 {failures}，成功率 {rate:.2%}".format(
            total=summary["total_requests"],
            successes=summary["successes"],
            failures=summary["failures"],
            rate=float(summary["success_rate"]),
        )
    )
    print(
        "耗时(ms)：avg {avg} | p50 {p50} | p95 {p95} | p99 {p99} | max {max}".format(**latencies)
    )
    print(f"吞吐：{summary['throughput_rps']} req/s（成功请求 / 实际 {summary['elapsed_seconds']}s）")
    print(f"错误分布：{summary['errors']}")
    print(f"判定：成功率≥99% {'PASS' if ok_rate else 'FAIL'}；P95<10s {'PASS' if ok_p95 else 'FAIL'}")
    print("JSON：" + json.dumps(summary, ensure_ascii=False))
    return 0 if ok_rate and ok_p95 else 2


if __name__ == "__main__":
    raise SystemExit(main())
