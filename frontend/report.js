"use strict";

/* ---------- 报告：由当前对话生成，不写死任何数字 ----------
 * 会话号、逐轮曲线、时延、通知记录全部来自真实数据（adapter 的结果 / 后端报告）。
 */
function sessId(){ return state.sid || "—"; }

function nowStr(){
  var d = new Date();
  function p(n){ return (n < 10 ? "0" : "") + n; }
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " +
         p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}

/* 逐轮曲线：用每轮真实判别结果（app.js 在 predict 成功时写入 state.history） */
function scoreHistory(conv, role){
  var hist = (state.history || []).slice().sort(function(a, b){ return a.turn - b.turn; });
  if (hist.length) return hist;
  var r = analyze(conv, role);
  return [{ turn: r.turns || conv.length, score: r.score, level: r.level }];
}

function dimSvg(dims){
  var rows = dims.map(function(x){
    var pct = Math.round(x[2] * 100);
    return { name: x[0], w: Math.round(pct * 2.48), v: (x[1] * x[2]).toFixed(1) };
  });
  var out = ['<svg viewBox="0 0 320 156" width="100%" height="156" role="img" aria-label="维度贡献条形图">'];
  out.push('<g font-size="10" fill="#5B6675">');
  rows.forEach(function(r, i){ out.push('<text x="0" y="' + (22 + i * 24) + '">' + esc(r.name) + '</text>'); });
  out.push('</g><g fill="#EDF1F7">');
  rows.forEach(function(r, i){ out.push('<rect x="52" y="' + (12 + i * 24) + '" width="248" height="10" rx="5"/>'); });
  out.push('</g><g fill="#1E6FD9">');
  rows.forEach(function(r, i){ out.push('<rect x="52" y="' + (12 + i * 24) + '" width="' + Math.max(r.w, 1) + '" height="10" rx="5"/>'); });
  out.push('</g><g font-size="9" fill="#8A94A6" font-family="Consolas, monospace">');
  rows.forEach(function(r, i){
    out.push('<text x="' + Math.min(52 + r.w + 4, 300) + '" y="' + (21 + i * 24) + '">' + r.v + '</text>');
  });
  out.push('</g></svg>');
  return out.join("");
}

function lineSvg(hist){
  if (!hist.length) return "";
  var n = hist.length, x0 = 40, x1 = 300;
  var step = n > 1 ? (x1 - x0) / (n - 1) : 0;
  var pts = [], dots = [], labs = [];
  hist.forEach(function(h, i){
    var x = n > 1 ? x0 + step * i : (x0 + x1) / 2;
    var y = 106 - (h.score / 100) * 90;
    pts.push(x.toFixed(0) + "," + y.toFixed(0));
    dots.push('<circle cx="' + x.toFixed(0) + '" cy="' + y.toFixed(0) + '" r="3.5"/>');
    labs.push('<text x="' + Math.max(x - 14, 0).toFixed(0) + '" y="126">第' + h.turn + '轮</text>');
  });
  var last = hist[hist.length - 1].level;
  var color = last >= 3 ? "#C81E1E" : (last >= 2 ? "#D97706" : "#1E6FD9");
  return '<svg viewBox="0 0 320 132" width="100%" height="132" role="img" aria-label="逐轮评分曲线">' +
    '<g stroke="#EDF1F7"><line x1="34" y1="16" x2="308" y2="16"/><line x1="34" y1="46" x2="308" y2="46"/>' +
    '<line x1="34" y1="76" x2="308" y2="76"/><line x1="34" y1="106" x2="308" y2="106"/></g>' +
    '<g font-size="9" fill="#8A94A6"><text x="4" y="19">100</text><text x="10" y="49">66</text>' +
    '<text x="10" y="79">33</text><text x="14" y="109">0</text></g>' +
    (pts.length > 1 ? '<polyline fill="none" stroke="' + color + '" stroke-width="2.5" points="' + pts.join(" ") + '"/>' : "") +
    '<g fill="' + color + '">' + dots.join("") + '</g>' +
    '<g font-size="9" fill="#5B6675">' + labs.join("") + '</g></svg>';
}

