"""24h 守护打点（纯标准库）：每小时一条 JSONL，记录内存 / 耗时 / 异常计数。

对应 NFR-3、验收用例 TC-6.6（连续跑批不崩、无未捕获异常、内存无持续增长）。

用法：

    python scripts/guard_24h.py                    # 默认 24h，每小时打点，输出 data/guard/guard_24h.jsonl
    python scripts/guard_24h.py --interval 5 --duration 20   # 短跑自检
    python scripts/guard_24h.py --pid 12345         # 同时采样服务进程 RSS（Windows/Linux）

每条 JSONL 字段：
    ts / iso / tick / health_ok / health_ms / detect_ok / detect_ms /
    detect_level / error / rss_bytes / guard_rss_bytes /
    errors_total / failures_total / ticks_total

``rss_bytes`` 只在给了 ``--pid`` 时才有值（标准库没有跨平台查别的进程内存的接口：
Windows 用 ctypes 调 psapi，Linux 读 /proc/<pid>/status）；否则为 null，不伪造。
``guard_rss_bytes`` 是守护脚本自己的 RSS，用于确认脚本本身没有泄漏。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_INTERVAL_SECONDS = 3600.0
DEFAULT_DURATION_SECONDS = 24 * 3600.0
DEFAULT_OUT = "data/guard/guard_24h.jsonl"
DEFAULT_TIMEOUT_SECONDS = 10.0

PROBE_TEXT = "您好，我是市局经侦支队的，你的银行卡涉嫌洗钱，请把存款转到我们的安全账户。"


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _windows_rss_bytes(pid: int) -> int | None:
    if os.name != "nt":
        return None
    process_query_limited_information = 0x1000
    process_vm_read = 0x0010
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information | process_vm_read, False, pid)
    if not handle:
        return None
    try:
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.WorkingSetSize)
    finally:
        kernel32.CloseHandle(handle)


def _linux_rss_bytes(pid: int) -> int | None:
    status_path = Path(f"/proc/{pid}/status")
    if not status_path.is_file():
        return None
    for line in status_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    return None


def sample_rss_bytes(pid: int | None) -> int | None:
    """采样目标进程 RSS；采不到返回 None（不伪造 0）。"""
    if pid is None:
        return None
    try:
        if os.name == "nt":
            return _windows_rss_bytes(pid)
        return _linux_rss_bytes(pid)
    except (OSError, ValueError):
        return None


def _http_get(url: str, timeout: float) -> tuple[bool, float]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            response.read()
            return response.status == 200, (time.perf_counter() - started) * 1000.0
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, (time.perf_counter() - started) * 1000.0


def _http_detect(url: str, timeout: float) -> tuple[bool, float, str]:
    payload = json.dumps(
        {"text": PROBE_TEXT, "session_id": "guard-24h", "role": "normal"}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            decision = body.get("decision") if isinstance(body, dict) else None
            level = ""
            if isinstance(decision, dict):
                level = str(decision.get("level", ""))
            return response.status == 200 and isinstance(decision, dict), elapsed_ms, level
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False, (time.perf_counter() - started) * 1000.0, ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description="24h 守护打点（JSONL：内存/耗时/异常计数）")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS, help="打点间隔（秒）")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_SECONDS, help="总时长（秒）")
    parser.add_argument("--out", default=DEFAULT_OUT, help="JSONL 输出路径")
    parser.add_argument("--pid", type=int, default=None, help="服务进程 PID（可选，用于采样 RSS）")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--once", action="store_true", help="只打一个点就退出（自检用）")
    args = parser.parse_args()

    if args.interval <= 0:
        parser.error("--interval 必须 > 0")
    if args.duration <= 0:
        parser.error("--duration 必须 > 0")

    base_url = args.base_url.rstrip("/")
    health_url = base_url + "/health"
    detect_url = base_url + "/api/v1/detect/text"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    tick = 0
    errors_total = 0
    failures_total = 0
    guard_rss = sample_rss_bytes(os.getpid())

    while True:
        tick += 1
        health_ok, health_ms = _http_get(health_url, args.timeout)
        detect_ok, detect_ms, level = _http_detect(detect_url, args.timeout)
        rss = sample_rss_bytes(args.pid)
        guard_rss = sample_rss_bytes(os.getpid())
        if not (health_ok and detect_ok):
            failures_total += 1
            errors_total += 1
        record = {
            "ts": round(time.time(), 3),
            "iso": _now_iso(),
            "tick": tick,
            "health_ok": health_ok,
            "health_ms": round(health_ms, 2),
            "detect_ok": detect_ok,
            "detect_ms": round(detect_ms, 2),
            "detect_level": level,
            "error": "" if health_ok and detect_ok else "health_or_detect_failed",
            "rss_bytes": rss,
            "guard_rss_bytes": guard_rss,
            "errors_total": errors_total,
            "failures_total": failures_total,
            "ticks_total": tick,
        }
        line = json.dumps(record, ensure_ascii=False)
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)

        if args.once:
            break
        elapsed = time.monotonic() - started
        remaining = args.duration - elapsed
        if remaining <= 0:
            break
        time.sleep(min(args.interval, remaining))

    summary = {
        "out": str(out_path),
        "ticks": tick,
        "failures_total": failures_total,
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    if sys.stdout.isatty() and tick > 0:
        print("提示：正式口径 --interval 3600 --duration 86400（24h，每小时一个点）", flush=True)
    return 0 if failures_total == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
