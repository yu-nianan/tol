"use strict";

/* ---------- 假数据：剧本对话（演示用，非真实接口） ---------- */
var STAGES = ["接触", "立威", "隔离", "诱导操作", "诱导转账"];
var STAGE_W = [0, 0.50, 0.75, 0.82, 0.95];

var CONVOS = {
  s01: {
    script: "S01 冒充公检法",
    turns: [
      { w:"them", t:"您好，这里是市公安局刑侦支队，我是王警官，工号 0371。" },
      { w:"me",   t:"啊？什么事？" },
      { w:"them", t:"您名下的一张银行卡涉嫌洗钱犯罪，现在需要对您的资金进行核查。" },
      { w:"them", t:"请勿将此事告知任何人，包括您的家人，配合我们办案。" },
      { w:"me",   t:"好的，我不说。" },
      { w:"them", t:"现在请把您账户里的全部资金转入我们指定的安全账户待查，核查完会原路退回。" }
    ]
  },
  s04: {
    script: "S04 冒充客服退款",
    turns: [
      { w:"them", t:"您好，我是XX商城客服，您购买的商品存在质量问题，我们给您双倍退款。" },
      { w:"me",   t:"怎么退？" },
      { w:"them", t:"请下载我们的退款专用 App，打开屏幕共享，我教您操作。" },
      { w:"me",   t:"下载好了。" },
      { w:"them", t:"稍后把收到的验证码报给我就行。" }
    ]
  },
  normal: {
    script: "—",
    turns: [
      { w:"them", t:"您的快递已放置在丰巢智能柜 A12，取件码 6688，请及时取件。" }
    ]
  }
};

/* 对方的话 → 阶段证据。阶段：0 接触 / 1 立威 / 2 隔离 / 3 诱导操作 / 4 诱导转账 */
var SIGNALS = [
  { re:/公安|刑侦|经侦|检察院|法院|警官|工号|办案/, lab:"冒用公检法身份", cat:"身份", stage:1, w:0.50, script:"S01 冒充公检法" },
  { re:/涉嫌|洗钱|犯罪|违法|立案|通缉|案件/, lab:"制造法律后果", cat:"心理", stage:1, w:0.55 },
  { re:/我是[^，。]{0,6}客服|客服中心|订单异常|质量问题|双倍退款|理赔/, lab:"冒用平台客服", cat:"身份", stage:1, w:0.50, script:"S04 冒充客服退款" },
  { re:/我是你(领导|老板|儿子|女儿)|这是我的新号|换.{0,3}号了/, lab:"冒充熟人 / 领导", cat:"身份", stage:1, w:0.52, script:"S03 冒充熟人 / 领导" },
  { re:/不要告诉|别告诉|请勿将此事告知|保密|不能跟家人说|不要挂断|别挂/, lab:"隔离施压", cat:"心理", stage:2, w:0.70 },
  { re:/(游戏|账号).{0,4}(交易|充值|代练|皮肤)|追星|打榜|应援/, lab:"游戏 / 追星交易话术", cat:"行为", stage:2, w:0.62, script:"S02 游戏 / 追星交易" },
  { re:/稳赚|内幕|带单|跟着.{0,3}老师|高回报|零风险/, lab:"投资理财话术（高回报承诺）", cat:"心理", stage:3, w:0.74, script:"S07 投资理财（杀猪盘）" },
  { re:/刷单|返利|佣金|垫付/, lab:"刷单返利话术", cat:"行为", stage:3, w:0.72, script:"S05 兼职刷单" },
  { re:/无抵押|放款|征信修复|解冻|包装流水|额度已批/, lab:"虚假贷款 / 征信话术", cat:"资金", stage:3, w:0.70, script:"S06 虚假贷款 / 征信" },
  { re:/下载|屏幕共享|远程协助|安装|App|APP/, lab:"诱导安装 / 共享屏幕", cat:"行为", stage:3, w:0.72 },
  { re:/验证码|短信码|动态码/, lab:"索要验证码", cat:"资金", stage:3, w:0.80 },
  { re:/转账|汇款|安全账户|保证金|打款|转入/, lab:"诱导转账", cat:"资金", stage:4, w:0.95 }
];

