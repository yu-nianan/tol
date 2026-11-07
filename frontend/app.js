/* 反诈智能助手 · 三屏演示（原生 JS，无构建、无依赖、无 CDN）
 *
 * 路由（hash）：
 *   #/detect              检测页（默认）
 *   #/alert/<alert_id>    告警页
 *   #/report/<session_id> 报告页
 *
 * 接口（同源相对路径，不写死 host/port）：
 *   POST /api/v1/detect/text
 *   GET  /api/v1/alerts/{alert_id}
 *   POST /api/v1/alerts/{alert_id}/ack
 *   GET  /api/v1/report/{session_id}
 *
 * 注意：app/api/web.py 的 GET / 只返回 frontend/index.html，没有静态文件路由，
 *       所以 index.html 内联了本文件与 style.css 的同一份代码，保证打开即可用。
 *       本文件是可读源文件，修改后需重新内联（见回执「下次接手要知道什么」）。
 */
(function () {
  "use strict";

  var API = "/api/v1";
  var LEVELS = [
    { label: "L0 仅记录", cls: "lv0" },
    { label: "L1 提醒", cls: "lv1" },
    { label: "L2 警告", cls: "lv2" },
    { label: "L3 紧急", cls: "lv3" }
  ];
  var ROLES = {
    normal: "普通用户",
    elder: "老年人",
    child: "儿童",
    student: "学生",
    finance: "财务人员"
  };
  var STATUS = { open: "待处理", acked: "已介入", dismissed: "已忽略" };
  // 预设文本改写自 data/samples/*.txt，已脱敏（无真实号码/姓名）
  var PRESETS = {
    normal: "明天下午三点在图书馆三楼讨论，记得带笔记本和充电器。",
    authority:
      "您好，我是市局经侦支队的，你的银行卡涉嫌洗钱，现在需要你配合资金审查，" +
      "不要告诉任何人，把存款转到我们的安全账户，半小时内完成，否则后果自负。",
    service:
      "亲，您的订单异常，我们可以双倍退款，请打开屏幕共享，我远程协助您操作银行APP，" +
      "并把收到的验证码发给我，马上就能到账。"
  };

  var app = document.getElementById("app");

  /* ---------------- 基础工具 ---------------- */
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmt(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) return "";
    return n.toFixed(digits == null ? 1 : digits);
  }

  function pct(value) {
    var n = Number(value);
    return isFinite(n) ? Math.round(n * 100) + "%" : "—";
  }

  function levelMeta(level) {
    return LEVELS[Number(level)] || LEVELS[0];
  }

  function levelBadge(level) {
    var meta = levelMeta(level);
    return '<span class="badge ' + meta.cls + '">' + esc(meta.label) + "</span>";
  }

  function statusMeta(status) {
    return STATUS[String(status)] || String(status || "—");
  }

  function statusClass(status) {
    if (status === "acked") return "ok";
    if (status === "dismissed") return "muted";
    return "warn";
  }

  function setTitle(suffix) {
    document.title = "反诈智能助手 · " + suffix;
  }

  /* ---------------- 会话（刷新后仍能拿到本次证据） ---------------- */
  function sessionId() {
    var key = "tol_session_id";
    var id = "";
    try {
      id = window.sessionStorage.getItem(key) || "";
    } catch (err) {
      id = "";
    }
    if (!id) {
      var rand = "";
      try {
        if (window.crypto && window.crypto.randomUUID) {
          rand = window.crypto.randomUUID().replace(/-/g, "").slice(0, 12);
        }
      } catch (err) {
        rand = "";
      }
      if (!rand) rand = String(Date.now()).slice(-8) + Math.random().toString(36).slice(2, 6);
      id = "demo-" + rand;
      try {
        window.sessionStorage.setItem(key, id);
      } catch (err) {
        /* 隐身模式禁用 storage 时退化为内存值，不阻断演示 */
      }
    }
    return id;
  }

  function storeResult(data) {
    try {
      window.sessionStorage.setItem("tol_last_result", JSON.stringify(data));
    } catch (err) {
      /* 同上：存不下就不存，页面仍可展示本次结果 */
    }
  }

  function loadResult(sessionIdValue) {
    try {
      var raw = window.sessionStorage.getItem("tol_last_result");
      if (!raw) return null;
      var data = JSON.parse(raw);
      if (data && data.session_id === sessionIdValue) return data;
      return null;
    } catch (err) {
      return null;
    }
  }

  /* ---------------- HTTP（同源相对路径） ---------------- */
  function request(url, options) {
    return fetch(url, options).then(function (resp) {
      return resp.text().then(function (text) {
        var data = null;
        if (text) {
          try {
            data = JSON.parse(text);
          } catch (err) {
            data = null;
          }
        }
        if (!resp.ok) {
          var code = data && data.error && data.error.code ? data.error.code : "http_" + resp.status;
          var message =
            data && data.error && data.error.message
              ? data.error.message
              : data && data.detail
                ? String(data.detail)
                : "请求失败（HTTP " + resp.status + "）";
          var error = new Error(message);
          error.code = code;
          error.status = resp.status;
          throw error;
        }
        return data || {};
      });
    });
  }

  function get(url) {
    return request(url, { method: "GET" });
  }

  function post(url, body) {
    return request(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
  }

  /* ---------------- 通用片段 ---------------- */
  function loadingBox(text) {
    return '<div class="card muted center">' + esc(text) + "</div>";
  }

  function errorBox(text) {
    return '<div class="card error"><p>' + esc(text) + "</p></div>";
  }

  var toastTimer = null;
  function toast(message) {
    var el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.hidden = false;
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      el.hidden = true;
    }, 3200);
  }

  function evidenceList(list) {
    if (!list || !list.length) {
      return '<p class="muted empty">本次没有可展示的证据（例如未命中规则，或会话证据在服务重启后丢失）。</p>';
    }
    var html = ['<ul class="ev-list">'];
    list.forEach(function (ev) {
      html.push('<li class="ev">');
      html.push(
        '<div class="ev-head"><strong>' +
          esc(ev.label || ev.code || "证据") +
          '</strong><span class="ev-code">' +
          esc(ev.code || "") +
          "</span></div>"
      );
      if (ev.text) html.push('<p class="ev-text">「' + esc(ev.text) + "」</p>");
      var bits = [];
      if (ev.weight != null) bits.push("权重 " + fmt(ev.weight, 2));
      if (ev.confidence != null) bits.push("置信度 " + pct(ev.confidence));
      if (ev.kind) bits.push("来源 " + esc(ev.kind));
      if (ev.modality) bits.push("模态 " + esc(ev.modality));
      if (bits.length) html.push('<div class="ev-meta">' + bits.join(" · ") + "</div>");
      html.push("</li>");
    });
    html.push("</ul>");
    return html.join("");
  }

  function renderError(title, err, tip, backHref) {
    app.innerHTML = [
      '<section class="screen-head"><h2>' + esc(title) + "</h2></section>",
      '<div class="card error">',
      "<p><strong>" + esc((err && err.message) || "未知错误") + "</strong></p>",
      err && err.code ? '<p class="muted">错误码：<code>' + esc(err.code) + "</code></p>" : "",
      tip ? '<p class="muted">' + esc(tip) + "</p>" : "",
      '<a class="btn ghost" href="' + esc(backHref || "#/detect") + '">返回检测页</a>',
      "</div>"
    ].join("");
  }

  /* ---------------- 检测页 ---------------- */
  function renderDetect() {
    app.innerHTML = [
      '<section class="screen-head">',
      "<h2>① 检测</h2>",
      '<p class="lede">粘贴一条可疑短信、聊天记录或录音转写。角色会改变阈值：同一句话，老人 / 儿童比普通用户更早触发告警。</p>',
      "</section>",
      '<div class="card">',
      '<label class="field-label" for="text">可疑内容</label>',
      '<textarea id="text" maxlength="4000" rows="6" placeholder="例：您好，我是市局经侦支队的，你的银行卡涉嫌洗钱……"></textarea>',
      '<div class="row row-between">',
      '<label class="field">角色',
      '<select id="role">',
      '<option value="normal">普通用户</option>',
      '<option value="elder">老年人（阈值更低）</option>',
      '<option value="child">儿童（阈值更低）</option>',
      '<option value="student">学生</option>',
      '<option value="finance">财务人员（阈值更高）</option>',
      "</select>",
      "</label>",
      '<button id="detect" class="btn primary" type="button">检测</button>',
      "</div>",
      '<div class="presets">',
      '<span class="muted">预设文本：</span>',
      '<button class="btn ghost" type="button" data-preset="normal">正常消息</button>',
      '<button class="btn ghost" type="button" data-preset="authority">冒充公检法</button>',
      '<button class="btn ghost" type="button" data-preset="service">客服退款</button>',
      "</div>",
      '<p class="muted" id="hint">当前会话：<code>' +
        esc(sessionId()) +
        "</code> · 预设文本来自 data/samples，已脱敏</p>",
      "</div>",
      '<div id="result"></div>',
      '<p class="hint-line">提示：L0 只记录、不告警；L1 起进入告警页；L3 会触发监护人通报（未配置 webhook 时如实记为 skipped）。</p>'
    ].join("");

    var text = document.getElementById("text");
    var role = document.getElementById("role");
    var detectBtn = document.getElementById("detect");
    var result = document.getElementById("result");
    var hint = document.getElementById("hint");

    Array.prototype.forEach.call(document.querySelectorAll("[data-preset]"), function (btn) {
      btn.addEventListener("click", function () {
        text.value = PRESETS[btn.getAttribute("data-preset")] || "";
        hint.innerHTML = "已填入「" + esc(btn.textContent) + "」预设，点「检测」查看结果。";
        text.focus();
      });
    });

    detectBtn.addEventListener("click", function () {
      var value = (text.value || "").trim();
      if (!value) {
        result.innerHTML = errorBox("先粘贴一段内容，或点上面的预设按钮。");
        text.focus();
        return;
      }
      detectBtn.disabled = true;
      detectBtn.textContent = "检测中…";
      result.innerHTML = loadingBox("正在判定，通常 1 秒内返回…");
      post(API + "/detect/text", { text: value, session_id: sessionId(), role: role.value })
        .then(function (data) {
          storeResult(data);
          if (data && data.alert && data.alert.id) {
            window.location.hash = "#/alert/" + encodeURIComponent(data.alert.id);
            return;
          }
          renderDetectResult(data, role.value);
        })
        .catch(function (err) {
          result.innerHTML = errorBox(
            "检测失败：" + err.message + (err.code ? "（" + err.code + "）" : "")
          );
        })
        .then(function () {
          detectBtn.disabled = false;
          detectBtn.textContent = "检测";
        });
    });
  }

  function renderDetectResult(data, role) {
    var result = document.getElementById("result");
    if (!result) return;
    var decision = (data && data.decision) || {};
    var level = Number(decision.level || 0);
    var meta = levelMeta(level);
    var script = decision.script;
    var reasons = decision.reasons || [];
    var evidence = decision.evidence || [];
    var parts = [];

    parts.push('<div class="card result-card">');
    parts.push('<div class="result-head">');
    parts.push('<div class="score">' + fmt(decision.score) + "<span>分</span></div>");
    parts.push('<div class="result-level">' + levelBadge(level) + "</div>");
    parts.push("</div>");
    parts.push(
      '<p class="muted">角色：' +
        esc(ROLES[role] || role) +
        " · 会话：<code>" +
        esc(data.session_id) +
        "</code> · 耗时 " +
        fmt(data.latency_ms, 0) +
        " ms</p>"
    );

    if (level < 1) {
      parts.push(
        '<div class="notice">本次判定为 <strong>L0 仅记录</strong>：未达到告警门槛，系统只记录、不生成告警（不会编造告警）。证据已写入本会话，可直接生成报告。</div>'
      );
    } else {
      parts.push(
        '<div class="notice warn">本次判定为 <strong>' +
          esc(meta.label) +
          "</strong>，但接口没有返回告警对象；请检查后端日志。</div>"
      );
    }

    if (script) {
      parts.push(
        '<p class="script-line">命中剧本：<strong>' +
          esc(script.name) +
          "</strong> · " +
          esc(script.stage_label || "") +
          "</p>"
      );
    } else {
      parts.push('<p class="script-line muted">未命中具体剧本，本次按通用话术规则定级。</p>');
    }

    if (reasons.length) {
      parts.push('<h3 class="sub">判定理由</h3><ul class="reasons">');
      reasons.forEach(function (reason) {
        parts.push("<li>" + esc(reason) + "</li>");
      });
      parts.push("</ul>");
    }

    parts.push('<h3 class="sub">证据（' + evidence.length + " 条）</h3>");
    parts.push(evidenceList(evidence.slice(0, 8)));
    parts.push('<div class="row">');
    parts.push('<button class="btn secondary" id="toReport" type="button">查看 / 生成报告</button>');
    parts.push('<button class="btn ghost" id="again" type="button">再检测一次</button>');
    parts.push("</div>");
    parts.push("</div>");
    result.innerHTML = parts.join("");

    var toReport = document.getElementById("toReport");
    var again = document.getElementById("again");
    if (toReport) {
      toReport.addEventListener("click", function () {
        window.location.hash = "#/report/" + encodeURIComponent(data.session_id);
      });
    }
    if (again) {
      again.addEventListener("click", function () {
        window.scrollTo(0, 0);
        var target = document.getElementById("text");
        if (target) target.focus();
      });
    }
  }

  /* ---------------- 告警页 ---------------- */
  function renderAlert(alertId) {
    app.innerHTML = loadingBox("正在加载告警 " + alertId + "…");
    get(API + "/alerts/" + encodeURIComponent(alertId))
      .then(function (alert) {
        var cached = loadResult(alert.session_id);
        var evidence = cached && cached.decision ? cached.decision.evidence || [] : [];
        if (evidence.length) {
          return { alert: alert, cached: cached, evidence: evidence };
        }
        return get(API + "/report/" + encodeURIComponent(alert.session_id))
          .then(function (payload) {
            var report = payload.report || {};
            return { alert: alert, cached: cached, evidence: report.evidence_chain || [] };
          })
          .catch(function () {
            // 报告拿不到就只展示告警元信息，不编证据
            return { alert: alert, cached: cached, evidence: [] };
          });
      })
      .then(function (ctx) {
        paintAlert(ctx);
      })
      .catch(function (err) {
        renderError(
          "打不开这条告警",
          err,
          err.code === "alert_not_found"
            ? "告警存在服务进程内存里，重启服务后会丢失；回检测页重新检测一次即可。"
            : "",
          "#/detect"
        );
      });
  }

  function paintAlert(ctx) {
    var alert = (ctx && ctx.alert) || {};
    var cached = ctx.cached || null;
    var decision = (cached && cached.decision) || {};
    var evidence = ctx.evidence || [];
    var level = Number(alert.level || 0);
    var meta = levelMeta(level);
    var scriptName = alert.script_name || (decision.script && decision.script.name) || "";
    var stageLabel =
      decision.script && decision.script.stage_label ? decision.script.stage_label : "";
    var scriptLine = scriptName
      ? esc(scriptName) + (stageLabel ? " · " + esc(stageLabel) : "")
      : "未命中具体剧本";
    var reasons = decision.reasons || [];
    var parts = [];

    parts.push(
      '<section class="screen-head"><h2>② 告警</h2><p class="lede">色条对应等级：L0 灰 / L1 蓝 / L2 橙 / L3 红。点「我已介入」会把家长确认状态回写给后端。</p></section>'
    );
    parts.push('<div class="levelbar ' + meta.cls + '">');
    parts.push(
      '<div class="levelbar-main"><span class="levelbar-level">' +
        esc(meta.label) +
        '</span><span class="levelbar-script">' +
        scriptLine +
        "</span></div>"
    );
    parts.push(
      '<div class="levelbar-score">' + fmt(alert.score) + "<span>分</span></div>"
    );
    parts.push("</div>");

    parts.push('<div class="card">');
    parts.push('<div class="kv"><span>告警 ID</span><div><code>' + esc(alert.id) + "</code></div></div>");
    parts.push(
      '<div class="kv"><span>会话</span><div><code>' + esc(alert.session_id) + "</code></div></div>"
    );
    parts.push('<div class="kv"><span>时间</span><div>' + esc(alert.created_at || "—") + "</div></div>");
    parts.push(
      '<div class="kv"><span>状态</span><div><span id="alertStatus" class="pill ' +
        statusClass(alert.status) +
        '">' +
        esc(statusMeta(alert.status)) +
        "</span></div></div>"
    );
    parts.push('<div class="row action-row">');
    parts.push('<button class="btn primary" id="ack" type="button">我已介入</button>');
    parts.push('<button class="btn ghost" id="dismiss" type="button">误报，忽略</button>');
    parts.push('<button class="btn secondary" id="toReport" type="button">生成报告</button>');
    parts.push("</div>");
    parts.push("</div>");

    parts.push(
      '<section class="card"><h3>证据链（名称 + 原文 + 置信度）</h3>' +
        evidenceList(evidence) +
        "</section>"
    );

    if (reasons.length) {
      parts.push('<section class="card"><h3>判定理由</h3><ul class="reasons">');
      reasons.forEach(function (reason) {
        parts.push("<li>" + esc(reason) + "</li>");
      });
      parts.push("</ul></section>");
    }
    app.innerHTML = parts.join("");

    var ackBtn = document.getElementById("ack");
    var dismissBtn = document.getElementById("dismiss");
    var reportBtn = document.getElementById("toReport");

    function syncButtons() {
      var open = alert.status === "open";
      if (ackBtn) {
        ackBtn.disabled = !open;
        ackBtn.textContent = alert.status === "acked" ? "已介入 ✓" : "我已介入";
      }
      if (dismissBtn) {
        dismissBtn.disabled = !open;
        dismissBtn.textContent = alert.status === "dismissed" ? "已忽略 ✓" : "误报，忽略";
      }
    }

    function applyStatus(updated) {
      alert.status = String((updated && updated.status) || alert.status);
      var pill = document.getElementById("alertStatus");
      if (pill) {
        pill.className = "pill " + statusClass(alert.status);
        pill.textContent = statusMeta(alert.status);
      }
      syncButtons();
    }

    function sendAck(action, label) {
      if (ackBtn) ackBtn.disabled = true;
      if (dismissBtn) dismissBtn.disabled = true;
      post(API + "/alerts/" + encodeURIComponent(alert.id) + "/ack", { action: action })
        .then(function (updated) {
          applyStatus(updated);
          toast("已回写：" + label + "（status=" + alert.status + "）");
        })
        .catch(function (err) {
          toast("回写失败：" + err.message);
          syncButtons();
        });
    }

    if (ackBtn) {
      ackBtn.addEventListener("click", function () {
        sendAck("ack", "家长确认已介入");
      });
    }
    if (dismissBtn) {
      dismissBtn.addEventListener("click", function () {
        sendAck("dismiss", "标记为误报");
      });
    }
    if (reportBtn) {
      reportBtn.addEventListener("click", function () {
        window.location.hash = "#/report/" + encodeURIComponent(alert.session_id);
      });
    }
    syncButtons();
  }

  /* ---------------- 报告页 ---------------- */
  function renderReport(sessionIdValue) {
    app.innerHTML = loadingBox("正在生成报告…");
    get(API + "/report/" + encodeURIComponent(sessionIdValue))
      .then(function (payload) {
        paintReport(payload.report || {}, sessionIdValue);
      })
      .catch(function (err) {
        renderError(
          "打不开这份报告",
          err,
          err.code === "session_not_found"
            ? "该会话还没有检测记录：先回检测页跑一次，或从告警页点「生成报告」。"
            : "",
          "#/detect"
        );
      });
  }

  function paintReport(report, sessionIdValue) {
    var rs = report.risk_summary || {};
    var level = Number(rs.level || 0);
    var parts = [];

    parts.push(
      '<section class="screen-head no-print"><h2>③ 报告</h2><p class="lede">五段式安全监测报告：风险概述 / 证据链 / 剧本匹配 / 处置建议 / 通报记录。可直接用浏览器「打印 → 另存为 PDF」导出。</p></section>'
    );

    parts.push('<div class="report-head card">');
    parts.push('<h3 class="report-title">安全监测报告</h3>');
    parts.push(
      '<p class="muted">会话 <code>' +
        esc(report.session_id || sessionIdValue) +
        "</code> · 生成于 " +
        esc(report.generated_at || "—") +
        " · 轮数 " +
        esc(report.turns != null ? report.turns : "—") +
        "</p>"
    );
    parts.push('<div class="row no-print">');
    parts.push('<button class="btn primary" id="printReport" type="button">打印 / 导出 PDF</button>');
    parts.push('<a class="btn ghost" href="#/detect">返回检测</a>');
    parts.push("</div>");
    parts.push("</div>");

    // ① 风险概述
    parts.push('<section class="card"><h3>① 风险概述</h3>');
    parts.push(
      '<div class="kv"><span>风险分</span><div><strong class="big">' +
        (rs.score != null ? fmt(rs.score) : "—") +
        "</strong> 分</div></div>"
    );
    if (rs.level != null) {
      parts.push(
        '<div class="kv"><span>等级</span><div>' + levelBadge(level) + "</div></div>"
      );
    }
    if (rs.script) {
      parts.push(
        '<div class="kv"><span>命中剧本</span><div>' +
          esc(rs.script) +
          (rs.stage ? " · " + esc(rs.stage) : "") +
          "</div></div>"
      );
    }
    parts.push(
      '<div class="kv"><span>需人工介入</span><div>' +
        (rs.need_human ? "是：L2 及以上建议人工复核" : "否") +
        "</div></div>"
    );
    parts.push(
      '<div class="kv"><span>分数封顶</span><div>' +
        (rs.cap_applied ? "已封顶：无剧本/案例证据时最高 60 分" : "未触发") +
        "</div></div>"
    );
    if (rs.modalities && rs.modalities.length) {
      parts.push(
        '<div class="kv"><span>涉及模态</span><div>' + esc(rs.modalities.join(" / ")) + "</div></div>"
      );
    }
    if (rs.text_count != null) {
      parts.push(
        '<div class="kv"><span>文本 / 轮数</span><div>' +
          esc(rs.text_count) +
          " 条 / " +
          esc(rs.turns != null ? rs.turns : report.turns) +
          " 轮</div></div>"
      );
    }
    parts.push("</section>");

    // ② 证据链
    parts.push(
      '<section class="card"><h3>② 证据链</h3>' +
        evidenceList(report.evidence_chain || []) +
        "</section>"
    );

    // ③ 剧本匹配
    var sm = report.script_match || {};
    parts.push('<section class="card"><h3>③ 剧本匹配</h3>');
    if (sm.name) {
      parts.push(
        '<div class="kv"><span>剧本</span><div><strong>' +
          esc(sm.name) +
          '</strong> <span class="muted">(' +
          esc(sm.script_id || "") +
          ")</span></div></div>"
      );
      parts.push(
        '<div class="kv"><span>阶段</span><div>' +
          esc(sm.stage_label || sm.stage_name || "—") +
          "</div></div>"
      );
      if (sm.stage_weight != null) {
        parts.push(
          '<div class="kv"><span>阶段权重</span><div>' + fmt(sm.stage_weight, 3) + "</div></div>"
        );
      }
      var signals = sm.matched_signals || [];
      if (signals.length) {
        parts.push('<div class="kv"><span>命中信号</span><div class="chips">');
        signals.forEach(function (signal) {
          parts.push('<span class="chip">' + esc(signal) + "</span>");
        });
        parts.push("</div></div>");
      }
    } else {
      parts.push(
        '<p class="muted empty">未命中具体剧本：本会话按通用话术规则定级，不强行编造剧本。</p>'
      );
    }
    parts.push("</section>");

    // ④ 处置建议
    var advice = report.advice || [];
    parts.push('<section class="card"><h3>④ 处置建议</h3>');
    if (advice.length) {
      parts.push('<ol class="advice">');
      advice.forEach(function (item) {
        parts.push("<li>" + esc(item) + "</li>");
      });
      parts.push("</ol>");
    } else {
      parts.push('<p class="muted empty">暂无建议。</p>');
    }
    parts.push("</section>");

    // ⑤ 通报记录
    var notifications = report.notifications || [];
    parts.push('<section class="card"><h3>⑤ 通报记录</h3>');
    if (notifications.length) {
      parts.push('<ul class="notif-list">');
      notifications.forEach(function (note) {
        parts.push("<li>" + notifText(note) + "</li>");
      });
      parts.push("</ul>");
    } else {
      parts.push(
        '<p class="muted empty">本会话未触发监护人通报。只有 L3 紧急级会推送；未配置 GUARDIAN_WEBHOOK 时系统会如实记录 skipped，不会假装已发送。</p>'
      );
    }
    parts.push("</section>");

    parts.push(
      '<p class="disclaimer">' +
        esc(report.disclaimer || "本报告由原型系统自动生成，仅用于演练与教学，不构成法律意见。") +
        "</p>"
    );

    app.innerHTML = parts.join("");
    var printBtn = document.getElementById("printReport");
    if (printBtn) {
      printBtn.addEventListener("click", function () {
        window.print();
      });
    }
  }

  function notifText(note) {
    var n = note || {};
    if (n.event === "ack") {
      return [
        '<span class="pill ok">家长确认</span>',
        "alert=" + esc(n.alert_id),
        "action=" + esc(n.action),
        "status=" + esc(n.status || "acked")
      ].join(" · ");
    }
    // event === "notify"：{status, sent, channels:[{channel,status,ok,note,summary}]}
    var head = [];
    head.push(
      '<span class="pill ' +
        (n.sent ? "ok" : "warn") +
        '">' +
        (n.sent ? "已推送" : "未推送（降级）") +
        "</span>"
    );
    if (n.level_label) head.push(esc(n.level_label));
    if (n.alert_id) head.push("alert=" + esc(n.alert_id));
    var html = '<div class="notif-head">' + head.join(" · ") + "</div>";
    var channels = n.channels || [];
    if (channels.length) {
      html += '<div class="chips">';
      channels.forEach(function (c) {
        var label = (c.channel || "unknown") + "=" + (c.status || "unknown");
        if (c.ok != null) label += "（" + (c.ok ? "已送达" : "未送达") + "）";
        if (c.summary) label += "：" + c.summary;
        if (c.note) label += "：" + c.note;
        html += '<span class="chip">' + esc(label) + "</span>";
      });
      html += "</div>";
    }
    return html;
  }

  /* ---------------- 路由 ---------------- */
  function parseRoute() {
    var raw = (window.location.hash || "").replace(/^#\/?/, "");
    if (!raw) return { name: "detect", arg: "" };
    var cut = raw.indexOf("/");
    if (cut < 0) return { name: raw, arg: "" };
    return { name: raw.slice(0, cut), arg: decodeURIComponent(raw.slice(cut + 1)) };
  }

  function route() {
    var parsed = parseRoute();
    window.scrollTo(0, 0);
    if (parsed.name === "alert" && parsed.arg) {
      setTitle("告警");
      renderAlert(parsed.arg);
      return;
    }
    if (parsed.name === "report" && parsed.arg) {
      setTitle("报告");
      renderReport(parsed.arg);
      return;
    }
    if (parsed.name === "detect" || parsed.name === "") {
      setTitle("检测");
      renderDetect();
      return;
    }
    renderError("页面不存在", { message: "未知路由 #" + parsed.name, code: "bad_route" }, "", "#/detect");
  }

  window.addEventListener("hashchange", route);

  if (!window.location.hash) {
    try {
      window.history.replaceState(null, "", "#/detect");
    } catch (err) {
      /* file:// 等环境可能禁用 replaceState，直接渲染即可 */
    }
  }
  route();
})();
