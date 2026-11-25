/* 主控：路由、对话录入、调用检测、渲染结果、串起告警与报告。
 *
 * 路由（hash）：#/detect（默认）、#/alert/<alert_id>、#/report/<session_id>
 * 接口一律走同源相对路径 /api/v1（见 api.js），不写死 host/port。
 *
 * 分工：api.js 只发请求，profile/store/alert/report 只渲染各自的块，
 * 本文件是唯一把状态串起来的层，别再往别处写业务判断。
 */
(function (global) {
  "use strict";

  var state = {
    role: "normal",
    sessionId: "",
    turns: [],
    decisions: [],
    alerts: [],
    activeAlertId: "",
    profile: null,
    profileWhy: [],
    askedCount: 0,
    askedPending: null,
    scripts: {},
    health: null,
    settings: null,
    busy: false
  };

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  var toastTimer = null;
  function toast(msg) {
    var box = $("toast");
    if (!box) return;
    box.textContent = msg;
    box.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.hidden = true; }, 2600);
  }

  /* ---------------- 路由 ---------------- */

  function parseHash() {
    var raw = (location.hash || "#/detect").replace(/^#/, "");
    var parts = raw.split("?");
    var path = parts[0] || "/detect";
    var query = {};
    if (parts[1]) {
      parts[1].split("&").forEach(function (kv) {
        var p = kv.split("=");
        if (p[0]) query[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || "");
      });
    }
    var seg = path.split("/").filter(Boolean);
    return { view: seg[0] || "detect", param: seg[1] || "", query: query };
  }

  function setView(view) {
    ["detect", "alert", "report"].forEach(function (name) {
      var sec = $("view-" + name);
      if (sec) sec.hidden = name !== view;
    });
    Array.prototype.forEach.call(document.querySelectorAll("#tabs a"), function (a) {
      if (a.getAttribute("data-view") === view) a.classList.add("on");
      else a.classList.remove("on");
    });
  }

  function route() {
    var r = parseHash();
    setView(r.view);

    if (r.view === "alert") {
      if (r.param) showAlert(r.param);
      else if (state.alerts.length) showAlert(state.alerts[state.alerts.length - 1].id);
      else {
        AlertUI.renderDetail(null, {});
        AlertUI.renderPhone(null, state.settings || {});
      }
    }

    if (r.view === "report") {
      var sid = r.param || state.sessionId;
      if (sid) loadReport(sid);
    }
  }

  /* ---------------- 渲染：对话 ---------------- */

  function renderConvo() {
    var box = $("convo");
    if (!box) return;
    box.innerHTML = "";
    state.turns.forEach(function (t, i) {
      var b = el("div", "bubble " + (t.role === "me" ? "me" : "them"));
      b.appendChild(el("span", "who", (t.role === "me" ? "我" : "对方") + " · 第 " + (i + 1) + " 轮"));
      b.appendChild(document.createTextNode(t.text));
      box.appendChild(b);
    });

    if (state.askedPending) {
      box.appendChild(el("div", "bubble typing", state.askedPending.text));
      var optRow = el("div", "row");
      state.askedPending.options.forEach(function (o) {
        var btn = el("button", "ghost", o.label);
        btn.type = "button";
        btn.addEventListener("click", function () { answerQuestion(o); });
        optRow.appendChild(btn);
      });
      box.appendChild(optRow);
    }

    box.scrollTop = box.scrollHeight;

    var meta = $("convoMeta");
    if (meta) meta.textContent = state.turns.length + " 轮";
  }

  /* ---------------- 渲染：结果 ---------------- */

  function stageBar(decision) {
    var bar = $("stageBar");
    if (!bar) return;
    bar.innerHTML = "";

    var scriptId = decision.script && decision.script.script_id;
    var script = scriptId ? state.scripts[scriptId] : null;
    var stages = (script && script.stages) || [];

    if (!stages.length) {
      bar.appendChild(el("div", "seg",
        scriptId ? "已命中剧本，但没取到阶段定义" : "未命中剧本（可能是闲聊）"));
      return;
    }

    stages.forEach(function (st, i) {
      var cls = "seg";
      if (i < decision.stage_index) cls += " done";
      if (i === decision.stage_index) cls += " on";
      bar.appendChild(el("div", cls, st.label || st.name));
    });
  }

  function attributeTurns(evidence) {
    return (evidence || []).map(function (ev) {
      var hit = null;
      for (var i = state.turns.length - 1; i >= 0; i--) {
        var t = state.turns[i];
        if (ev.text && t.text && (t.text.indexOf(ev.text) !== -1 || ev.text.indexOf(t.text) !== -1)) {
          hit = { turn: i + 1, speaker: t.role === "me" ? "我说的" : "对方说的" };
          break;
        }
      }
      var copy = {};
      Object.keys(ev).forEach(function (k) { copy[k] = ev[k]; });
      if (hit) { copy.turn = hit.turn; copy.speaker = hit.speaker; }
      return copy;
    });
  }

  function victimLines(evidence) {
    var hits = (evidence || []).filter(function (ev) {
      return (ev.code && ev.code.indexOf("victim") === 0) || (ev.meta && ev.meta.victim);
    });
    if (!hits.length) return "";
    return "受害状态：" + hits.map(function (ev) { return ev.label; }).join("、");
  }

  function renderResult(payload) {
    var empty = $("emptyState");
    var box = $("resultBox");
    if (empty) empty.hidden = true;
    if (box) box.hidden = false;

    var d = payload.decision || {};
    var badge = $("levelBadge");
    if (badge) {
      badge.textContent = "L" + (d.level | 0);
      badge.style.background = "var(--" + AlertUI.levelClass(d.level) + ")";
    }
    if ($("score")) $("score").textContent = d.score === undefined ? "—" : d.score;

    if ($("meta")) {
      var bits = [];
      bits.push("阶段：" + ((d.script && (d.script.stage_label || d.script.stage_name)) || "无"));
      bits.push("轮次：第 " + state.turns.length + " 轮");
      bits.push("时延：" + (payload.latency_ms || 0) + "ms");
      if (d.need_human) bits.push("建议人工介入");
      if (d.cap_applied) bits.push("未引用案例，置信度封顶");
      $("meta").textContent = bits.join(" · ");
    }

    stageBar(d);

    var victim = $("victimBox");
    if (victim) {
      var line = victimLines(d.evidence);
      victim.hidden = !line;
      victim.textContent = line;
    }

    var evBox = $("evList");
    if (evBox) {
      evBox.innerHTML = "";
      var list = attributeTurns(d.evidence);
      if ($("evCount")) $("evCount").textContent = "共 " + list.length + " 条";
      if (!list.length) {
        evBox.appendChild(el("li", "hint", "这一轮没有命中证据（分数只来自画像/渠道等弱信号）。"));
      }
      list.forEach(function (ev) {
        var item = el("li", "ev" + (ev.kind === "context" ? " ctx" : ""));
        item.appendChild(el("div", "label", ev.label || ev.code || "证据"));
        item.appendChild(el("div", "quote", "「" + (ev.text || "") + "」"));
        var sub = "置信度 " + Math.round((ev.confidence || 0) * 100) + "%";
        if (ev.weight) sub += " · 权重 " + ev.weight;
        if (ev.turn) sub += " · 第 " + ev.turn + " 轮 · " + ev.speaker;
        item.appendChild(el("div", "sub", sub));
        evBox.appendChild(item);
      });
    }

    var dimBox = $("dimBox");
    if (dimBox) {
      dimBox.innerHTML = "";
      var dims = d.dims || {};
      var keys = Object.keys(dims);
      if (!keys.length) {
        dimBox.appendChild(el("p", "hint", "后端这次没返回维度明细（需 Decision.dims，见 ADR-0006）。"));
      }
      keys.forEach(function (k) {
        var v = Math.max(0, Math.min(1, Number(dims[k]) || 0));
        var row = el("div", "dim");
        row.appendChild(el("span", "", k));
        var bar = el("span", "bar");
        var fill = el("i");
        fill.style.width = (v * 100).toFixed(0) + "%";
        bar.appendChild(fill);
        row.appendChild(bar);
        row.appendChild(el("span", "val", v.toFixed(2)));
        dimBox.appendChild(row);
      });
    }

    var advice = $("adviceBox");
    if (advice) {
      advice.innerHTML = "";
      var tips = (d.script && d.script.advice) || d.reasons || [];
      if (!tips.length) advice.appendChild(el("li", "", "暂无建议。"));
      tips.forEach(function (t) { advice.appendChild(el("li", "", t)); });
    }

    if ($("jsonBox")) $("jsonBox").textContent = JSON.stringify(payload, null, 2);
  }

  /* ---------------- 检测 ---------------- */

  function send(text, speaker) {
    text = (text || "").trim();
    if (!text) { toast("先输入点内容"); return; }
    if (state.busy) { toast("上一条还在检测中"); return; }
    if (text.length > 4000) { toast("太长了，后端上限 4000 字"); return; }

    state.turns.push({ role: speaker === "me" ? "me" : "them", text: text, ts: Date.now() });
    store.saveTurns(state.sessionId, state.turns);

    if ($("input")) $("input").value = "";
    state.busy = true;
    renderConvo();

    var convo = $("convo");
    var typing = null;
    if (convo) {
      typing = el("div", "bubble typing", "检测中…");
      convo.appendChild(typing);
      convo.scrollTop = convo.scrollHeight;
    }

    function done() {
      if (typing && typing.parentNode) typing.parentNode.removeChild(typing);
      state.busy = false;
    }

    api.detectText(text, state.sessionId, state.role)
      .then(function (payload) {
        done();
        renderResult(payload);
        afterDecision(payload);
      })
      .catch(function (err) {
        done();
        toast(err.message || "检测失败");
        if ($("meta")) {
          $("meta").textContent = "检测失败：" + (err.message || "") + (err.code ? "（" + err.code + "）" : "");
        }
      });
  }

  function afterDecision(payload) {
    var d = payload.decision || {};

    store.pushDecision(state.sessionId, {
      score: d.score || 0,
      level: d.level || 0,
      stage_index: d.stage_index || 0,
      script_name: (d.script && d.script.name) || "",
      dims: d.dims || {},
      ts: Date.now()
    });

    if (payload.alert) {
      state.alerts.push(payload.alert);
      store.saveAlerts(state.alerts);
      state.activeAlertId = payload.alert.id;
      AlertUI.renderList(state.alerts, state.activeAlertId, showAlert);
      AlertUI.renderPhone(payload.alert, state.settings || {});
    }

    if ((d.level | 0) >= 3) showL3(d);

    if ((d.level | 0) >= 2) {
      state.askedPending = null;
    } else {
      state.askedPending = Profile.nextQuestion({
        turns: state.turns,
        profile: state.profile,
        level: d.level || 0,
        asked: state.askedCount
      });
    }
    renderConvo();

    var inf = Profile.infer(state.turns, state.profile, state.role);
    if (Object.keys(inf.patch).length) {
      Profile.applyPatch(state.profile, inf.patch);
      state.profileWhy = state.profileWhy.concat(inf.why).slice(-4);
      store.saveProfile(state.profile);
      Profile.render(state.profile, state.profileWhy);
    }
  }

  function answerQuestion(opt) {
    Profile.setField(state.profile, opt.key, opt.value, "answer");
    state.askedCount += 1;
    state.askedPending = null;
    store.saveProfile(state.profile);
    Profile.render(state.profile, state.profileWhy);
    renderConvo();
    toast("已记录：" + opt.label);
  }

  /* ---------------- 告警 ---------------- */

  function isPushed() {
    return !!(state.settings && state.settings.hook && state.settings.hook !== "local");
  }

  function showAlert(id) {
    if (!id) return;
    state.activeAlertId = id;
    AlertUI.renderList(state.alerts, id, showAlert);

    var local = state.alerts.filter(function (a) { return a.id === id; })[0];
    AlertUI.renderDetail(local || null, { pushed: isPushed(), evidence: (local && local.evidence) || [] });
    AlertUI.renderPhone(local || null, state.settings || {});

    api.getAlert(id).then(function (alert) {
      AlertUI.renderDetail(alert, { pushed: isPushed(), evidence: (local && local.evidence) || [] });
    }).catch(function (err) {
      toast("取告警失败：" + err.message);
    });
  }

  function doAck(action) {
    var id = state.activeAlertId;
    if (!id) { toast("先选一条告警"); return; }
    api.ackAlert(id, action, "").then(function (alert) {
      state.alerts = state.alerts.map(function (a) {
        return a.id === id ? Object.assign({}, a, alert || {}) : a;
      });
      store.saveAlerts(state.alerts);
      AlertUI.renderList(state.alerts, id, showAlert);
      AlertUI.renderDetail(alert, { pushed: isPushed(), evidence: [] });
      AlertUI.renderPhone(alert, state.settings || {});
      loopback("已记录处置：" + ((alert && alert.status) || action) + "（写回后端）");
    }).catch(function (err) {
      toast("处置失败：" + err.message);
    });
  }

  function loopback(text) {
    var box = $("loopback");
    if (!box) return;
    box.textContent = text;
    box.hidden = false;
    setTimeout(function () { box.hidden = true; }, 5000);
  }

  /* ---------------- 报告 ---------------- */

  function loadReport(sid) {
    var decisions = store.decisions(sid);
    var cached = store.cachedReport(sid);
    if (cached) ReportUI.render(cached, { decisions: decisions, sessionId: sid });

    api.getReport(sid).then(function (report) {
      store.cacheReport(sid, report);
      ReportUI.render(report, { decisions: decisions, sessionId: sid });
    }).catch(function (err) {
      ReportUI.render(null, {});
      toast("取报告失败：" + err.message);
    });
  }

  function finish() {
    var sid = state.sessionId;
    if (!state.turns.length) { toast("还没有对话"); return; }
    api.getReport(sid).then(function (report) {
      store.cacheReport(sid, report);
      ReportUI.render(report, { decisions: store.decisions(sid), sessionId: sid });
      location.hash = "#/report/" + encodeURIComponent(sid);
      loopback("报告已生成：固定在这一刻，不随之后的对话变化");
    }).catch(function (err) {
      toast("生成报告失败：" + err.message);
    });
  }

  /* ---------------- L3 覆盖层 ---------------- */

  function showL3(d) {
    var ovl = $("ovl");
    if (!ovl) return;
    ovl.hidden = false;

    if ($("ovlText")) {
      $("ovlText").textContent =
        "当前风险分 " + d.score + "（L3），命中剧本「" +
        ((d.script && d.script.name) || "未知") +
        "」。立即停止操作手机银行：不要转账、不要把验证码给别人。";
    }

    if ($("ovlVoice")) {
      var canSpeak = "speechSynthesis" in window;
      $("ovlVoice").textContent = canSpeak
        ? "正在语音播报（浏览器合成音）"
        : "这台机器不支持语音播报，已用文字替代";
      if (canSpeak) {
        try {
          var u = new SpeechSynthesisUtterance("检测到高风险诈骗，请立即停止转账，不要提供验证码。");
          u.lang = "zh-CN";
          window.speechSynthesis.speak(u);
        } catch (e) { /* 播报失败不影响判定 */ }
      }
    }
  }

  /* ---------------- 设置 ---------------- */

  function openSettings() {
    var s = state.settings || {};
    if ($("gName")) $("gName").value = s.name || "";
    if ($("gRel")) $("gRel").value = s.rel || "";
    if ($("gSecond")) $("gSecond").value = s.second || "";
    if ($("gHook")) $("gHook").value = s.hook || "local";
    if ($("setOvl")) $("setOvl").hidden = false;
  }

  function saveSettings() {
    state.settings = {
      name: ($("gName") || {}).value || "",
      rel: ($("gRel") || {}).value || "",
      second: ($("gSecond") || {}).value || "",
      hook: ($("gHook") || {}).value || "local"
    };
    store.saveSettings(state.settings);
    if ($("setOvl")) $("setOvl").hidden = true;
    var active = state.alerts.filter(function (a) { return a.id === state.activeAlertId; })[0] || null;
    AlertUI.renderPhone(active, state.settings);
    toast("已保存监护人设置（只存本地，不上传）");
  }

  /* ---------------- 概览 ---------------- */

  function renderOverview() {
    var h = state.health || {};
    var chips = [
      ["剧本", h.kb_scripts || "—"],
      ["案例", h.kb_cases || "—"],
      ["LLM", h.llm_enabled ? "已启用" : "未启用"],
      ["ASR", h.asr_enabled ? "已启用" : "未启用"],
      ["OCR", h.ocr_enabled ? "已启用" : "未启用"]
    ];
    var box = $("overview");
    if (!box) return;
    box.innerHTML = "";
    chips.forEach(function (c) {
      box.appendChild(el("span", "chip", c[0] + " " + c[1]));
    });
  }

  /* ---------------- 绑定 ---------------- */

  function bind() {
    if ($("role")) {
      $("role").addEventListener("change", function (e) {
        state.role = e.target.value;
        state.profile = Profile.blank(state.role);
        state.profileWhy = [];
        store.saveProfile(state.profile);
        Profile.render(state.profile, state.profileWhy);
        toast("角色已切到 " + e.target.value + "（只影响建议，不影响分数）");
      });
    }

    if ($("sendThem")) {
      $("sendThem").addEventListener("click", function () { send(($("input") || {}).value, "them"); });
    }
    if ($("sendMe")) {
      $("sendMe").addEventListener("click", function () { send(($("input") || {}).value, "me"); });
    }
    if ($("input")) {
      $("input").addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          send(e.target.value, "them");
        }
      });
    }

    if ($("undoBtn")) {
      $("undoBtn").addEventListener("click", function () {
        if (!state.turns.length) return;
        state.turns.pop();
        store.saveTurns(state.sessionId, state.turns);
        renderConvo();
        toast("已撤销最后一轮（不会撤回后端已产生的告警）");
      });
    }

    if ($("clearBtn")) {
      $("clearBtn").addEventListener("click", function () {
        state.turns = [];
        state.decisions = [];
        state.askedPending = null;
        state.askedCount = 0;
        state.sessionId = store.resetSession();
        store.saveTurns(state.sessionId, []);
        renderConvo();
        if ($("resultBox")) $("resultBox").hidden = true;
        if ($("emptyState")) $("emptyState").hidden = false;
        toast("已清空对话，换成新会话（旧告警还在）");
      });
    }

    Array.prototype.forEach.call(document.querySelectorAll("[data-preset]"), function (btn) {
      btn.addEventListener("click", function () {
        var preset = PRESETS[btn.getAttribute("data-preset")];
        if (!preset) return;
        state.turns = [];
        state.decisions = [];
        state.askedPending = null;
        store.saveTurns(state.sessionId, []);
        renderConvo();

        var i = 0;
        (function step() {
          if (i >= preset.turns.length) {
            toast("预设已灌入，点「结束对话 · 生成报告」可出报告");
            return;
          }
          var t = preset.turns[i++];
          send(t.text, t.role);
          setTimeout(step, 700);
        })();
      });
    });

    if ($("finishBtn")) $("finishBtn").addEventListener("click", finish);

    if ($("printBtn")) {
      $("printBtn").addEventListener("click", function () {
        if (parseHash().view !== "report") {
          location.hash = "#/report/" + encodeURIComponent(state.sessionId);
        }
        setTimeout(function () { window.print(); }, 250);
      });
    }
    if ($("backDetect")) {
      $("backDetect").addEventListener("click", function () { location.hash = "#/detect"; });
    }

    Array.prototype.forEach.call(document.querySelectorAll("button[data-ack]"), function (btn) {
      btn.addEventListener("click", function () { doAck(btn.getAttribute("data-ack")); });
    });

    if ($("settingsBtn")) $("settingsBtn").addEventListener("click", openSettings);
    if ($("setSave")) $("setSave").addEventListener("click", saveSettings);
    if ($("setClose")) {
      $("setClose").addEventListener("click", function () { if ($("setOvl")) $("setOvl").hidden = true; });
    }

    if ($("callVictim")) {
      $("callVictim").addEventListener("click", function () {
        var num = (state.settings && state.settings.second) || "";
        if (num) location.href = "tel:" + num;
        else toast("先到「设置」里填第二联系人号码");
      });
    }
    if ($("ackHere")) $("ackHere").addEventListener("click", function () { doAck("ack"); });

    if ($("ovlStop")) {
      $("ovlStop").addEventListener("click", function () {
        if ($("ovl")) $("ovl").hidden = true;
        if ("speechSynthesis" in window) window.speechSynthesis.cancel();
        doAck("ack");
      });
    }
    if ($("ovlToAlert")) {
      $("ovlToAlert").addEventListener("click", function () {
        if ($("ovl")) $("ovl").hidden = true;
        location.hash = "#/alert/" + encodeURIComponent(state.activeAlertId || "");
      });
    }

    if ($("profileToggle")) {
      $("profileToggle").addEventListener("click", function () {
        var card = $("profileCard");
        if (!card) return;
        card.classList.toggle("collapsed");
        $("profileToggle").textContent = card.classList.contains("collapsed") ? "展开" : "收起";
      });
    }

    window.addEventListener("hashchange", route);
  }

  /* ---------------- 启动 ---------------- */

  function boot() {
    state.sessionId = store.sessionId();
    state.turns = store.turns(state.sessionId);
    state.alerts = store.alerts();
    state.settings = store.settings();
    state.profile = store.profile() || Profile.blank(state.role);

    bind();
    renderConvo();
    Profile.render(state.profile, state.profileWhy);
    AlertUI.renderList(state.alerts, "", showAlert);
    AlertUI.renderPhone(null, state.settings);
    renderOverview();
    route();

    api.health().then(function (h) {
      state.health = h;
      renderOverview();
    }).catch(function () {
      toast("后端没连上：先跑 scripts/start.ps1 或 uvicorn");
    });

    api.listScripts().then(function (data) {
      (data.scripts || []).forEach(function (s) { state.scripts[s.id] = s; });
    }).catch(function () {
      /* 只有阶段条会退化，不影响主流程 */
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window);
