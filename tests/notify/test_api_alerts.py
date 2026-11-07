from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SCAM = (
    "您好，我是市局经侦支队的，你的银行卡涉嫌洗钱，现在需要你配合资金审查，"
    "不要告诉任何人，把存款转到我们的安全账户，半小时内完成。"
)
PHONE = "13812345678"


def test_ack_endpoint_writes_notification_into_report() -> None:
    detected = client.post(
        "/api/v1/detect/text", json={"text": SCAM, "session_id": "ack-b-1", "role": "elder"}
    )
    assert detected.status_code == 200
    alert = detected.json()["alert"]
    assert alert is not None

    acked = client.post(
        f"/api/v1/alerts/{alert['id']}/ack",
        json={"action": "ack", "note": f"已联系家属 {PHONE}"},
    )
    assert acked.status_code == 200
    assert acked.json()["status"] == "acked"

    report = client.get("/api/v1/report/ack-b-1").json()["report"]
    acks = [item for item in report["notifications"] if item.get("event") == "ack"]
    assert acks
    assert acks[-1]["alert_id"] == alert["id"]
    assert acks[-1]["note"] == "已联系家属 138****5678"
    assert PHONE not in json.dumps(report, ensure_ascii=False)


def test_ack_unknown_alert_still_404() -> None:
    resp = client.post("/api/v1/alerts/A-does-not-exist/ack", json={"action": "ack"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "alert_not_found"
