from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.pipelines.notify import guardian
from app.schemas import AlertStatus, Level

PHONE = "13812345678"


def _settings_without_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guardian, "settings", SimpleNamespace(guardian_webhook=""))


def test_level_channel_mapping_without_webhook(monkeypatch, make_alert, make_decision) -> None:
    _settings_without_webhook(monkeypatch)
    monkeypatch.setattr(
        guardian.httpx, "post", lambda *args, **kwargs: pytest.fail("未配 webhook 时不应发请求")
    )

    expected = {
        Level.L0: ([], "skipped"),
        Level.L1: (["in_app"], "recorded"),
        Level.L2: (["in_app", "voice"], "skipped"),
        Level.L3: (["in_app", "voice", "guardian"], "skipped"),
    }
    for level, (channels, status) in expected.items():
        note = guardian.notify_guardian(make_alert(level=level), make_decision(level=level))
        assert note["level"] == int(level)
        assert [item["channel"] for item in note["channels"]] == channels
        assert note["status"] == status
        assert note["sent"] is False

    l3 = guardian.notify_guardian(make_alert(level=Level.L3), make_decision())
    guardian_channel = l3["channels"][-1]
    assert guardian_channel["channel"] == "guardian"
    assert guardian_channel["status"] == "skipped"
    assert "payload_preview" in guardian_channel


def test_l3_webhook_sent_with_masked_payload(monkeypatch, make_alert, make_decision) -> None:
    calls: list[dict[str, object]] = []

    def fake_post(url: str, json: object = None, timeout: float = 0) -> SimpleNamespace:
        calls.append({"url": url, "json": json, "timeout": timeout})
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(
        guardian, "settings", SimpleNamespace(guardian_webhook="https://example.invalid/hook")
    )
    monkeypatch.setattr(guardian.httpx, "post", fake_post)

    note = guardian.notify_guardian(make_alert(level=Level.L3), make_decision(level=Level.L3))

    assert note["status"] == "sent"
    assert note["sent"] is True
    assert len(calls) == 1
    assert calls[0]["url"] == "https://example.invalid/hook"
    assert calls[0]["timeout"] == 3.0
    payload = calls[0]["json"]
    assert isinstance(payload, dict)
    assert payload["level"] == 3
    assert payload["evidence_count"] == 1
    assert "L3" in str(payload["summary"])
    blob = json.dumps(payload, ensure_ascii=False)
    assert PHONE not in blob
    assert "138****5678" in blob


def test_webhook_http_error_is_not_reported_as_sent(monkeypatch, make_alert, make_decision) -> None:
    monkeypatch.setattr(
        guardian, "settings", SimpleNamespace(guardian_webhook="https://example.invalid/hook")
    )
    monkeypatch.setattr(
        guardian.httpx, "post", lambda *args, **kwargs: SimpleNamespace(status_code=500)
    )

    note = guardian.notify_guardian(make_alert(level=Level.L3), make_decision())
    channel = note["channels"][-1]

    assert note["status"] == "skipped"
    assert note["sent"] is False
    assert channel["status"] == "http_error"
    assert channel["http_status"] == 500


def test_webhook_network_error_is_masked(monkeypatch, make_alert, make_decision) -> None:
    def boom(*args, **kwargs):
        raise httpx.ConnectError("无法连接 13812345678")

    monkeypatch.setattr(
        guardian, "settings", SimpleNamespace(guardian_webhook="https://example.invalid/hook")
    )
    monkeypatch.setattr(guardian.httpx, "post", boom)

    note = guardian.notify_guardian(make_alert(level=Level.L3), make_decision())
    channel = note["channels"][-1]

    assert note["status"] == "skipped"
    assert note["sent"] is False
    assert channel["status"] == "error"
    assert "138****5678" in channel["detail"]
    assert PHONE not in channel["detail"]


def test_record_ack_in_session_masks_note(make_alert) -> None:
    state = SimpleNamespace(notifications=[])
    alert = make_alert(level=Level.L2)
    alert.status = AlertStatus.ACKED

    record = guardian.record_ack_in_session(state, alert, "ack", f"已联系家属 {PHONE}")

    assert state.notifications == [record]
    assert record["event"] == "ack"
    assert record["action"] == "ack"
    assert record["status"] == "acked"
    assert record["note"] == "已联系家属 138****5678"


def test_record_ack_requires_notifications_list(make_alert) -> None:
    with pytest.raises(TypeError):
        guardian.record_ack_in_session(SimpleNamespace(), make_alert(), "ack")


def test_notify_logs_do_not_leak_full_phone(monkeypatch, caplog, make_alert, make_decision) -> None:
    caplog.set_level(logging.INFO)
    _settings_without_webhook(monkeypatch)

    guardian.notify_guardian(make_alert(level=Level.L3), make_decision())

    assert PHONE not in caplog.text
