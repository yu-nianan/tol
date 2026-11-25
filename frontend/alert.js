"use strict";

/* ---------- 告警：由检测结果生成，不再是写死的三条 ---------- */
function resetAlerts(){
  state.alerts = [];
  state.alertLevel = 0;
  state.alertSeq = 0;
  state.currentAlert = null;
  state.acked = false;
  renderAlertPage();
}

function recordAlert(r){
  if (r.level < 1) return;                 // L0 只记录，不建告警
  if (r.level <= state.alertLevel) return; // 同一会话只在跨档时新建一条
  state.alertLevel = r.level;
  state.alertSeq += 1;
  var a = {
    id: "AL-" + state.alertSeq,
    level: r.level,
    score: r.score,
    stage: r.stage,
    script: r.scriptName,
    turns: r.turns,
    at: nowStr().slice(11),
    evidence: r.ev.slice(),
    pushed: r.level >= 3 ? state.webhook : false,
    read: false,
    acked: false
  };
  state.alerts.unshift(a);
  state.currentAlert = a.id;
  renderAlertPage();
}

function currentAlert(){
  if (!state.currentAlert) return null;
  for (var i = 0; i < state.alerts.length; i++) {
    if (state.alerts[i].id === state.currentAlert) return state.alerts[i];
  }
  return null;
}

function renderAlertPage(){
  renderAlertList();
  renderAlertDetail();
  renderGuardian();
}

function renderAlertList(){
  var box = $("#alertList");
  if (!box) return;
  if (!state.alerts.length) {
    box.innerHTML = '<div class="muted" style="line-height:1.9">还没有告警。<br>' +
      "回「检测」页把对话粘进去，等级到 L1 就会在这里生成一条。</div>";
    return;
  }
  box.innerHTML = state.alerts.map(function(a){
    var tag = a.level >= 3 ? "l3" : (a.level >= 2 ? "l2" : "wait");
    var st = a.feedback === "scam" ? "已确认诈骗"
      : a.feedback === "fp" ? "已标记误报"
      : a.acked ? "已介入" : (a.read ? "已读 · 待处置" : (a.pushed ? "已推送 · 待查看" : "未推送"));
    return '<div class="alertitem' + (a.id === state.currentAlert ? " on" : "") + '" data-alert="' + a.id + '">' +
      '<span class="tag ' + tag + '">L' + a.level + "</span>" +
      '<div><div class="t">' + esc(a.script === "—" ? "未命中剧本" : a.script) +
      " · 命中 " + a.evidence.length + " 条证据</div>" +
      '<div class="s">' + esc(a.at) + " · " + a.score.toFixed(1) + " 分 · " + esc(st) + "</div></div></div>";
  }).join("");
  $$("#alertList .alertitem").forEach(function(el){
    el.addEventListener("click", function(){
      state.currentAlert = el.getAttribute("data-alert");
      renderAlertPage();
    });
  });
}

  function renderAlertDetail(){
  var box = $("#alertDetail");
  if (!box) return;
  var a = currentAlert();
  if (!a) { box.innerHTML = ""; return; }
  var evs = a.evidence.filter(function(e){ return e.speaker === "them"; }).slice(0, 5);
  box.innerHTML = '<div class="hr"></div>' +
    '<div class="muted" style="margin-bottom:8px">这条告警凭什么这么判（阶段：' +
    esc(a.stage) + " · 第 " + a.turns + " 轮）</div>" +
    (evs.length ? evs.map(function(e){
      return '<div class="ev"><div class="lab">' + esc(e.lab) +
        '<span class="spk them">对方</span></div>' +
        '<div class="quo">「' + esc(e.quo) + '」</div>' +
        '<div class="cod">' + esc(e.cod) + "</div></div>";
    }).join("") : '<div class="muted">这条告警没有对方话术证据。</div>') +
    feedbackRow(a);
  bindFeedback();
}

/* ---------- 用户判定：确认诈骗 / 误报（FR-4 在用户侧的入口） ---------- */
function feedbackRow(a){
  if (a.feedback === "scam") {
    return '<div class="muted" style="margin-top:10px;color:var(--ok)">已确认是诈骗 · 已提交人工复核（待审 +1）</div>';
  }
  if (a.feedback === "fp") {
    return '<div class="muted" style="margin-top:10px;color:var(--l2)">已标记为误报 · 不进案例库，会用于降低误报</div>';
  }
  return '<div class="row" style="margin-top:12px">' +
    '<button class="btn" id="fbScam" type="button">确认是诈骗</button>' +
    '<button class="btn" id="fbFp" type="button">是误报</button>' +
    '<span class="muted">你的判断会进入复核队列，用于更新识别能力</span>' +
    '</div>';
}