/* 我的话 → 受害状态。只影响处置分支与分值偏移，不计入"话术维度" */
var ME_SIGNALS = [
  { re:/已经转|转过去了|打了钱|汇了|转给|已经打款/, flag:"paid", lab:"你已经转账 —— 需要立即止付", sev:20 },
  { re:/验证码|念给|报给|发给|收到.{0,4}码/, flag:"code", lab:"你已经把验证码给出 —— 等同交出密码", sev:18 },
  { re:/按他说的|照做|下载(了|好)|装好|开了屏幕|屏幕共享/, flag:"obey", lab:"你已执行对方指令", sev:8 },
  { re:/我不说|不会说|不告诉家人|他说不能|不敢说/, flag:"isolated", lab:"你在复述对方的隔离指令 —— 已受影响", sev:6 },
  { re:/不确定|有点怕|是不是骗|要不要信|感觉不对/, flag:"hesitate", lab:"你正在犹豫 —— 这是最好的干预时机", sev:0 }
];

function esc(s){
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* ---------- 判别器：结果是后端给的（adapter.js），这里只做同步读取 ----------
 * 原型里 analyze() 是本地假判定；现在 state.last 由 predict() 异步填好，
 * analyze() 仍然同步返回，所以下面所有渲染函数一行都不用改。
 */
var EMPTY_DIMS = [["阶段",30,0],["实体",20,0],["话术",15,0],["跨模态",15,0],["渠道",10,0],["画像",10,0]];
var MIN_LOADING = 260;   // 与原型一致：让"判别中"有可感知的停留

function analyze(conv, role){
  return state.last || {
    score:0, level:0, stage:"无命中", stageIdx:-1, stageW:0,
    flags:[], bias:(ROLE_BIAS[role] || 0),
    ev:[], themCount:0, themMsgs:0, meMsgs:0, turns:(conv || []).length,
    scriptName:"—", key:null, dims:EMPTY_DIMS, latency:0
  };
}

var ROLE_BIAS = { normal:0, elder:8, student:5, child:10, finance:-3 };
var ROLE_NAME = { normal:"普通", elder:"老人", student:"学生", child:"儿童", finance:"财会" };
var THRESH = { l3:85, l2:60, l1:35 };

/* 闭环回执：把"进化"翻译成用户能感知的一句话（示例数据，不可当真） */
var LOOPBACK = {
  s01: { last:"「冒充公检法 · 要求转入安全账户」", num:1284 },
  s04: { last:"「冒充电商客服 · 共享屏幕盗验证码」", num:436 },
  normal: null
};
var LOOPBACK_DELAY = 260; // 模拟"预处理完成"耗时，让回执晚于结果出现

var state = {
  conv: [], score:0, level:0, scriptKey:null,
  last: null,          // 本轮判别结果（adapter 给的，形状同原型 analyze）
  history: [],         // 逐轮 (turn, score, level)，报告页的曲线用它
  sid: "",             // 真实 session_id（后端按它累计阶段）
  engine: {},          // /health 拿到的 llm/asr/ocr 开关，用于"概览"与 JSON 如实显示
  guardian: { name:"张*", rel:"女儿", second:"" },
  webhook: true,   // 演示假设：GUARDIAN_WEBHOOK 已配置；关掉后会如实显示「未推送（降级）」
  acked: false,
  reportAt: "",
  timer: null,
  qa: { asked: 0, lastTurn: 0, answers: {}, current: null },
  alerts: [], currentAlert: null, alertSeq: 0, alertLevel: 0,
  kb: { version: "—", pending: 0 }
};

var $ = function(s){ return document.querySelector(s); };
var $$ = function(s){ return Array.prototype.slice.call(document.querySelectorAll(s)); };

function levelOf(score){
  if (score >= THRESH.l3) return 3;
  if (score >= THRESH.l2) return 2;
  if (score >= THRESH.l1) return 1;
  return 0;
}
function levelText(l){ return ["L0 仅记录","L1 提醒","L2 警告","L3 紧急"][l]; }

/* ---------- 闭环回执 ---------- */
function showLoopback(key){
  var box = $("#loopback");
  if (!box) return;
  clearTimeout(box._h);
  box.classList.remove("on");
  var d = LOOPBACK[key];
  if (!d) {
    box.className = "loopback mut";
    box.innerHTML = '<div class="lb-top"><span class="lb-icon">·</span>' +
      '本次未命中已知剧本，暂不进入案例池</div>';
  } else {
    box.className = "loopback";
    box.innerHTML =
      '<div class="lb-top"><span class="lb-icon">✓</span>闭环回执' +
        '<span class="lb-tag">示例数据</span></div>' +
      '<div class="lb-body">你上次报的' + d.last + '已生效，累计帮 <b class="lb-num">' +
        d.num + '</b> 人躲过这一招。</div>' +
      '<div class="lb-sub">本次结果已加入<b>待审案例</b>：人工审核通过后才生效（约 3 天），' +
        '审核期间不会被检索引用。</div>';
  }
  box._h = setTimeout(function(){ box.classList.add("on"); }, LOOPBACK_DELAY);
}
function hideLoopback(){
  var box = $("#loopback");
  if (!box) return;
  clearTimeout(box._h);
  box.classList.remove("on");
}

function toast(msg){
  var t = $("#toast");
  t.textContent = msg; t.classList.add("on");
  clearTimeout(t._h); t._h = setTimeout(function(){ t.classList.remove("on"); }, 2200);
}

function switchView(v){
  state.view = v;
  $$("#tabs .tab").forEach(function(el){ el.classList.toggle("on", el.dataset.view === v); });
  $$(".view").forEach(function(el){ el.classList.toggle("on", el.id === "view-" + v); });
  if (v === "report") renderReport();
  if (v === "alert") renderAlertPage();
  window.scrollTo({ top:0, behavior:"instant" in window ? "instant" : "auto" });
}

/* ---------- 对话流 ---------- */
function paintConvo(){
  var box = $("#convo");
  if (!box) return;
  if (!state.conv.length) {
    box.innerHTML = '<div class="convo-empty">还没有对话<br>粘贴对方发来的第一条消息，或点下面的预设剧本</div>';
    return;
  }
  box.innerHTML = state.conv.map(function(m){
    return '<div class="msg ' + (m.w === "me" ? "me" : "them") + '">' +
      '<div class="who">' + (m.w === "me" ? "我" : "对方") + '</div>' +
      '<div class="bub">' + esc(m.t) + '</div></div>';
  }).join("") + qaHtml();
  bindQa();
  box.scrollTop = box.scrollHeight;
}

function addTurn(who){
  var ta = $("#input");
  var v = (ta.value || "").trim();
  if (!v) { toast("先粘一条内容进来"); ta.focus(); return; }
  if (v.length > 4000) { toast("单条最多 4000 字，请分段粘"); return; }
  state.conv.push({ w: who, t: v });
  ta.value = "";
  hideLoopback();
  paintConvo();
  predict();
}

/* ---------- 真判别：调后端，拿到原型形状的结果再渲染 ----------
 * 一次检测 = 一轮；后端按 session 累计阶段，所以只送"还没送过的对方消息"。
 * 失败时如实提示并保留上一轮结果，绝不本地编一个分数。
 */
var busy = false;
function predict(opts){
  if (busy) return;
  if (!state.conv.length) { state.last = null; render(); return; }
  busy = true;
  var box = $("#resultBox");
  $("#emptyState").style.display = "none";
  if (box) { box.style.display = "block"; box.classList.add("loading"); }
  var t0 = Date.now();
  var role = $("#role").value;

  A30Adapter.analyze(state.conv, role, opts || {}).then(function(r){
    var wait = Math.max(0, MIN_LOADING - (Date.now() - t0));
    setTimeout(function(){
      state.last = r;
      if (r.alertId) state.lastAlertId = r.alertId;
      var h = state.history.filter(function(x){ return x.turn < r.turns; });
      h.push({ turn: r.turns, score: r.score, level: r.level });
      state.history = h;
      if (box) box.classList.remove("loading");
      busy = false;
      render();
      if (state.view === "report") renderReport();
    }, wait);
  }).catch(function(e){
    if (box) box.classList.remove("loading");
    busy = false;
    toast("判别失败：" + e.message);
    $("#latVal").textContent = "—";
    if (!state.last) render();
  });
}

/* ---------- 渲染结果（每加一条就重判） ---------- */
function render(){
  var conv = state.conv;
  var role = $("#role").value;

  if (!conv.length) {
    state.qa.current = null;
    paintConvo();
    renderProfile();
    $("#emptyState").style.display = "";
    $("#resultBox").style.display = "none";
    $("#scoreVal").textContent = "0.0";
    $("#lvBadge").className = "badge l0";
    $("#lvBadge").textContent = levelText(0);
    $("#stageVal").textContent = "—";
    $("#turnVal").textContent = "0";
    hideLoopback();
    state.level = 0;
    return;
  }

  var prev = state.level;
  var r = analyze(conv, role);
  maybeAsk(r);
  paintConvo();
  renderProfile();
  var lv = r.level;
  recordAlert(r);
  state.score = r.score; state.level = lv; state.scriptKey = r.key;

  $("#emptyState").style.display = "none";
  $("#resultBox").style.display = "block";

  var badge = $("#lvBadge");
  badge.className = "badge l" + lv;
  badge.textContent = levelText(lv);

  $("#scoreVal").textContent = r.score.toFixed(1);
  $("#scoreVal").parentNode.querySelector("small").textContent =
    " / 100（含角色偏移 " + (r.bias > 0 ? "+" : "") + r.bias + "）";
  $("#stageVal").textContent = r.stage;
  $("#turnVal").textContent = r.turns + " 轮 · 对方 " + r.themMsgs + " / 我 " + r.meMsgs;
  $("#sessVal").textContent = state.sid || "—";
  var lat = r.latency || 0;
  $("#latVal").textContent = lat ? lat + " ms" : "—";

  $("#stageBar").innerHTML = STAGES.map(function(name, i){
    var cls = i < r.stageIdx ? "on" : (i === r.stageIdx && r.themCount ? "now" : "");
    return '<div class="st ' + cls + '"><div class="bar"></div>' + name + '</div>';
  }).join("");

  $("#victimBox").innerHTML = r.flags.length
    ? '<div class="victim"><div><b>你在对话里已经暴露了这些状态</b></div>' +
      r.flags.map(function(f){
        var hit = null;
        ME_SIGNALS.forEach(function(x){ if (x.flag === f) hit = x; });
        return '<div>· ' + esc(hit ? hit.lab : f) + '</div>';
      }).join("") + '</div>'
    : "";

  $("#evList").innerHTML = r.ev.length
    ? r.ev.map(function(e){
        return '<div class="ev"><div class="lab">' + esc(e.lab) +
          '<span class="spk ' + e.speaker + '">' + (e.speaker === "them" ? "对方" : "我") + '</span>' +
          '</div><div class="quo">「' + esc(e.quo) + '」</div>' +
          '<div class="cod">' + esc(e.cod) + '</div></div>';
      }).join("")
    : '<div class="ev" style="border-left-color:var(--ink3)"><div class="lab">未命中任何剧本阶段</div>' +
      '<div class="quo">对方话术里还没有出现诱导、隔离、转账类信号</div>' +
      '<div class="cod">no_signal</div></div>';

  $("#dimBox").innerHTML = r.dims.map(function(x){
    var w = x[1], s = x[2], v = (w * s);
    var pct = Math.round(s * 100);
    return '<div class="line"><span class="k">' + x[0] + '</span>' +
           '<span class="track"><span class="fill" style="width:' + pct + '%;background:' +
           (pct >= 80 ? "var(--l3)" : pct >= 50 ? "var(--l2)" : "var(--accent)") + '"></span></span>' +
           '<span class="v">' + v.toFixed(1) + '</span></div>';
  }).join("");

  $("#jsonBox").textContent = JSON.stringify({
    session_id: state.sid || "—", role:role, turns:r.turns,
    messages:{ them:r.themMsgs, me:r.meMsgs },
    score:Number(r.score.toFixed(1)), level:"L" + lv,
    stage:{ index:r.stageIdx, name:r.stage, weight:Number(r.stageW.toFixed(2)) },
    script:r.scriptName, evidence:r.ev.length,
    evidence_by_speaker:{
      them:r.ev.filter(function(e){ return e.speaker === "them"; }).length,
      me:r.ev.filter(function(e){ return e.speaker === "me"; }).length
    },
    victim_state:r.flags, latency_ms:lat,
    engine:{
      rules:true,
      llm:!!state.engine.llm_enabled,
      asr:!!state.engine.asr_enabled,
      ocr:!!state.engine.ocr_enabled
    }
  }, null, 2);

  $("#adviceBox").innerHTML = adviceHtml(r);

  showLoopback(r.key);

  if (lv >= 3 && prev < 3) {
    if (location.hash.indexOf("noalert") < 0) openOverlay(r.score, speechFor(r), r);
  } else if (lv === 2 && prev < 2) {
    toast("L2 警告：对方已进入「" + r.stage + "」阶段");
    speak("注意，对方正在" + r.stage + "。请先挂断电话，不要在聊天里做任何操作。");
  }
}

/* ---------- 建议（按受害状态优先，其次按等级，最后叠角色话术） ---------- */
function adviceList(r){
  var lv = r.level, list;
  if (r.flags.indexOf("paid") >= 0) {
    list = ["立即挂断并拨打 110 报警，说明转账时间与金额",
            "联系开户行申请紧急止付 / 冻结，越早越可能追回",
            "保留全部聊天记录与转账凭证，不要删除、不要听对方的话"];
  } else if (r.flags.indexOf("code") >= 0) {
    list = ["立即挂断；验证码等于密码，已泄露的账户马上改密码",
            "检查是否被开通免密支付 / 快捷支付 / 新设备登录",
            "拨打 96110 说明情况，并核对近期交易"];
  } else if (lv >= 3) {
    list = ["立即挂断，不回拨、不加微信/QQ",
            "把这段对话转给家人，并拨打 96110 核实",
            "如已转账，24 小时内报警争取止付"];
  } else if (lv >= 2) {
    list = ["先别按对方说的操作，去官方 App 或官网核实",
            "不要把验证码、屏幕共享给任何人",
            "对方要你「保密」这件事本身就是最大的破绽"];
  } else if (lv === 1) {
    list = ["对方还在建立身份，没提到钱 —— 先别给身份证、银行卡、验证码",
            "这类开场和真的客服 / 银行分不出来，继续把对话粘进来，阶段推进会自动升级",
            "不要点对方发来的链接，也不要装对方指定的 App"];
  } else {
    list = ["未发现明显诱导，如仍不放心可拨打 96110",
            "继续把对方的每条消息粘进来，等级会随阶段推进"];
  }
  var roleLine = {
    normal: "",
    elder: "（老年用户）让子女陪你把这段看完再决定，不用怕麻烦他们。",
    student: "（学生）任何要你「先交钱」的兼职、追星、游戏交易都是骗局。",
    child: "（儿童）立刻告诉爸爸妈妈，不要自己操作手机。",
    finance: "（财会）涉及「领导让转账」一律走电话二次确认，不在聊天里办。"
  }[$("#role").value] || "";
  // 画像里只要是独居，就给这条（不管来源是推断还是回答）
  if (computeProfile().living.v === "独居") {
    list = list.concat(["你一个人住 —— 真出事时先给子女或信得过的人打个电话，别自己扛着。"]);
  }
  if (roleLine) list = list.concat([roleLine]);
  return list;
}

function adviceHtml(r){
  var color = (r.flags.length || r.level >= 3) ? "var(--l3)" : r.level >= 2 ? "var(--l2)" : r.level >= 1 ? "var(--l1)" : "var(--ok)";
  return '<div class="muted" style="margin-bottom:6px">建议（' +
    (ROLE_NAME[$("#role").value] || "普通") + '角色 · ' + r.turns + " 轮对话）</div>" +
    adviceList(r).map(function(a){
      return '<div class="ev" style="border-left-color:' + color + '">' + esc(a) + '</div>';
    }).join("");
}

/* ---------- 语音文案：已经受损时说的不是"别转"，是"怎么办" ---------- */
function speechFor(r){
  if (r.flags.indexOf("paid") >= 0) {
    return "你已经转账了。请立即挂断电话，拨打 110 报警，并联系银行申请止付。";
  }
  if (r.flags.indexOf("code") >= 0) {
    return "你已经把验证码告诉了对方。请立即挂断，修改银行卡密码，并拨打 96110。";
  }
  return "检测到高风险诈骗，请立即停止操作。对方正在" + r.stage + "阶段，请挂断电话并联系家人核实。";
}

/* ---------- L3 覆盖层 + 语音 ---------- */
function openOverlay(score, text, r){
  var sub = $("#ovlSub");
  if (sub) {
    sub.innerHTML = r
      ? "命中「" + esc(r.scriptName) + "」" + esc(r.stage) + "阶段 · 评分 <b>" + score.toFixed(1) + "</b> / 100"
      : "评分 <b>" + score.toFixed(1) + "</b> / 100";
  }
  var body = $("#ovlBody");
  if (body) {
    var them = r ? r.ev.filter(function(e){ return e.speaker === "them"; }).slice(0, 4) : [];
    body.innerHTML = them.length
      ? them.map(function(e){
          return '<div class="ev"><div class="lab">' + esc(e.lab) + '</div>' +
            '<div class="quo">「' + esc(e.quo) + '」</div>' +
            '<div class="cod">' + esc(e.cod) + '</div></div>';
        }).join("")
      : '<div class="ev"><div class="lab">暂无对方话术证据</div></div>';
  }
  var gd = $("#ovlGuardian");
  if (gd) gd.textContent = "已通知监护人（" + state.guardian.name + " · " + state.guardian.rel + "）";
  $("#ovl").classList.add("on");
  speak(text || "检测到高风险诈骗，请立即停止操作。请挂断电话，并立即联系家人核实。");
}
function closeOverlay(){
  $("#ovl").classList.remove("on");
  try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch(e){}
  $("#voiceState").textContent = "语音播报中…";
}
function speak(text){
  if (!("speechSynthesis" in window)) { $("#voiceState").textContent = "本机不支持语音（speechSynthesis 缺失）"; return; }
  try {
    window.speechSynthesis.cancel();
    var u = new SpeechSynthesisUtterance(text);
    u.lang = "zh-CN"; u.rate = 1.02; u.pitch = 1;
    u.onend = function(){ $("#voiceState").textContent = "播报结束"; };
    window.speechSynthesis.speak(u);
    $("#voiceState").textContent = "语音播报中…";
  } catch(e) { $("#voiceState").textContent = "语音被浏览器拦截（需先交互）"; }
}

/* ---------- 设置：监护人配置（FR-3.3「可配置监护人」） ---------- */
function openSettings(){
  var n = $("#gName"), r = $("#gRel"), s2 = $("#gSecond"), hk = $("#gHook"), msg = $("#setMsg");
  if (n) n.value = state.guardian.name || "";
  if (r) r.value = state.guardian.rel || "女儿";
  if (s2) s2.value = state.guardian.second || "";
  if (hk) hk.value = state.webhook ? "1" : "0";
  if (msg) msg.textContent = "—";
  var ov = $("#setOvl");
  if (ov) ov.classList.add("on");
}

function closeSettings(){
  var ov = $("#setOvl");
  if (ov) ov.classList.remove("on");
}

function saveSettings(){
  var name = ($("#gName").value || "").trim();
  if (!name) { $("#setMsg").textContent = "监护人姓名不能为空"; return; }
  state.guardian = {
    name: name,
    rel: $("#gRel").value || "女儿",
    second: ($("#gSecond").value || "").trim()
  };
  state.webhook = $("#gHook").value === "1";
  // 通道配置按"当前"生效：开关一变，当前告警的推送状态跟着重算（便于演示降级态）
  var cur = currentAlert();
  if (cur) cur.pushed = (cur.level >= 3 && state.webhook);
  closeSettings();
  renderAlertPage();
  renderReport();
  toast("已保存：" + state.guardian.name + " · " + (state.webhook ? "通道已配置" : "通道未配置（降级）"));
}

/* ---------- 事件 ---------- */
$$("#tabs .tab").forEach(function(el){
  el.addEventListener("click", function(){ switchView(el.dataset.view); });
});

$$(".presets .btn").forEach(function(b){
  b.addEventListener("click", function(){
    var k = b.dataset.preset;
    var src = CONVOS[k];
    if (!src) return;
    state.conv = src.turns.map(function(t){ return { w:t.w, t:t.t }; });
    state.level = 0;
    state.last = null;
    state.history = [];
    $("#input").value = "";
    resetAlerts();
    newSession();
    predict();
  });
});

$$("#mods .chip").forEach(function(c){
  c.addEventListener("click", function(){
    if (c.dataset.mod !== "text") { toast("该模态尚未启用：需要配置 ASR / OCR 引擎，接口会返回 501 并说明原因"); return; }
    $$("#mods .chip").forEach(function(x){ x.classList.toggle("on", x === c); });
  });
});

$("#sendThem").addEventListener("click", function(){ addTurn("them"); });
$("#sendMe").addEventListener("click", function(){ addTurn("me"); });

$("#undo").addEventListener("click", function(){
  if (!state.conv.length) { toast("对话已经是空的了"); return; }
  state.conv.pop();
  state.level = 0;
  state.history = state.history.filter(function(x){ return x.turn <= state.conv.length; });
  predict();
  toast("已撤销上一条，等级已重算");
});

$("#clear").addEventListener("click", function(){
  if (!state.conv.length) return;
  state.conv = [];
  state.level = 0;
  state.last = null;
  state.history = [];
  resetAlerts();
  newSession();
  render();
  toast("对话已清空");
});

$("#pfToggle").addEventListener("click", function(){
  var card = $("#profileCard");
  var closed = card.classList.toggle("collapsed");
  this.textContent = closed ? "展开" : "收起";
});

$("#role").addEventListener("change", function(){
  var rv = $("#role").value;
  if (state.conv.length) predict({ refresh:true }); else render();
  toast("角色已切换为「" + (ROLE_NAME[rv] || rv) + "」：分数与阈值已重算");
});

$("#ovlClose").addEventListener("click", closeOverlay);
$("#ovlToAlert").addEventListener("click", function(){ closeOverlay(); switchView("alert"); });

$("#callBtn").addEventListener("click", function(){
  var a = currentAlert();
  if (!a) { toast("还没有告警"); return; }
  a.read = true;
  renderAlertPage();
  toast("正在拨打 " + state.guardian.name + " 的号码…（演示）");
});

$("#callPolice").addEventListener("click", function(){
  var a = currentAlert();
  if (!a) { toast("还没有告警"); return; }
  a.read = true;
  renderAlertPage();
  toast("正在拨打 96110…（演示）");
});

$("#ackBtn").addEventListener("click", function(){
  var a = currentAlert();
  if (!a || a.acked) return;
  var btn = this;
  a.read = true;
  renderAlertPage();
  if (!state.lastAlertId) {
    toast("这条告警没有后端编号：先跑一轮判别再回写");
    return;
  }
  btn.disabled = true;
  A30Adapter.ack(state.lastAlertId, "ack").then(function(){
    a.acked = true;
    state.acked = true;
    renderAlertPage();
    renderReport();
    toast("已回写后端：告警 → 已读 → 已介入");
  }).catch(function(e){
    renderAlertPage();
    toast("回写失败：" + e.message);
  });
});

/* 报告里的"五、通知记录"用后端报告的真实记录；取不到就退回本地汇总 */
function loadServerReport(){
  if (!state.sid) return;
  A30Adapter.report(state.sid).then(function(rep){
    state.serverReport = rep || null;
    if (state.view === "report") renderReport();
  }).catch(function(e){
    state.serverReport = null;
    toast("报告接口失败：" + e.message + "（页面仍显示本地汇总）");
  });
}

$("#printBtn").addEventListener("click", function(){
  renderReport();
  switchView("report");
  loadServerReport();
  setTimeout(function(){ window.print(); }, 60);
});

// 由用户决定对话结束，才生成报告（B2）
$("#finishBtn").addEventListener("click", function(){
  if (!state.conv.length) { toast("还没有对话，先粘一条"); return; }
  state.reportAt = nowStr();
  switchView("report");
  loadServerReport();
  toast("报告已生成 · 之后不再随对话变化");
});

// 改动输入即撤回上一条回执，避免"旧回执挂在新内容下"
$("#input").addEventListener("input", hideLoopback);

// 回车 = 对方说的；Ctrl+Enter = 我说的；Shift+Enter 换行
$("#input").addEventListener("keydown", function(e){
  if (e.key !== "Enter" || e.shiftKey) return;
  e.preventDefault();
  addTurn(e.ctrlKey ? "me" : "them");
});

/* ---------- 设置入口 ---------- */
$("#setBtn").addEventListener("click", openSettings);
$("#setCancel").addEventListener("click", closeSettings);
$("#setSave").addEventListener("click", saveSettings);
$("#setOvl").addEventListener("click", function(e){
  if (e.target === this) closeSettings();
});

/* ---------- 会话与概览：真实 session_id + /health 的数字 ---------- */
function newSession(){
  state.sid = A30Adapter.reset();
  state.history = [];
  $("#sessVal").textContent = state.sid;
}

function hydrateOverview(){
  var chips = $$(".overview div");
  function setB(i, val){
    if (!chips[i]) return;
    var b = chips[i].querySelector("b");
    if (b) b.textContent = val;
  }
  A30Adapter.health().then(function(h){
    state.engine = h || {};
    setB(0, h.kb_scripts != null ? h.kb_scripts : "—");
    setB(1, h.kb_cases != null ? h.kb_cases : "—");
    setB(4, h.llm_enabled ? "已启用" : "未启用");
    setB(5, h.asr_enabled ? "已启用" : "未启用");
    setB(6, h.ocr_enabled ? "已启用" : "未启用");
    var ver = $("#kbVer");
    if (ver) { ver.textContent = "未登记"; ver.title = "后端 /health 只给应用版本 " + (h.version || "—") + "，没有知识库版本号"; }
    updateKb();
  }).catch(function(e){
    toast("后端未连接：" + e.message + "（页面只展示空态，不做本地假判定）");
    setB(0, "—"); setB(1, "—");
    setB(4, "未连接"); setB(5, "未连接"); setB(6, "未连接");
    var ver = $("#kbVer");
    if (ver) ver.textContent = "—";
  });
}

/* ---------- 深链接（给截图/演示用） ---------- */
function boot(){
  var h = decodeURIComponent(location.hash.replace(/^#/, ""));
  var wantView = null;
  if (h.indexOf("view=") >= 0) {
    var v = h.split("view=")[1].split("&")[0];
    if (["detect","alert","report"].indexOf(v) >= 0) { wantView = v; switchView(v); }
  }
  if (h.indexOf("run=") >= 0) {
    var k = h.split("run=")[1].split("&")[0];
    if (CONVOS[k]) {
      if (!wantView) switchView("detect");
      state.conv = CONVOS[k].turns.map(function(t){ return { w:t.w, t:t.t }; });
      state.level = 0;
      state.last = null;
      newSession();
      predict();
    }
  }
  if (h.indexOf("overlay") >= 0) { switchView("detect"); openOverlay(95.3); }
  // 首屏先放对方的第 1 条：一进来就看到"只到立威 / L1 提醒"，这就是"早"
  if (!state.conv.length && !h) {
    state.conv = [
      { w:"them", t: CONVOS.s01.turns[0].t },
      { w:"me",   t:"我一个人住，孩子在国外，不想麻烦他们。" }
    ];
    state.level = 0;
    state.last = null;
    predict();
  }
}
window.addEventListener("hashchange", boot);
if (!state.sid) newSession();
hydrateOverview();
boot();
