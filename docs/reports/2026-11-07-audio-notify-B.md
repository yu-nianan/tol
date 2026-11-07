---
title: 任务回执：音频 VAD/ASR、监护人与报告、会话与画像（负责人 B）
owner: B
status: final
last_updated: 2026-11-07
related_code: "app/pipelines/audio/asr.py, app/pipelines/notify/, app/pipelines/memory/, app/api/alerts.py"
summary: T-02 纯标准库能量 VAD + 16k 重采样；T-11 三档×三渠道推送、五段报告与单文件 HTML、周报聚合、ack 回写；T-09 sqlite3 会话记忆、画像偏移、30 分钟冷却与白名单
audience: agent
depends_on: [../INDEX.md]
---

# 任务回执：T-02 / T-11 / T-09（负责人 B）

## 做了什么

- **T-02 音频**：`app/pipelines/audio/asr.py` 改为纯标准库（wave/array/math），30ms 帧 RMS、峰值 ×0.15 阈值、静音 ≥300ms 切段、上限 200 段、立体声混单、非 16k 最近邻重采样；非 PCM/16bit 或乱码抛 `UnsupportedAudioFormat`；无 ASR 模型时返回 `backend="energy-vad-only"`、`text=""`、`confidence=0.0`，不抛异常。
- **T-11 监护人与报告**：`notify/guardian.py` 三档×三渠道（L1 站内 / L2 +语音 / L3 +监护人），未接入的语音通道与未配置的 webhook 一律如实 `skipped`，配置了才 `httpx.post`，2xx 才 `sent`；`record_ack_in_session()` 把人工处置写回会话；`notify/report_builder.py` 输出五段报告并新增 `render_report_html()`（单文件、内联 CSS、`@media print`、全字段 HTML 转义）；`notify/weekly.py` 提供周报聚合入口；`app/api/alerts.py` 的 ack 接口在改状态后回写会话；报告与日志统一脱敏（`sanitize.py`）。
- **T-09 会话与画像**：新建 `app/pipelines/memory/`，sqlite3 落盘 `sessions / messages / alerts` 三表；`recent_summary()` 取最近 5 轮、硬上限 200 字，`context_evidence()` 包装成 `Evidence(kind=CONTEXT)`；`build_profile(evidences, role, alert_count=0)` 把角色偏移 + 近 30 天历史告警次数折算成阈值偏移并生成可读原因（写进 `Decision.reasons`）；`should_notify()` 实现同会话 30 分钟同等级（或更高等级）冷却；`match_whitelist()` 命中可信号码直接降 L0 并给出原因。

## 没做完 / 已知问题

- **T-09 的 engine.py 接线未做**：按队长 2026-11-07 调整，`app/pipelines/decision/engine.py` 由队长在 T-07 中统一改，B 只交付独立模块与测试；接口清单见下一节，接线时直接调用即可。
- **L1/L2 的端到端推送尚未触发**：现有 `engine.py` 只在 `level >= L3` 调 `notify_guardian`，因此站内（L1）与语音（L2）映射目前只有单测覆盖。队长接线时把触发条件改成 `level >= L1` 即可（`guardian` 对 L0 返回空渠道，安全）。
- **语音外呼通道未接入**：没有供应商配置，`_deliver_voice` 恒为 `skipped`，演示时需口播说明；未配置 `GUARDIAN_WEBHOOK` 时监护人渠道同样 `skipped`，不会假装发送。
- 按队长要求未运行 `python scripts/docs.py`、未跑全量 pytest、未执行任何 git 命令（提交由队长统一做）。

## 下次接手要知道什么

- 入口与文件：
  - `transcribe(audio_bytes, suffix=".wav") -> Transcript`（`app/pipelines/audio/asr.py`），`app/api/detect.py` 已由队长接好。
  - `notify_guardian(alert, decision) -> dict` / `record_ack_in_session(state, alert, action, note)`（`app/pipelines/notify/guardian.py`）。
  - `build_report(...)` / `render_report_html(report)`（`app/pipelines/notify/report_builder.py`）。
  - `build_weekly_digest(alerts, now=None, days=7)`（`app/pipelines/notify/weekly.py`）。
  - `MemoryStore`、`build_profile(evidences, role, alert_count=0) -> dict`、`should_notify(store, session_id, level, now=None) -> (bool, str)`、`match_whitelist(text, entries=None) -> str | None`（`app/pipelines/memory/`）。