function bindFeedback(){
  var scam = $("#fbScam"), fp = $("#fbFp");
  if (scam) scam.addEventListener("click", function(){ giveFeedback("scam"); });
  if (fp) fp.addEventListener("click", function(){ giveFeedback("fp"); });
}

function giveFeedback(kind){
  var a = currentAlert();
  if (!a) return;
  if (a.feedback) { toast("这条已经标记过了"); return; }
  a.feedback = kind;
  if (kind === "scam") {
    state.kb.pending += 1;
    updateKb();
    toast("已提交人工复核（待审 +1）· 审核通过后用于更新识别能力");
  } else {
    toast("已标记误报 · 不进案例库，会用于降低误报");
  }
  renderAlertPage();
}

function updateKb(){
  var v = $("#kbVer"), pd = $("#kbPending");
  if (v) v.textContent = state.kb.version;
  if (pd) pd.textContent = state.kb.pending;
}

function guardianNote(a){
  if (a.level < 3) return "L" + a.level + " 不触发监护人推送（只有 L3 才推）。下面是配置好之后监护人<b>会</b>看到的内容。";
  if (!state.webhook) return "当前未配置 GUARDIAN_WEBHOOK，这条通知<b>没有发出去</b>（降级）。下面是监护人<b>会</b>看到的内容。";
  return "";
}

function guardianBubbles(a){
  var tops = a.evidence.filter(function(e){ return e.speaker === "them"; })
    .slice(0, 3).map(function(e){ return e.lab; }).join("・");
  return '<div class="time">今天 ' + esc(a.at.slice(0, 5)) + "</div>" +
    '<div class="bubble sys">【' + (a.level >= 3 ? "紧急" : "警告") + "】您的家人（" +
      esc(state.guardian.name) + "，" + esc(state.guardian.rel) + "）可能正在遭遇诈骗，风险等级 <b>L" +
      a.level + "</b>。</div>" +
    (tops ? '<div class="bubble warn">命中证据：' + esc(tops) + "。</div>" : "") +
    '<div class="bubble">系统已向当事人发出风险提醒，并建议立即挂断。请立即联系本人确认。</div>' +
    '<div class="bubble sys">处置建议：先打电话给本人，确认是否已转账；已转账请立即拨 96110 并保留凭证。</div>' +
    (a.acked ? '<div class="time">刚刚</div><div class="bubble me">我已介入，正在联系家人</div>' : "");
}

function renderGuardian(){
  var chat = $("#chat");
  if (!chat) return;
  var a = currentAlert();

  if (!a) {
    chat.innerHTML = '<div class="time">—</div><div class="bubble">还没有告警，监护人不会收到任何消息。</div>';
  } else {
    var note = guardianNote(a);
    var body = guardianBubbles(a);
    chat.innerHTML = note
      ? '<div class="bubble" style="border-style:dashed;color:var(--ink3)">' + note + "</div>" +
        '<div style="opacity:.55">' + body + "</div>"
      : body;
    chat.scrollTop = chat.scrollHeight;
  }

  var st = $("#ackState");
  if (st) {
    st.textContent = !a ? "—"
      : a.acked ? "监护人已介入 · 回写完成（FR-3.3）"
      : a.read ? "监护人已读 · 等待处置"
      : a.pushed ? "已推送，等待监护人查看"
      : (a.level < 3 ? "未达 L3，不推送监护人" : "未配置通道 → 未推送（降级）");
  }
  var p = $("#st-push"), rd = $("#st-read"), ak = $("#st-ack");
  if (p) p.classList.toggle("on", !!(a && a.pushed));
  if (rd) rd.classList.toggle("on", !!(a && a.read));
  if (ak) ak.classList.toggle("on", !!(a && a.acked));

  var btn = $("#ackBtn"), call = $("#callBtn"), police = $("#callPolice");
  var live = !!(a && a.pushed && !a.acked);
  if (btn) { btn.disabled = !live; btn.textContent = a && a.acked ? "已介入 ✓" : "我已介入"; }
  if (call) call.disabled = !live;
  if (police) police.disabled = !live;
}
