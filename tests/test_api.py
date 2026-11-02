from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SCAM = (
    "您好，我是市局经侦支队的，你的银行卡涉嫌洗钱，现在需要你配合资金审查，"
    "不要告诉任何人，把存款转到我们的安全账户，半小时内完成。"
)
NORMAL = "明天下午三点在图书馆三楼讨论，记得带笔记本和充电器。"


def test_health_reports_kb_loaded() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["kb_scripts"] >= 10
    assert body["kb_cases"] >= 20


def test_detect_scam_text_is_high_risk() -> None:
    resp = client.post("/api/v1/detect/text", json={"text": SCAM, "session_id": "t1", "role": "elder"})
    assert resp.status_code == 200
    decision = resp.json()["decision"]
    assert decision["score"] >= 60
    assert decision["level"] >= 2
    assert decision["script"]["script_id"] == "S01"


def test_detect_normal_text_is_not_flagged() -> None:
    resp = client.post("/api/v1/detect/text", json={"text": NORMAL, "session_id": "t2", "role": "normal"})
    assert resp.status_code == 200
    assert resp.json()["decision"]["level"] <= 1


def test_blank_text_rejected() -> None:
    resp = client.post("/api/v1/detect/text", json={"text": "    ", "session_id": "t3"})
    assert resp.status_code == 422


def test_unknown_role_rejected() -> None:
    resp = client.post("/api/v1/detect/text", json={"text": NORMAL, "role": "hacker"})
    assert resp.status_code == 422


def test_report_after_detect() -> None:
    resp = client.post("/api/v1/detect/text", json={"text": SCAM, "session_id": "t4", "role": "normal"})
    alert_id = resp.json()["alert"]["id"]

    report = client.get("/api/v1/report/t4")
    assert report.status_code == 200
    payload = report.json()["report"]
    assert payload["risk_summary"]["score"] >= 60
    assert payload["evidence_chain"]
    assert payload["advice"]

    acked = client.post(f"/api/v1/alerts/{alert_id}/ack", json={"action": "ack", "note": "已电话联系"})
    assert acked.status_code == 200
    assert acked.json()["status"] == "acked"


def test_report_for_unknown_session_404() -> None:
    assert client.get("/api/v1/report/nope").status_code == 404


def test_kb_scripts_and_case_ingest() -> None:
    scripts = client.get("/api/v1/kb/scripts")
    assert scripts.status_code == 200
    assert scripts.json()["count"] >= 10

    created = client.post(
        "/api/v1/kb/cases",
        json={
            "id": "C900",
            "script_id": "S01",
            "title": "测试案例：安全账户",
            "text": "我是公安，请把钱转到安全账户接受资金审查",
            "level": "L3",
        },
    )
    assert created.status_code == 200
    assert created.json()["added"] is True

    duplicated = client.post(
        "/api/v1/kb/cases",
        json={"id": "C900", "text": "重复案例文本内容", "script_id": "S01"},
    )
    assert duplicated.json()["added"] is False