- 关键约定：冷却窗口常量 `COOLDOWN_MINUTES = 30`；摘要 `SUMMARY_TURNS = 5`、`SUMMARY_MAX_CHARS = 200`；画像每多一次历史告警 +2.0 分、最多 +8.0，合计偏移封顶 ±18；白名单默认是公开演示号码（96110 / 12381 / 95588 / 110），真实部署应从配置加载。
- 测试数据库用 `tmp_path`；"重启"用同一 db 路径新建 `MemoryStore` 实例模拟，历史仍可读。
- 脱敏规则来自 `app/pipelines/text/normalize.py::mask_sensitive`，报告与 webhook payload 都过 `mask_data()`；新增日志字段时不要把原文整段写进 `extra`。

## 怎么验收

按队长指定的三条命令（未跑全量 pytest / 文档门禁）：

```
命令：& .\.venv\Scripts\python.exe -m pytest tests/audio tests/notify tests/memory -q
输出：
..................................................                       [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  E:\deepseek\服务外部自测试\tol\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
（50 passed：tests/audio 10 + tests/notify 16 + tests/memory 24）
```

```
命令：& .\.venv\Scripts\python.exe -m ruff check app/pipelines/audio app/pipelines/notify app/pipelines/memory app/api/alerts.py tests/audio tests/notify tests/memory
输出：All checks passed!
```

T-11 额外自验（`render_report_html` 开头 10 行 + 未配 webhook 的实际返回）：

```
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>反诈风险分析报告 - demo</title>
<style>body{margin:0;padding:28px;background:#f3f4f6;color:#111827;font:14px/1.7 "Microsoft YaHei","PingFang SC",sans-serif}.sheet{max-width:860px;margin:0 auto;background:#fff;padding:36px 44px;border:1px solid #d1d5db;border-radius:8px}header{border-bottom:3px solid #1d4ed8;padding-bottom:12px;margin-bottom:22px}h1{margin:0 0 6px;font-size:22px;color:#1d4ed8}.meta{color:#6b7280;font-size:13px}.badge{display:inline-block;padding:2px 10px;border-radius:999px;background:#fee2e2;color:#b91c1c;font-weight:600}section{margin:22px 0}h2{font-size:16px;margin:0 0 10px;padding-left:10px;border-left:4px solid #1d4ed8}table{width:100%;border-collapse:collapse;font-size:13px}th,td{border:1px solid #d1d5db;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f3f4f6;white-space:nowrap}.kv th{width:140px}.empty{color:#6b7280}pre{white-space:pre-wrap;word-break:break-all;background:#f9fafb;border:1px solid #e5e7eb;padding:10px;font-size:12px}ol{margin:0;padding-left:22px}footer{margin-top:28px;padding-top:12px;border-top:1px dashed #d1d5db;color:#6b7280;font-size:12px}@media print{body{padding:0;background:#fff}.sheet{max-width:none;border:0;border-radius:0;padding:0}.no-print{display:none}}</style>
</head>
<body>
<main class="sheet">

--- 未配 webhook 的实际返回 ---
{'status': 'skipped', 'sent': False, 'channels': [{'channel': 'in_app', 'status': 'recorded'}, {'channel': 'voice', 'status': 'skipped'}, {'channel': 'guardian', 'status': 'skipped'}]}
```

契约变更：无（`Decision.stage_index / cited_case_ids`、`SourceKind.CONTEXT / CROSS_MODAL` 均按队长冻结的契约使用）。

工具：DSH agent（负责人 B 代理）

## 改动清单

- `app/pipelines/audio/asr.py`（重写：纯标准库能量 VAD、Segment/Transcript、重采样、格式校验）
- `app/pipelines/notify/sanitize.py`（新增：`mask_text` / `mask_data` 递归脱敏）
- `app/pipelines/notify/guardian.py`（重写：三档×三渠道、真实 skipped/sent、webhook 投递、ack 回写）
- `app/pipelines/notify/report_builder.py`（重写：五段报告 + `render_report_html`、全字段脱敏）
- `app/pipelines/notify/weekly.py`（新增：`build_weekly_digest` 周报聚合）
- `app/pipelines/memory/__init__.py`、`store.py`、`profile.py`、`cooldown.py`、`whitelist.py`（新增：sqlite3 三表、摘要、画像偏移、冷却、白名单）
- `app/api/alerts.py`（ack 后调用 `record_ack_in_session` 回写会话）
- `tests/audio/test_asr.py`（10 条：正弦/静音/乱码/空字节/非 wav/8bit/48k 立体声/切段/封顶）
- `tests/notify/`（16 条：conftest、三档映射、脱敏 payload、500/网络错、ack 回写与端点、五段 HTML、转义、周报、日志脱敏）
- `tests/memory/`（24 条：三表、摘要上限、重启、上下文证据、告警/ack、画像偏移、冷却、白名单）
- `docs/reports/2026-11-07-audio-notify-B.md`（本回执）
