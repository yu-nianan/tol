---
title: 任务回执：LLM 证据抽取（T-06，负责人 队长）
owner: 队长
status: final
last_updated: 2026-11-07
related_code: "app/pipelines/text/llm.py, app/pipelines/text/prompts/evidence_v1.md, tests/text/test_llm.py"
summary: 用外部 OpenAI 兼容接口把"可疑话术"抽成结构化 Evidence；未配置或任何失败都返回空列表，不编造、不抛异常
audience: agent
depends_on: [../INDEX.md]
---

# 任务回执：T-06 LLM 证据抽取（负责人 队长）

## 做了什么

- `app/pipelines/text/prompts/evidence_v1.md`：system 段固定 11 个证据编号（`impersonate_authority` /
  `isolation` / `transfer_demand` / `pressure` / `prize` / `campus` / `fake_service` / `fake_loan` /
  `acquaintance` / `fake_invest` / `brushing`），明确只许输出 `{"evidences":[{code,text,confidence}]}`，
  并写死"禁止输出 score / level / advice，等级由规则引擎决定"；user 段用 `{{TEXT}}`、`{{HINTS}}` 占位。
- `app/pipelines/text/llm.py`：`ModelConfig(base_url, api_key, model, timeout=6.0)` + `.endpoint`；
  `load_config()` 现读四个环境变量，缺任一要素返回 `None`；`extract_evidence(text, hints=None)`
  用 `urllib.request` 发 OpenAI 兼容 `chat/completions` 请求（不新增依赖），解析时去 Markdown 围栏、
  按白名单校验 code、`text` 截 60 字、`confidence` 裁剪到 0–1、`weight = min(0.80, 0.80 * confidence)`，
  产出 `Evidence(kind=SourceKind.MODEL, code="llm_<code>", meta={"source": "llm"})`。
- 失败策略：未配置 → 0 次网络调用；超时/连接错/HTTP 非 2xx/坏 JSON/未知 code → `log.warning` 后返回 `[]`，
  **从不抛异常**，不吞掉"返回空"这件事（警告日志里带 session 无关的原始错误片段，不含原文）。
- `tests/text/test_llm.py` 7 条：未配置不发请求、正常解析与权重上限、忽略模型自带的 score/level、
  丢弃自造 code、坏 JSON、网络错误、`load_config` 缺 env 返回 None（假 `urlopen`，全离线）。

## 没做完 / 已知问题

- **没有真实 key 的联调**：本机与 CI 都没有 `LLM_BASE_URL`，所以只验证了"协议形状正确"和"降级正确"，
  真实模型的抽取质量（recall、是否乱编 code）要等演示前用真 key 跑一遍 `docs/测评集` 才能下结论。
- 提示词只有 v1：没有 few-shot 示例，长文本（>2000 字）会被整段塞进 user 段，超出模型上下文时依赖服务端截断，
  目前没有本地长度上限保护（`DetectTextRequest.text` 上限 4000 字是唯一约束）。
- `hints` 目前只传命中剧本的阶段标签；没有把"上一轮已抽取的证据"传给模型做指代消解（"他说"指谁），
  跨轮代词的抽取质量有限。
- 与初稿的差异：第二参数由 `script_hits: list[ScriptHit]` 改为 `hints: list[str]`（避免模型层依赖知识库对象）；
  code 词表 11 条（多一个 `brushing`）；`load_config` 要求三要素齐全。

## 下次接手要知道什么

- 入口：`extract_evidence(text, hints=None) -> list[Evidence]`（`app/pipelines/text/llm.py`）。
  调用方是 `app/pipelines/decision/engine.py` 的 `detect_text`，**只在 `settings.llm_enabled` 为真时调用**。
- 环境变量：`LLM_BASE_URL`（写到 `/v1` 或直接以 `/chat/completions` 结尾都可）、`LLM_API_KEY`、
  `LLM_MODEL`、`LLM_TIMEOUT`（默认 6 秒）。三个必需项缺一个就静默降级为纯规则。
- 权重上限 0.8 是刻意的：模型证据单条不能把分数顶满，避免"模型一句话就 L3"；想让模型影响更大，
  改 `_extract` 里的 `min(0.80, ...)` 并同步改本回执与 `docs/modules/decision.md`。
- 测试里改 `llm.settings` 必须整个替换 `types.SimpleNamespace`，`Settings` 是 frozen dataclass。
- 想换提示词就加 `evidence_v2.md` 并在 `llm.py` 顶部改 `PROMPT_PATH`，不要原地改 v1（回执与 ticket 都按 v1 验收）。

## 怎么验收

```powershell
# 单测（不需要任何 key，也不会发真实请求）
& .\.venv\Scripts\python.exe -m pytest tests/text/test_llm.py -q
# 应当看到：7 passed

# 全绿口径
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m ruff check .
python scripts/docs.py check
```

## 改动清单

- 新增 `app/pipelines/text/llm.py`
- 新增 `app/pipelines/text/prompts/evidence_v1.md`
- 新增 `tests/text/test_llm.py`
- 契约变更：无（只消费既有 `Evidence` / `SourceKind.MODEL`）
- 工具行：`pytest tests/text/test_llm.py -q` → 7 passed；`ruff check app/pipelines/text tests/text` → All checks passed