function renderReport(){
  var host = $("#reportPaper");
  if (!host) return;

  if (!state.conv.length) {
    host.innerHTML = '<div class="reply"><div class="sec"><h3>还没有可生成报告的内容</h3>' +
      '<p class="muted">先回「检测」页粘贴至少一条对话；聊完之后点结果区下方的「结束对话 · 生成报告」。</p></div></div>';
    return;
  }

  var conv = state.conv;
  var role = $("#role").value;
  var r = analyze(conv, role);
  var hist = scoreHistory(conv, role);
  var lv = r.level;
  var lvColor = lv >= 3 ? "var(--l3)" : lv >= 2 ? "var(--l2)" : lv >= 1 ? "var(--l1)" : "var(--l0)";
  var g = state.guardian;
  var at = state.reportAt || nowStr();
  var themEv = r.ev.filter(function(e){ return e.speaker === "them"; });
  var meEv = r.ev.filter(function(e){ return e.speaker === "me"; });
  var p = [];

  p.push('<div class="reply">');
  p.push('<div class="rep-head"><div style="flex:1"><h1>安全监测报告</h1>' +
    '<div class="muted" style="margin-top:6px">会话 ' + esc(sessId()) + ' · 生成于 ' + esc(at) +
    ' · 角色 ' + esc(ROLE_NAME[role] || role) + '</div></div>' +
    '<div class="r">等级：<b style="color:' + lvColor + '">' + levelText(lv) + '</b><br>' +
    '评分：' + r.score.toFixed(1) + ' / 100<br>轮次：' + r.turns + '</div></div>');

  p.push('<div class="sec"><h3>一、风险概览</h3><table>');
  p.push('<tr><th style="width:120px">最高等级</th><td>' + levelText(lv) + '（当前阶段：' + esc(r.stage) + '）</td></tr>');
  p.push('<tr><th>命中剧本</th><td>' + (r.scriptName === "—" ? "未命中具体剧本，按通用话术规则定级" : esc(r.scriptName)) + '</td></tr>');
  p.push('<tr><th>对话构成</th><td>' + r.turns + ' 轮（对方 ' + r.themMsgs + ' 条 / 我 ' + r.meMsgs + ' 条）</td></tr>');
  p.push('<tr><th>证据条数</th><td>' + r.ev.length + ' 条（对方话术 ' + themEv.length + ' / 我的状态 ' + meEv.length + '）</td></tr>');
  if (r.flags.length) {
    p.push('<tr><th>受害状态</th><td>' + r.flags.map(function(f){
      var hit = null;
      ME_SIGNALS.forEach(function(x){ if (x.flag === f) hit = x; });
      return esc(hit ? hit.lab : f);
    }).join("；") + '</td></tr>');
  }
  p.push('<tr><th>处置状态</th><td>' +
    (state.acked ? "监护人已介入（确认回写）" : (lv >= 3 ? "已通知监护人 · 待确认" : "仅记录，未通知")) +
    '</td></tr>');
  p.push('</table></div>');

  p.push('<div class="sec"><h3>二、证据链</h3>');
  if (r.ev.length) {
    p.push('<table><thead><tr><th style="width:50px">轮次</th><th style="width:50px">来源</th><th>证据</th><th style="width:54px">权重</th></tr></thead><tbody>');
    r.ev.forEach(function(e){
      var m = e.cod.match(/第(\d+)轮/);
      p.push('<tr><td class="mono">' + (m ? m[1] : "—") + '</td>' +
        '<td>' + (e.speaker === "them" ? "对方" : "我") + '</td>' +
        '<td>' + esc(e.lab) + '：' + esc(e.quo) + '</td>' +
        '<td class="mono">' + (e.w ? e.w.toFixed(2) : "—") + '</td></tr>');
    });
    p.push('</tbody></table>');
  } else {
    p.push('<p class="muted">这段对话没有命中任何剧本信号。</p>');
  }
  p.push('</div>');

  p.push('<div class="sec"><h3>三、量化分析</h3><div class="chart">');
  p.push('<div class="box"><div class="ttl">维度贡献</div>' + dimSvg(r.dims) + '</div>');
  p.push('<div class="box"><div class="ttl">逐轮评分（同一段对话，等级是长出来的）</div>' + lineSvg(hist) + '</div>');
  p.push('</div></div>');

  p.push('<div class="sec"><h3>四、防御建议</h3><ol class="advice">');
  adviceList(r).forEach(function(a){ p.push('<li>' + esc(a) + '</li>'); });
  p.push('</ol></div>');

  p.push('<div class="sec"><h3>五、通知记录</h3><table>' +
    '<thead><tr><th style="width:110px">时间</th><th>对象</th><th>渠道</th><th style="width:110px">状态</th></tr></thead><tbody>');
  var srv = state.serverReport && state.serverReport.notifications;
  if (srv && srv.length) {
    srv.forEach(function(n, i){
      var who = n.target || n.role || n.name || n.channel || ("通知 " + (i + 1));
      var how = n.channel || n.via || "—";
      var state2 = n.status || (n.sent === false ? "未推送（降级）" : n.sent === true ? "已送达" : "—");
      var when = n.at || n.time || n.created_at || at;
      p.push('<tr><td class="mono">' + esc(String(when)) + '</td><td>' + esc(String(who)) + '</td><td>' +
        esc(String(how)) + '</td><td>' + esc(String(state2)) + '</td></tr>');
    });
  } else if (lv >= 3) {
    var pushState = state.webhook ? "已推送" : '<span style="color:var(--l2);font-weight:700">未推送（降级）</span>';
    p.push('<tr><td class="mono">' + esc(at) + '</td><td>监护人 ' + esc(g.name) + '</td><td>站内通知 + 企业微信</td><td>' + pushState + '</td></tr>');
    if (g.second) {
      p.push('<tr><td class="mono">' + esc(at) + '</td><td>第二联系人 ' + esc(g.second) + '</td><td>短信</td><td>' + pushState + '</td></tr>');
    }
    p.push('<tr><td class="mono">' + (state.acked ? esc(at) : "—") + '</td><td>监护人 ' + esc(g.name) +
      '</td><td>回写</td><td>' + (state.acked ? "已介入" : "待确认") + '</td></tr>');
  } else {
    p.push('<tr><td class="mono">—</td><td>—</td><td>—</td><td>未触发（仅 L3 推送监护人）</td></tr>');
  }
  p.push('</tbody></table>');
  if (!(srv && srv.length) && !state.webhook) {
    p.push('<p class="muted" style="margin-top:8px">当前环境未配置 GUARDIAN_WEBHOOK，因此如实显示「未推送（降级）」，不写「已送达」。</p>');
  }
  p.push('</div>');

  p.push('<div class="foot">本报告由原型系统自动生成，仅用于演练与教学，不构成法律意见。<br>' +
    '数据来源：文本对话 ' + r.turns + ' 轮 / ' + r.ev.length + ' 条证据；评分时延 ' + (r.latency || 0) +
    ' ms（规则链路' + (state.engine && state.engine.llm_enabled ? ' + 外部模型' : '，未启用外部模型') + '）。</div>');
  p.push('</div>');

  host.innerHTML = p.join("");
}
