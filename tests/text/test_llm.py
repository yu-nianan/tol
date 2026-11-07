"""LLM 证据抽取的单测：不联网，全部走 monkeypatch 假响应。"""

from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace

import pytest

from app.pipelines.text import llm
from app.schemas import Modality, SourceKind


def _blank_settings() -> SimpleNamespace:
    return SimpleNamespace(llm_base_url="", llm_api_key="", llm_model="")


class FakeResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


def _completion(evidences: list[dict] | None = None, raw: str | None = None) -> str:
    content = raw if raw is not None else json.dumps({"evidences": evidences or []}, ensure_ascii=False)
    return json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def test_load_config_returns_none_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.setenv(key, "")
    monkeypatch.setattr(llm, "settings", _blank_settings())
    assert llm.load_config() is None


def test_extract_evidence_skips_call_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setattr(llm, "settings", _blank_settings())

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("未配置时不应该发请求")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    assert llm.extract_evidence("您的账户涉嫌洗钱，请配合调查") == []


def test_extract_evidence_parses_and_caps_weight(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        llm.urllib.request,
        "urlopen",
        lambda *_a, **_k: FakeResponse(
            _completion([{"code": "transfer_demand", "text": "把存款转到安全账户", "confidence": 1.0}])
        ),
    )
    evidences = llm.extract_evidence("把存款转到安全账户", ["transfer_demand"])
    assert len(evidences) == 1
    item = evidences[0]
    assert item.code == "llm_transfer_demand"
    assert item.kind is SourceKind.MODEL
    assert item.modality is Modality.TEXT
    assert item.confidence == 1.0
    assert item.weight <= llm.MAX_CONFIDENCE_WEIGHT  # 模型权重不得压过规则层 0.95


def test_extract_evidence_ignores_score_and_level_fields(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = json.dumps(
        {
            "score": 99,
            "level": 3,
            "evidences": [{"code": "isolation", "text": "不要告诉任何人", "confidence": 0.9}],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *_a, **_k: FakeResponse(_completion(raw=raw)))
    evidences = llm.extract_evidence("不要告诉任何人")
    assert [e.code for e in evidences] == ["llm_isolation"]
    dumped = json.dumps([e.model_dump() for e in evidences], ensure_ascii=False)
    assert "score" not in dumped and "level" not in dumped


def test_extract_evidence_drops_unknown_codes(configured: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm.urllib.request,
        "urlopen",
        lambda *_a, **_k: FakeResponse(
            _completion(
                [
                    {"code": "made_up_signal", "text": "自造编号", "confidence": 0.9},
                    {"code": "prize", "text": "恭喜中奖", "confidence": 0.5},
                ]
            )
        ),
    )
    evidences = llm.extract_evidence("恭喜中奖")
    assert [e.code for e in evidences] == ["llm_prize"]


def test_extract_evidence_returns_empty_on_bad_json(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *_a, **_k: FakeResponse(_completion(raw="不是 JSON")))
    assert llm.extract_evidence("随便一段话") == []


def test_extract_evidence_returns_empty_on_network_error(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", fail)
    assert llm.extract_evidence("随便一段话") == []
