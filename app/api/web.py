"""自带的演示页：不需要前端构建、不依赖任何 CDN，打开就能用。

演示时的顺序建议：先点"正常消息"证明不误报，再点"冒充公检法"看拦截，
最后点"生成报告"展示证据链 —— 30 秒讲完。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["web"])

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>反诈智能助手 · 演示</title>
<style>
  :root { --navy:#1f3864; --blue:#2e5c8a; --l0:#2e7d32; --l1:#f9a825; --l2:#ef6c00; --l3:#c62828; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:"Microsoft YaHei",system-ui,sans-serif; background:#f4f6f9; color:#222; }
  header { background:var(--navy); color:#fff; padding:16px 24px; }
  header h1 { margin:0; font-size:18px; font-weight:600; }
  header p { margin:4px 0 0; font-size:12px; opacity:.75; }
  main { max-width:760px; margin:20px auto; padding:0 16px 40px; }
  .card { background:#fff; border-radius:10px; padding:16px; box-shadow:0 1px 3px rgba(0,0,0,.08); margin-bottom:16px; }
  textarea { width:100%; min-height:110px; padding:10px; border:1px solid #d5dbe5; border-radius:8px; font-size:14px; resize:vertical; }
  select, button { font-size:14px; }
  select { padding:6px 8px; border-radius:6px; border:1px solid #d5dbe5; }
  button { cursor:pointer; border:none; border-radius:6px; padding:9px 16px; font-weight:600; }
  .primary { background:var(--blue); color:#fff; }
  .ghost { background:#eef2f8; color:var(--navy); }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:12px; }
  .badge { display:inline-block; padding:4px 10px; border-radius:999px; color:#fff; font-size:13px; font-weight:700; }
  .score { font-size:32px; font-weight:800; color:var(--navy); }
  ul { margin:8px 0 0; padding-left:18px; }
  li { margin:4px 0; font-size:13.5px; line-height:1.5; }
  .muted { color:#6b7280; font-size:12.5px; }
  .ev { border-left:3px solid var(--blue); padding:6px 10px; margin:8px 0; background:#f8fafc; font-size:13px; }
  pre { background:#0f172a; color:#d7e3f4; padding:12px; border-radius:8px; font-size:12px; overflow:auto; max-height:260px; }
</style>
</head>
<body>
<header>
  <h1>多模态反诈智能助手 · 演示版</h1>
  <p>粘贴一条可疑消息或录音转写文本，系统给出风险分、命中剧本与证据链</p>
</header>
<main>
  <div class="card">
    <textarea id="text" placeholder="把可疑短信 / 聊天记录 / 录音转写粘贴到这里"></textarea>
    <div class="row">
      <select id="role">
        <option value="normal">普通用户</option>
        <option value="elder">老年人</option>
        <option value="child">儿童</option>
        <option value="student">学生</option>
        <option value="finance">财务人员</option>
      </select>
      <button class="primary" onclick="detect()">检测</button>
      <button class="ghost" onclick="preset('scam')">冒充公检法</button>
      <button class="ghost" onclick="preset('service')">客服退款</button>
      <button class="ghost" onclick="preset('normal')">正常消息</button>
      <button class="ghost" onclick="report()">生成报告</button>
    </div>
    <p class="muted" id="meta"></p>
  </div>

  <div class="card" id="result" style="display:none">
    <div style="display:flex;align-items:center;gap:12px">
      <span class="score" id="score">0</span>
      <span class="badge" id="level">L0</span>
      <span id="script" class="muted"></span>
    </div>
    <ul id="reasons"></ul>
    <div id="evidence"></div>
  </div>

  <div class="card" id="reportBox" style="display:none">
    <strong>会话报告（截取）</strong>
    <pre id="reportJson"></pre>
  </div>
</main>
<script>
const PRESETS = {
  scam: "您好，我是市局经侦支队的，你的银行卡涉嫌洗钱，现在需要你配合资金审查，不要告诉任何人，把存款转到我们的安全账户，半小时内完成，否则后果自负。",
  service: "亲，您的订单异常，我们可以双倍退款，请打开屏幕共享，我远程协助您操作银行APP，并把验证码发给我。",
  normal: "明天下午三点在图书馆三楼讨论，记得带笔记本和充电器。"
};
const sessionId = "web-" + Math.random().toString(36).slice(2, 8);
const LEVELS = ["L0 仅记录", "L1 提醒", "L2 警告", "L3 紧急"];
const COLORS = ["var(--l0)", "var(--l1)", "var(--l2)", "var(--l3)"];

function preset(kind) { document.getElementById("text").value = PRESETS[kind] || ""; }

async function detect() {
  const text = document.getElementById("text").value.trim();
  if (!text) { alert("先填点内容"); return; }
  const body = { text, session_id: sessionId, role: document.getElementById("role").value };
  const resp = await fetch("/api/v1/detect/text", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  });
  const data = await resp.json();
  if (!resp.ok) { alert("检测失败：" + JSON.stringify(data)); return; }
  const d = data.decision;
  document.getElementById("score").textContent = d.score;
  const badge = document.getElementById("level");
  badge.textContent = LEVELS[d.level];
  badge.style.background = COLORS[d.level];
  document.getElementById("script").textContent = d.script ? ("命中剧本：" + d.script.name + " · " + d.script.stage_label) : "未命中剧本";
  document.getElementById("reasons").innerHTML = d.reasons.map(r => "<li>" + r + "</li>").join("");
  document.getElementById("evidence").innerHTML = d.evidence.slice(0, 6).map(e =>
    '<div class="ev"><strong>' + e.label + '</strong>「' + (e.text || "") + '」<br><span class="muted">' + e.code + ' · 权重 ' + e.weight + '</span></div>'
  ).join("");
  document.getElementById("meta").textContent = "耗时 " + data.latency_ms + "ms · 会话 " + data.session_id + (data.alert ? " · 告警 " + data.alert.id : "");
  document.getElementById("result").style.display = "block";
}

async function report() {
  const resp = await fetch("/api/v1/report/" + sessionId);
  const data = await resp.json();
  document.getElementById("reportJson").textContent = JSON.stringify(data.report || data, null, 2);
  document.getElementById("reportBox").style.display = "block";
}
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return PAGE
