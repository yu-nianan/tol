"use strict";

/* ---------- 适配层：把后端 Decision 翻译成原型 analyze() 的输出形状 ----------
 *
 * 原型（app.js / report.js / alert.js）只认一个对象：
 *   { score, level, stage, stageIdx, stageW, flags[], bias,
 *     ev:[{speaker, lab, quo, cat, w, stage, cod}],
 *     themCount, themMsgs, meMsgs, turns, scriptName, key,
 *     dims:[[label, weightPct, rate]] }
 *
 * 本文件只做"取数 + 翻译"：不碰 DOM、不改渲染、不自己算分数。
 * 一次检测 = 一轮：只把"这一轮对方说的话"送后端（后端按 session 累计阶段）；
 * 我方的话不送后端，只用来算受害状态（原型语义：我的话只进"受害状态"，不计分）。
 */
(function () {
  var API = "/api/v1";

  /* 后端维度键 → 原型里的中文标签（顺序固定，缺的维度给 0） */
  var DIM_ORDER = ["stage", "entity", "pressure", "cross", "channel", "profile"];
  var DIM_LABEL = {
    stage: "阶段", entity: "实体", pressure: "话术",
    cross: "跨模态", channel: "渠道", profile: "画像"
  };

  /* 后端 stage_index（0 未命中 / 1 接触 / 2 立威 / 3 隔离 / 4 诱导转账）
     → 原型 5 格阶段条的槽位。原型第 4 格"诱导操作"后端没有对应阶段，永不点亮。 */
  var STAGE_SLOT = { 1: 0, 2: 1, 3: 2, 4: 4 };

  /* 证据自带的阶段标签（rules 里 category 就是 stage_xxx）也能定位阶段：
     后端 stage_index 只在本轮文本命中剧本时才前进，单条消息常拿不到 S01，
     所以取"证据里最高阶段"和 stage_index 的较大值，避免分数到了 L2 阶段条还停在接触。 */
  var EVIDENCE_STAGE = {
    stage_contact: 0, stage_authority: 1, stage_isolation: 2, stage_transfer: 4
  };

  var S = { sid: null, sent: 0, last: null, best: null };

  function randomId() {
    return "web-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 6);
  }

  /* 新会话：换 session_id 并让后端从头累计阶段 */
  function reset() {
    S.sid = randomId();
    S.sent = 0;
    S.last = null;
    S.best = null;
    window.__A30_SESSION__ = S.sid;
    return S.sid;
  }

  function sessionId() {
    if (!S.sid) reset();
    return S.sid;
  }

  async function request(path, opts) {
    opts = opts || {};
    var res;
    try {
      res = await fetch(API + path, {
        method: opts.method || "GET",
        headers: opts.body ? { "Content-Type": "application/json" } : undefined,
        body: opts.body ? JSON.stringify(opts.body) : undefined
      });
    } catch (e) {
      throw new Error("连不上后端：" + (e && e.message ? e.message : "网络错误"));
    }
    var data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      var err = (data && data.error) || {};
      var msg = err.message || ("HTTP " + res.status);
      if (err.code) msg += "（" + err.code + "）";
      throw new Error(msg);
    }
    return data;
  }

  /* 我方的话 → 受害状态（与原型同一套规则，只影响提示与建议，不进分数） */
  function victimFlags(conv) {
    var flags = [];
    if (typeof ME_SIGNALS === "undefined") return flags;
    conv.forEach(function (m) {
      if (m.w !== "me") return;
      ME_SIGNALS.forEach(function (s) {
        if (s.re.test(m.t) && flags.indexOf(s.flag) < 0) flags.push(s.flag);
      });
    });
    return flags;
  }

  /* 证据落到"第几轮、谁说的"：后端不给轮次，用原文在我方对话里反查 */
  function squash(x) {
    return String(x || "").replace(/[^0-9A-Za-z\u4e00-\u9fa5]/g, "");
  }

  function locate(conv, text) {
    var t = squash(text);
    for (var i = conv.length - 1; i >= 0; i--) {
      var m = conv[i];
      if (!m || !m.t) continue;
      var mt = squash(m.t);
      if (t && (mt.indexOf(t) >= 0 || t.indexOf(mt) >= 0)) {
        return { turn: i + 1, speaker: m.w };
      }
    }
    return { turn: conv.length, speaker: "them" };
  }

  function dimsOf(decision) {
    var weights = decision.dim_weights || {};
    var rates = decision.dims || {};
    return DIM_ORDER.map(function (key) {
      var rate = typeof rates[key] === "number" ? rates[key] : 0;
      var w = typeof weights[key] === "number" ? Math.round(weights[key]) : 0;
      return [DIM_LABEL[key], w, Math.max(0, Math.min(1, rate))];
    });
  }

  /* Decision → 原型对象 */
  function decorate(decision, conv, role, latency) {
    var script = decision.script || null;
    var evidences = decision.evidence || [];

    // 阶段槽位：stage_index 与"证据里最高的阶段标签"取大（后端单条消息常匹配不到整本剧本）
    var idxSlot = (script && typeof decision.stage_index === "number" &&
                   Object.prototype.hasOwnProperty.call(STAGE_SLOT, decision.stage_index))
      ? STAGE_SLOT[decision.stage_index] : -1;
    var evSlot = -1;
    evidences.forEach(function (e) {
      var key = e.category || (e.meta && e.meta.stage) || "";
      if (Object.prototype.hasOwnProperty.call(EVIDENCE_STAGE, key)) {
        evSlot = Math.max(evSlot, EVIDENCE_STAGE[key]);
      }
    });
    var slot = Math.max(idxSlot, evSlot);

    // 剧本名"粘住"：本轮没匹配到剧本时沿用本会话最近一次命中的，避免同一段对话里标题忽有忽无
    if (script) S.best = script;
    var shown = script || S.best;
    // 阶段文案跟着"实际点亮的格子"走：证据显示到了转账，就不能还挂着第一轮的"接触"
    var stageLabel = slot >= 0 && typeof STAGES !== "undefined" ? STAGES[slot] : "无命中";
    var stageW = typeof STAGE_W !== "undefined" && slot >= 0 ? STAGE_W[slot]
      : (shown && typeof shown.stage_weight === "number" ? shown.stage_weight : 0);

    var ev = evidences.map(function (e) {
      var at = locate(conv, e.text);
      var tag = (e.meta && e.meta.stage) ? ("stage=" + e.meta.stage) : (e.code || "evidence");
      return {
        speaker: at.speaker,
        lab: e.label || e.code || "证据",
        quo: e.text || "",
        cat: e.category || "",
        w: typeof e.weight === "number" ? e.weight : 0,
        stage: slot,
        cod: "第" + at.turn + "轮 · " + tag +
             (typeof e.weight === "number" ? " · w=" + e.weight.toFixed(2) : "")
      };
    });

    var flags = victimFlags(conv);
    if (flags.length && typeof ME_SIGNALS !== "undefined") {
      ME_SIGNALS.forEach(function (s) {
        if (flags.indexOf(s.flag) < 0) return;
        var hit = null;
        conv.forEach(function (m, i) { if (m.w === "me" && s.re.test(m.t)) hit = hit || (i + 1); });
        ev.push({
          speaker: "me", lab: s.lab, quo: "", cat: "受害状态", w: 0, stage: slot,
          cod: "第" + (hit || conv.length) + "轮 · victim_state=" + s.flag
        });
      });
    }

    var scriptId = shown && shown.script_id ? String(shown.script_id).toLowerCase() : null;
    return {
      score: typeof decision.score === "number" ? decision.score : 0,
      level: typeof decision.level === "number" ? decision.level : 0,
      stage: stageLabel,
      stageIdx: slot,
      stageW: stageW,
      flags: flags,
      bias: (typeof ROLE_BIAS !== "undefined" && ROLE_BIAS[role]) || 0,
      ev: ev,
      themCount: (decision.evidence || []).length,
      themMsgs: conv.filter(function (m) { return m.w === "them"; }).length,
      meMsgs: conv.filter(function (m) { return m.w === "me"; }).length,
      turns: conv.length,
      scriptName: shown ? ((shown.script_id || "") + " " + (shown.name || "")).trim() : "—",
      key: scriptId,
      dims: dimsOf(decision),
      latency: typeof latency === "number" ? latency : 0,
      alertId: (decision.alert && decision.alert.id) || null,
      raw: decision
    };
  }

  /* 空态：用来占位，避免"没结果时显示上一轮的数字" */
  function blank(conv, role) {
    return {
      score: 0, level: 0, stage: "无命中", stageIdx: -1, stageW: 0,
      flags: victimFlags(conv || []),
      bias: (typeof ROLE_BIAS !== "undefined" && ROLE_BIAS[role]) || 0,
      ev: [], themCount: 0,
      themMsgs: (conv || []).filter(function (m) { return m.w === "them"; }).length,
      meMsgs: (conv || []).filter(function (m) { return m.w === "me"; }).length,
      turns: (conv || []).length, scriptName: "—", key: null,
      dims: DIM_ORDER.map(function (k) { return [DIM_LABEL[k], 0, 0]; }),
      latency: 0, alertId: null, raw: null
    };
  }

  /**
   * 判别当前对话。
   * - 只把"还没送过的对方消息"按顺序送后端（后端按 session 累计阶段，不会重算历史）；
   * - 对话变短（撤销 / 清空 / 切预设）→ 换 session 从头重放，避免后端状态错位；
   * - refresh=true（切角色）→ 用新角色重发最后一条对方消息。
   */
  async function analyze(conv, role, opts) {
    opts = opts || {};
    if (!conv || !conv.length) { S.sent = 0; S.last = null; return blank(conv, role); }

    var lastThem = -1;
    for (var i = conv.length - 1; i >= 0; i--) {
      if (conv[i].w === "them") { lastThem = i; break; }
    }
    if (lastThem < 0) { S.last = blank(conv, role); return S.last; }

    if (S.sent > lastThem + 1 || opts.refresh) { reset(); }

    var latency = 0;
    for (var idx = S.sent; idx <= lastThem; idx++) {
      if (conv[idx].w !== "them") { S.sent = idx + 1; continue; }
      var resp = await request("/detect/text", {
        method: "POST",
        body: { text: conv[idx].t, session_id: sessionId(), role: role }
      });
      latency = resp.latency_ms || latency;
      S.last = decorate((resp.decision || {}), conv.slice(0, idx + 1), role, latency);
      S.last.alertId = (resp.alert && resp.alert.id) || null;
      S.sent = idx + 1;
    }

    if (!S.last) S.last = blank(conv, role);
    /* 轮次 / 我方条数按当前对话刷新（撤销、追加我方消息都会变） */
    S.last.turns = conv.length;
    S.last.themMsgs = conv.filter(function (m) { return m.w === "them"; }).length;
    S.last.meMsgs = conv.filter(function (m) { return m.w === "me"; }).length;
    S.last.flags = victimFlags(conv);
    return S.last;
  }

  async function health() { return request("/health"); }
  async function ack(alertId, action, note) {
    return request("/alerts/" + encodeURIComponent(alertId) + "/ack", {
      method: "POST", body: { action: action || "ack", note: note || "" }
    });
  }
  async function report(sid) { return request("/report/" + encodeURIComponent(sid || sessionId())); }

  window.A30Adapter = {
    analyze: analyze,
    reset: reset,
    sessionId: sessionId,
    blank: blank,
    health: health,
    ack: ack,
    report: report
  };
})();
