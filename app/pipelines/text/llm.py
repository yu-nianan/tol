"""LLM 证据抽取：外部 HTTP 模型只负责"这段话命中了哪几条话术"，不负责打分。

设计约束（AGENTS.md §1.1）：
- 只用标准库 urllib 发请求，不引入 openai 之类的 SDK，也不新增依赖；
- 未配置 ``LLM_BASE_URL`` / ``LLM_API_KEY`` / ``LLM_MODEL`` 时返回空列表，绝不编造证据；
- 模型输出必须先过白名单校验（编号固定 11 个、文本必须非空、置信度裁剪到 0–1），
  再把权重压到 0.8 以下 —— 规则层与知识库的权重优先，模型只能补充不能压倒。

对外只有两个动词：``extract_evidence``（主入口）与 ``load_config``（读配置）。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import Evidence, Modality, SourceKind

log = get_logger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "evidence_v1.md"

# 提示词里约定的 11 个固定编号 → (展示名, 类别, 权重上限)
ALLOWED_CODES: dict[str, tuple[str, str, float]] = {
    "impersonate_authority": ("冒充权威身份", "authority", 0.80),
    "isolation": ("要求保密/隔离", "isolation", 0.75),
    "transfer_demand": ("要求转账/验证码", "transfer", 0.80),
    "pressure": ("制造紧迫感", "pressure", 0.65),
    "prize": ("中奖/返利", "gift", 0.60),
    "campus": ("校园场景话术", "scene", 0.60),
    "fake_service": ("冒充客服", "service", 0.70),
    "fake_loan": ("贷款/征信", "loan", 0.70),
    "acquaintance": ("冒充熟人", "acquaintance", 0.70),
    "fake_invest": ("投资理财", "invest", 0.70),
    "brushing": ("刷单返佣", "brushing", 0.70),
}

MAX_TEXT = 60
MAX_CONFIDENCE_WEIGHT = 0.80


@dataclass(frozen=True)
class ModelConfig:
    """一次调用的最小连接信息；为空就表示"未启用"。"""

    base_url: str
    api_key: str
    model: str
    timeout: float = 6.0

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def load_config() -> ModelConfig | None:
    """从环境变量读配置（每次现读，测试可以直接 monkeypatch 环境）。

    三个变量缺一个都返回 None —— 宁可"未启用"，也不要拿半套配置去猜。
    """
    base_url = os.getenv("LLM_BASE_URL", "").strip() or settings.llm_base_url
    api_key = os.getenv("LLM_API_KEY", "").strip() or settings.llm_api_key
    model = os.getenv("LLM_MODEL", "").strip() or settings.llm_model
    raw_timeout = os.getenv("LLM_TIMEOUT", "").strip()
    try:
        timeout = float(raw_timeout) if raw_timeout else 6.0
    except ValueError:
        timeout = 6.0
    if not (base_url and api_key and model):
        return None
    return ModelConfig(base_url=base_url, api_key=api_key, model=model, timeout=timeout)


def _load_template() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return "# evidence_v1\n\n待分析文本：\n{{TEXT}}\n"


def _build_prompt(text: str, hints: list[str]) -> str:
    template = _load_template()
    hint_text = "、".join(hints) if hints else "无"
    return template.replace("{{TEXT}}", text).replace("{{HINTS}}", hint_text)


def _post(prompt: str, cfg: ModelConfig) -> str:
    body = {
        "model": cfg.model,
        "temperature": 0,
        "max_tokens": 600,
        "messages": [
            {"role": "system", "content": "你是反诈文本分析器，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        cfg.endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=cfg.timeout) as response:  # noqa: S310 - 仅 http(s)
        return response.read().decode("utf-8", errors="replace")


def _strip_fence(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip()


def _parse_evidences(raw_response: str) -> list[Evidence]:
    try:
        payload = json.loads(raw_response)
        content = payload["choices"][0]["message"]["content"]
        data = json.loads(_strip_fence(content))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning("LLM 返回无法解析，按 0 条处理：%s", exc)
        return []

    rows = data.get("evidences") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        log.warning("LLM 返回缺少 evidences 数组，按 0 条处理")
        return []

    evidences: list[Evidence] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "")).strip()
        spec = ALLOWED_CODES.get(code)
        if spec is None:
            continue  # 自造编号一律丢弃
        text = str(row.get("text", "")).strip()[:MAX_TEXT]
        if not text:
            continue
        try:
            confidence = float(row.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        label, category, weight_cap = spec
        evidences.append(
            Evidence(
                code=f"llm_{code}",
                label=f"模型识别：{label}",
                category=category,
                text=text,
                weight=round(min(weight_cap, MAX_CONFIDENCE_WEIGHT * confidence), 4),
                confidence=confidence,
                modality=Modality.TEXT,
                kind=SourceKind.MODEL,
                meta={"source": "llm", "model_code": code},
            )
        )
    return evidences


def extract_evidence(text: str, hints: list[str] | None = None) -> list[Evidence]:
    """调外部模型抽证据；任何失败都退化为空列表，绝不抛给上层。"""
    cfg = load_config()
    if cfg is None:
        return []
    if not text.strip():
        return []
    prompt = _build_prompt(text, hints or [])
    try:
        raw = _post(prompt, cfg)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("LLM 调用失败，按 0 条处理：%s", exc)
        return []
    return _parse_evidences(raw)
