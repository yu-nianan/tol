from __future__ import annotations

import json

from app.pipelines.notify.report_builder import build_report, render_report_html

PHONE = "13812345678"


def _report(make_decision, **kwargs):
    options = {
        "session_id": "s1",
        "turns": 3,
        "decision": make_decision(),
        "notifications": [{"event": "notify", "level": 3, "status": "skipped"}],
        "text_count": 3,
    }
    options.update(kwargs)
    return build_report(**options)


def test_build_report_masks_every_section(make_decision) -> None:
    report = _report(make_decision)

    blob = json.dumps(report.model_dump(), ensure_ascii=False)

    assert PHONE not in blob
    assert "138****5678" in blob
    assert report.is_complete()
    assert report.risk_summary["level"] == 3
    assert report.evidence_chain


def test_render_report_html_has_five_sections_and_is_self_contained(make_decision) -> None:
    html = render_report_html(_report(make_decision))

    assert html.startswith("<!DOCTYPE html>")
    assert 'lang="zh-CN"' in html
    assert "<style>" in html
    assert "@media print" in html
    assert "<script" not in html
    assert "http://" not in html and "https://" not in html
    for title in ("一、风险说明", "二、证据链", "三、剧本匹配", "四、防范建议", "五、通知记录"):
        assert title in html
    assert PHONE not in html
    assert "138****5678" in html


def test_render_report_html_escapes_markup(make_decision) -> None:
    decision = make_decision()
    decision.evidence[0].text = "<script>alert(1)</script>"

    html = render_report_html(_report(make_decision, decision=decision))

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_render_report_html_handles_empty_script_and_notifications(make_decision) -> None:
    decision = make_decision()
    decision.script = None
    decision.evidence = []
    report = _report(make_decision, decision=decision, notifications=[])

    html = render_report_html(report)

    assert "未命中剧本" in html
    assert "没有触发通知" in html
    assert report.script_match == {}
