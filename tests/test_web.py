"""演示页与 /static 资产的路由测试。

背景：原来 `frontend/index.html` 把 app.js/style.css 内联成 1616 行，
改一次要重新内联；ADR-0006 改成 /static 投递。这些用例守住三件事：
   1. `/` 返回演示页，并且页面引用的是 /static/ 资产（不再内联）；
   2. 白名单后缀的资产能取到，类型正确；
   3. 路径穿越与非白名单后缀一律 404（不许把仓库里的 .py/.html 漏出去）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_index_serves_demo_page_with_static_assets() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert "/static/app.js" in html
    assert "/static/style.css" in html
    # 反例：内联资产会把 20KB 以上的 JS 直接塞进 HTML，这里卡住回归
    assert len(html) < 20_000


def test_static_asset_is_served() -> None:
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert "getElementById" in resp.text

    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]


def test_static_rejects_traversal() -> None:
    for path in ("/static/../app/main.py", "/static/..%2Fapp%2Fmain.py", "/static/%2e%2e/app/core/config.py"):
        resp = client.get(path)
        assert resp.status_code == 404, path


def test_static_rejects_non_whitelisted_suffix() -> None:
    for path in ("/static/index.html", "/static/app.exe", "/static/presets.json", "/static/nope.js"):
        resp = client.get(path)
        assert resp.status_code == 404, path


def test_index_falls_back_when_frontend_missing(monkeypatch) -> None:
    from app.api import web

    monkeypatch.setattr(web, "FRONTEND", web.FRONTEND / "definitely-missing")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "演示版" in resp.text
    # 兜底页不带外链资产，前端缺失时也不该 500
    assert "/static/app.js" not in resp.text
