---
title: T-06 M5 接大模型：结构化证据抽取（队长代做，owner 记队长）
owner: 队长
status: final
last_updated: 2026-11-05
related_code: app/pipelines/text, app/core/config.py, tests/text
summary: 用标准库调 OpenAI 兼容接口，只让它吐证据、不让它给分；没 key 时安静降级
audience: agent
depends_on: [../INDEX.md, ../需求清单.md, ../decisions/ADR-0002-evidence-contract.md]
---

# 任务单：M5 接入大模型（只出证据，不出分数）

> **归属说明**：`app/pipelines/text/**` 在 `OWNERS.md` 里属于 A。本单由队长代做，
> 因为 A 手上已有 T-01（语料）与 T-05（测评集）。回执里 `owner` 写 **队长**，正文「工具：」一行写清是哪个 agent 做的。

## 1. 背景（为什么做这件事）

- 对应需求：`FR-2.1`（文本判别）、`FR-2.4a`（多模态融合里的文本侧证据）
- 对应测试用例：`TC-2.1`（诈骗文本判 L2 以上）、`TC-2.7`（模型超时不得让服务 500）
- 现状：`app/pipelines/text/rules.py` 是 12 类关键词 + 4 类渠道正则的规则版。
  规则能保证"可解释"，但漏判明显（换同义词、加错别字就穿）。M5 是方案里"语言理解"那一格，现在是空的。
- 一句话：让模型**只做一件事**——把"这句话像哪一类诈骗、处在哪个阶段、命中了哪些信号"抽成结构化证据；
  **分数仍然由 `decision/scoring.py` 算**（这是 ADR-0003 的分界线，不许破）。

## 2. 目标（做完之后，什么会不一样）

1. 新增 `app/pipelines/text/llm.py`：

```python
@dataclass
class ModelConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 6.0

def load_config() -> ModelConfig | None:      # 缺 base_url 或 api_key → None（不抛）
    ...

def extract_evidence(text: str, script_hits: list[ScriptHit]) -> list[Evidence]:
    """调模型，返回 kind=EvidenceKind.MODEL 的证据；任何失败都返回 []，不抛。"""
```

2. 只用**标准库**（`urllib.request` + `json`），打 `POST {base_url}/chat/completions`，
   请求体 `{"model":..., "messages":[...], "temperature":0, "response_format":{"type":"json_object"}}`。
   解析失败时从返回文本里用正则捞第一个 `{...}` 再 `json.loads`（现实里模型的 JSON 常常带 ``` 包裹）。
3. 提示词放 `app/pipelines/text/prompts/evidence_v1.md`（独立文件，便于改版与对比），内容三块：
   - 角色与边界：**只抽证据，不许给分、不许给等级**
   - 输出 schema 与 10 条 `code` 词表（与 `rules.py` 对齐，便于合并去重）
   - 3 个 few-shot：冒充公检法 / 刷单返利 / 正常聊天（正常样本必须输出空数组）
4. `decision/` 侧一行接入：`evidence = rules.extract(text) + llm.extract_evidence(text, hits)`，
   交给现有 `dedupe()`；**不改打分公式**。
5. `tests/text/test_llm.py` 至少 5 条（全部离线，用 monkeypatch 替换 `urllib.request.urlopen`）：
   - 正常 JSON → 2 条 `kind="model"` 证据
   - 超时（`socket.timeout`）→ `[]` 且不抛
   - 坏 JSON（返回 `<html>502</html>`）→ `[]`
   - 没配置（`load_config()` 为 None）→ `[]`
   - 模型返回里有"score"字段 → 必须被忽略（证明分数量没被模型篡改）

## 3. 输入 / 输出样例（写死，不要"大概"）

```python
hits = kb.match_script("我是市局的，你要配合调查")
ev = extract_evidence(text, hits)
# [Evidence(code="authority_claim", label="冒充公职人员", category="话术",
#           text="我是市局的", weight=0.9, confidence=0.86, modality="text", kind="model")]
```

## 4. 允许修改的路径（超出即越界）

```
app/pipelines/text/llm.py
app/pipelines/text/prompts/**
app/pipelines/text/rules.py        # 只允许加 code 词表常量，不许改 extract() 行为
app/core/config.py                 # 只加 LLM_* 三个配置项
app/pipelines/decision/engine.py   # 只加 llm 证据合并那一行
tests/text/**
```

## 5. 不许做的事（本次特有）

- 不许新增依赖（不许 `openai` / `requests` / `httpx`）；只用 `urllib.request`
- 不许把 key 写进代码或 `.env.example` 的真实值；`env` 只留空占位
- 不许让模型返回分数/等级；不许把 `response["score"]` 塞进 `Decision`
- 不许把"模型没配"做成报错；必须是静默降级 + 一条 warning 日志
- 不许在测试里真联网（CI 没网；联网测试一律不许进 `tests/`）

## 6. 验收命令（必须全绿）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task lint
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task test
python scripts/docs.py check
```

附加验收（有 key 时人工做一次）：

- [ ] 配好 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL` 后启动，用现成的诈骗话术打一次 `/api/v1/detect/text`，
      贴出响应里 `evidence` 中 `kind="model"` 的条目（脱敏）
- [ ] 把 key 删掉再打一次，确认服务不 500、响应里只有规则证据
- [ ] 贴一次"规则判 L1、加模型证据后判 L2/L3"的对照（证明模型确实补上了漏判）

## 7. 预计与截止

| 项 | 内容 |
|---|---|
| 负责人 | 队长（代 A） |
| 预计耗时 | 1.5 天（prompt 0.5 天 / 调用与解析 0.5 天 / 测试 0.5 天） |
| 截止 | 周三晚 22:00 |
| 卡住找谁 | 自己 |

## 8. 交付时会问的三个问题（提前想好）

1. 模型给了分数你不用，为什么？如果评委问"大模型到底起了什么作用"，你怎么演示？
2. 6 秒超时怎么定的？网上慢的时候用户看到什么？
3. 同一条话术，规则和模型各给一条证据，会不会重复计分？（提示：`dedupe()` 按 code 去重）
