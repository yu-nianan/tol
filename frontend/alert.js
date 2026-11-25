/* 告警页：列表（前端累积）、详情（证据链 + 处置状态）、监护人手机（演示）。
 *
 * 两处降级，UI 上必须如实标出来，不许假装：
 *  ① 后端没有告警列表接口 → 列表来自本会话 sessionStorage，刷新后仍在、换会话即空；
 *  ② 后端 Alert 没有"已读"字段、也没有真实 webhook → 只显示「已推送 / 已介入」两态，
 *     未配置通道时标「未推送（降级）」，按钮置灰并注明"预览"。
 */
(function (global) {
  "use strict";

  var LEVEL_TEXT = ["L0 无风险", "L1 提醒", "L2 警告", "L3 紧急"];
  var STATUS_TEXT = {
    open: "待处置",
    acked: "已处置",
    acknowledged: "已处置",
    dismissed: "已忽略",
    confirmed_false_positive: "确认为误报"
  };

  function levelClass(level) {
    return ["l0", "l1", "l2", "l3"][Math.max(0, Math.min(3, level | 0))];
  }

  function fmtTime(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    function p(n) { return n < 10 ? "0" + n : "" + n; }
    return p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderList(list, activeId, onPick) {
    var box = document.getElementById("alertList");
    if (!box) return;
    box.innerHTML = "";

    var meta = document.getElementById("alertMeta");
    if (meta) {
      meta.textContent = list.length
        ? "共 " + list.length + " 条 · 同会话跨档会自动新建一条"
        : "同会话跨档会自动新建一条";
    }

    if (!list.length) {
      box.appendChild(el("li", "hint", "本次会话还没有告警。"));
      return;
    }

    list.slice().reverse().forEach(function (a) {
      var item = el("li", "alert-item" + (a.id === activeId ? " on" : ""));
      item.style.borderLeftColor = "var(--" + levelClass(a.level) + ")";

      var t = el("div", "t");
      var badge = el("span", "badge", "L" + (a.level | 0));
      badge.style.background = "var(--" + levelClass(a.level) + ")";
      t.appendChild(badge);
      t.appendChild(el("span", "", a.script_name || "可疑对话"));
      t.appendChild(el("span", "hint", (a.score || 0) + " 分"));

      var s = el("div", "s", fmtTime(a.created_at) + " · " + (STATUS_TEXT[a.status] || a.status || "待处置"));
      item.appendChild(t);
      item.appendChild(s);
      item.addEventListener("click", function () { onPick(a.id); });
      box.appendChild(item);
    });
  }

  function renderSteps(alert, pushed) {
    var box = document.getElementById("alertSteps");
    if (!box) return;
    box.innerHTML = "";

    var done = alert && alert.status && alert.status !== "open";

    var s1 = el("div", "step" + (pushed ? " on" : " warn"));
    s1.textContent = pushed ? "已推送监护人" : "未推送（降级）";
    box.appendChild(s1);

    var s2 = el("div", "step" + (done ? " on" : ""));
    s2.textContent = done ? "已介入" : "等待介入";
    box.appendChild(s2);

    var s3 = el("div", "step");
    s3.textContent = done ? "已结案" : "未结案";
    box.appendChild(s3);
  }

  function renderDetail(alert, ctx) {
    var empty = document.getElementById("alertEmpty");
    var body = document.getElementById("alertBody");
    if (!alert || !alert.id) {
      if (empty) empty.hidden = false;
      if (body) body.hidden = true;
      return;
    }
    if (empty) empty.hidden = true;
    if (body) body.hidden = false;

    var badge = document.getElementById("detailBadge");
    if (badge) {
      badge.textContent = "L" + (alert.level | 0);
      badge.style.background = "var(--" + levelClass(alert.level) + ")";
    }
    var score = document.getElementById("detailScore");
    if (score) score.textContent = alert.score || 0;
    var script = document.getElementById("detailScript");
    if (script) script.textContent = (alert.script_name || "") + " · " + fmtTime(alert.created_at);

    var evBox = document.getElementById("detailEvidence");
    if (evBox) {
      evBox.innerHTML = "";
      var list = (alert.evidence || ctx.evidence || []);
      if (!list.length) {
        evBox.appendChild(el("li", "hint", "这条告警没有留存证据（后端 Alert 不存 evidence，来自发起检测时的快照）。"));
      }
      list.forEach(function (ev) {
        var item = el("li", "ev" + (ev.kind === "context" ? " ctx" : ""));
        item.appendChild(el("div", "label", ev.label || ev.code || "证据"));
        item.appendChild(el("div", "quote", "「" + (ev.text || "") + "」"));
        var sub = "置信度 " + Math.round((ev.confidence || 0) * 100) + "% · 权重 " + (ev.weight || 0);
        if (ev.turn) sub += " · 第 " + ev.turn + " 轮";
        if (ev.speaker) sub += " · " + ev.speaker;
        item.appendChild(el("div", "sub", sub));
        evBox.appendChild(item);
      });
    }

    renderSteps(alert, ctx.pushed);

    var ackState = document.getElementById("ackState");
    if (ackState) {
      ackState.textContent = alert.status && alert.status !== "open"
        ? "已记录处置：" + (STATUS_TEXT[alert.status] || alert.status)
        : "还没处置。处置会写回后端（POST /alerts/{id}/ack）。";
    }

    var row = document.getElementById("feedbackRow");
    if (row) {
      Array.prototype.forEach.call(row.querySelectorAll("button[data-ack]"), function (btn) {
        btn.disabled = !!(alert.status && alert.status !== "open");
      });
    }
  }

  function renderPhone(alert, settings) {
    var chat = document.getElementById("guardianChat");
    var who = document.getElementById("phoneWho");
    var hint = document.getElementById("phoneHint");
    if (!chat) return;

    var name = settings.name || "（未设置）";
    if (who) who.textContent = name + (settings.rel ? " · " + settings.rel : "");

    chat.innerHTML = "";
    if (!alert) {
      chat.appendChild(el("div", "gmsg", "（还没有推送。先在检测页跑出一段 L2 以上的对话。）"));
      return;
    }

    var msg = el("div", "gmsg");
    msg.appendChild(el("div", "", "【反诈预警】" + name + "，系统检测到家人可能正在被" + (alert.script_name || "诈骗") + "，当前风险 " + (alert.score || 0) + " 分（L" + (alert.level | 0) + "）。"));
    msg.appendChild(el("div", "", "建议立刻打电话确认，不要让他/她继续操作手机银行。"));
    msg.appendChild(el("span", "t", fmtTime(alert.created_at) + " · 通道：" + (settings.hook === "local" ? "本地预览（未接 webhook）" : settings.hook)));
    chat.appendChild(msg);

    if (alert.status && alert.status !== "open") {
      chat.appendChild(el("div", "gmsg sys", "监护人已回执：" + (STATUS_TEXT[alert.status] || alert.status)));
    }

    if (hint) {
      hint.textContent = settings.hook === "local"
        ? "当前是本地预览：不会真的发出去，按钮置灰标「预览」。"
        : "已配置推送通道：" + settings.hook + "（演示环境仍需后端 webhook 支持）。";
    }

    var disabled = settings.hook === "local";
    ["callVictim", "ackHere"].forEach(function (id) {
      var b = document.getElementById(id);
      if (b) b.disabled = disabled;
    });
  }

  global.AlertUI = {
    LEVEL_TEXT: LEVEL_TEXT,
    levelClass: levelClass,
    fmtTime: fmtTime,
    renderList: renderList,
    renderDetail: renderDetail,
    renderPhone: renderPhone
  };
})(window);
