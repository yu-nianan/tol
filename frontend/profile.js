"use strict";

/* ---------- 画像：冷启动自选 + 对话中零提问推断 ---------- */
var ROLE_AGE = { normal:"青壮年", elder:"老年", child:"儿童", student:"青少年", finance:"青壮年" };

var PROFILE_RULES = [
  { key:"living",   v:"独居",         re:/一个人住|独居|自己住|老伴.{0,3}(走|没)|孩子.{0,6}(国外|不在身边|外地)/ },
  { key:"job",      v:"财会",         re:/做(会计|财务)|出纳|管账|财务部/ },
  { key:"digital",  v:"数字操作不熟",  re:/不会(用|弄|操作)|你教我|怎么点|找不到|看不清/ },
  { key:"pressure", v:"已被隔离施压",  re:/不敢(说|告诉)|他说不能|别告诉家人|不告诉家人/ }
];

var PF_LABEL = { age:"年龄段", living:"居住", job:"职业", digital:"数字熟练度", pressure:"当前处境" };
var PF_ORDER = ["age", "living", "job", "digital", "pressure"];

function computeProfile(){
  var role = $("#role").value;
  var p = {
    age:      { v: ROLE_AGE[role] || "青壮年", src:"self" },
    living:   { v:null, src:"pending" },
    job:      { v: role === "finance" ? "财会" : null, src: role === "finance" ? "self" : "pending" },
    digital:  { v:null, src:"pending" },
    pressure: { v:null, src:"pending" },
    why: null
  };
  state.conv.forEach(function(m, idx){
    if (m.w !== "me") return;
    PROFILE_RULES.forEach(function(rule){
      if (p[rule.key].src === "self") return;
      if (!rule.re.test(m.t)) return;
      p[rule.key].v = rule.v;
      p[rule.key].src = "inferred";
      p.why = { turn: idx + 1, text: m.t };
    });
  });
  // 系统问过并答过的，覆盖推断结果
  Object.keys(state.qa.answers).forEach(function(k){
    var a = state.qa.answers[k];
    if (a && a.pf) p[k] = { v: a.pf, src: "asked" };
  });
  return p;
}

function renderProfile(){
  var chips = $("#pfChips");
  if (!chips) return;
  var p = computeProfile();
  var sum = [], html = [];
  PF_ORDER.forEach(function(k){
    var f = p[k];
    if (f.src === "pending" || !f.v) {
      html.push('<span class="pf-chip pending">' + PF_LABEL[k] + ' 待确认</span>');
      return;
    }
    sum.push(f.v);
    html.push('<span class="pf-chip ' + f.src + '">' + esc(f.v) +
      '<span class="pf-src">' + (f.src === "self" ? "自选" : (f.src === "asked" ? "回答" : "推断")) + "</span></span>");
  });
  chips.innerHTML = html.join("");
  var sm = $("#pfSum");
  if (sm) sm.textContent = sum.length ? sum.join(" · ") : "还没有你的画像";
  var w = $("#pfWhy");
  if (w) {
    w.innerHTML = p.why
      ? "推断依据：第 " + p.why.turn + " 轮你说「" + esc(p.why.text) + "」—— 不需要你填表"
      : "画像会随对话自动长出来：你说过的话里有线索（退休 / 一个人住 / 做会计…），不需要填表。";
  }
}

/* ---------- 对话内提问：只在低风险时问，一次会话最多 2 个 ---------- */
var QUESTIONS = [
  { key:"living", q:"平时家里有人一起住吗？",
    opts:[
      { v:"一个人住", pf:"独居" },
      { v:"和家人住", pf:"有家人同住" },
      { v:"不方便说", pf:null }
    ] },
  { key:"digital", q:"手机银行、转账这类操作，你自己弄得多吗？",
    opts:[
      { v:"我自己能弄", pf:"操作熟练" },
      { v:"要人帮忙",   pf:"数字操作不熟" },
      { v:"基本不会",   pf:"数字操作不熟" }
    ] }
];

function maybeAsk(r){
  if (r.level >= 2) { state.qa.current = null; return; }    // 营救优先：升到 L2 连正在问的也撤掉
  if (state.qa.current) return;
  if (state.qa.asked >= 2) return;                         // 一次会话最多 2 个
  if (state.conv.length - state.qa.lastTurn < 3) return;   // 每 3 轮最多 1 个
  var p = computeProfile();
  for (var i = 0; i < QUESTIONS.length; i++) {
    var q = QUESTIONS[i];
    if (state.qa.answers[q.key]) continue;                 // 问过不再问
    if (p[q.key].src !== "pending") continue;              // 已经知道了就别问
    state.qa.current = q;
    return;
  }
}

function qaHtml(){
  var q = state.qa.current;
  if (!q) return "";
  return '<div class="qa">' +
    '<div class="qa-head">安全助手 · 想确认一件事</div>' +
    '<div class="qa-q">' + esc(q.q) + '</div>' +
    '<div class="qa-opts">' + q.opts.map(function(o, i){
      return '<button class="qa-opt" id="qa-opt-' + i + '" type="button">' + esc(o.v) + '</button>';
    }).join("") + '</div>' +
    '<div class="qa-note">只用来调整后续提醒的说法，不影响这次判定。不想说可以选「不方便说」。</div>' +
  '</div>';
}

function bindQa(){
  var q = state.qa.current;
  if (!q) return;
  q.opts.forEach(function(o, i){
    var b = $("#qa-opt-" + i);
    if (b) b.addEventListener("click", function(){ answerQa(i); });
  });
}

function answerQa(idx){
  var q = state.qa.current;
  if (!q || !q.opts[idx]) return;
  var o = q.opts[idx];
  state.qa.answers[q.key] = { v: o.v, pf: o.pf || null };
  state.qa.asked += 1;
  state.qa.lastTurn = state.conv.length;
  state.qa.current = null;
  toast("已记录：" + o.v);
  render();
}
