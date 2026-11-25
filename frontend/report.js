/* 报告页：五段正文 + 逐轮曲线 + 维度图 + 打印。
 *
 * 后端 report 只给五段文本（risk_summary / evidence_chain / script_match /
 * advice / notifications），没有逐轮分数与维度 —— 这两张图由前端用本次会话
 * 累积的 decisions 画，属于前端补充，页面上注明来源。
 */
(function (global) {
  "use strict";

  var SECTIONS = [
    { key: "risk_summary", title: "风险摘要" },
    { key: "evidence_chain", title: "证据链" },
    { key: "script_match", title: "剧本匹配" },
    { key: "advice", title: "处置建议" },
    { key: "notifications", title: "通知记录" }
  ];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function isPlainObject(v) {
    return v && typeof v === "object" && !Array.isArray(v);
  }

  function paintValue(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (Array.isArray(value)) return value.map(paintValue).join("；");
    if (isPlainObject(value)) {
      return Object.keys(value).map(function (k) {
        return k + "：" + paintValue(value[k]);
      }).join(" · ");
    }
    return String(value);
  }

  function sectionBody(value) {
    var wrap = document.createDocumentFragment();

    if (value === null || value === undefined || value === "" ||
        (Array.isArray(value) && !value.length)) {
      wrap.appendChild(el("p", "hint", "（后端这一项为空）"));
      return wrap;
    }

    if (typeof value === "string") {
      value.split(/\n+/).forEach(function (line) {
        if (line.trim()) wrap.appendChild(el("p", "", line.trim()));
      });
      return wrap;
    }

    if (Array.isArray(value)) {
      var ul = el("ul");
      value.forEach(function (item) {
        ul.appendChild(el("li", "", paintValue(item)));
      });
      wrap.appendChild(ul);
      return wrap;
    }

    if (isPlainObject(value)) {
      var kv = el("div", "kv");
      Object.keys(value).forEach(function (k) {
        kv.appendChild(el("span", "k", k));
        kv.appendChild(el("span", "", paintValue(value[k])));
      });
      wrap.appendChild(kv);
      return wrap;
    }

    wrap.appendChild(el("p", "", String(value)));
    return wrap;
  }

  /* 逐轮分数折线：用行内 SVG，不引图表库 */
  function sparkline(points) {
    var w = 520;
    var h = 96;
    var pad = 6;
    if (!points.length) return el("p", "hint", "（本次会话还没有逐轮记录）");

    var maxScore = 100;
    var stepX = points.length > 1 ? (w - pad * 2) / (points.length - 1) : 0;
    var coords = points.map(function (p, i) {
      var x = pad + stepX * i;
      var y = h - pad - (Math.max(0, Math.min(maxScore, p.score)) / maxScore) * (h - pad * 2);
      return [x, y];
    });

    var svgNs = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNs, "svg");
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.setAttribute("width", "100%");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "逐轮风险分");

    [[85, "#c62828", "L3"], [60, "#ef6c00", "L2"], [35, "#f9a825", "L1"]].forEach(function (lv) {
      var line = document.createElementNS(svgNs, "line");
      var y = h - pad - (lv[0] / maxScore) * (h - pad * 2);
      line.setAttribute("x1", pad);
      line.setAttribute("x2", w - pad);
      line.setAttribute("y1", y);
      line.setAttribute("y2", y);
      line.setAttribute("stroke", lv[1]);
      line.setAttribute("stroke-dasharray", "3 4");
      line.setAttribute("opacity", ".45");
      svg.appendChild(line);
    });

    var path = "M" + coords.map(function (c) { return c[0].toFixed(1) + " " + c[1].toFixed(1); }).join(" L");
    var poly = document.createElementNS(svgNs, "path");
    poly.setAttribute("d", path);
    poly.setAttribute("fill", "none");
    poly.setAttribute("stroke", "#2e5c8a");
    poly.setAttribute("stroke-width", "2");
    svg.appendChild(poly);

    coords.forEach(function (c, i) {
      var dot = document.createElementNS(svgNs, "circle");
      dot.setAttribute("cx", c[0]);
      dot.setAttribute("cy", c[1]);
      dot.setAttribute("r", "3");
      dot.setAttribute("fill", points[i].level >= 2 ? "#c62828" : "#2e5c8a");
      svg.appendChild(dot);
    });

    var box = el("div");
    box.appendChild(svg);

    var legend = el("p", "hint", points.map(function (p, i) {
      return "第" + (i + 1) + "轮 " + p.score + "（L" + p.level + "）";
    }).join(" · "));
    box.appendChild(legend);
    return box;
  }

  function dimBars(dims) {
    var keys = Object.keys(dims || {});
    if (!keys.length) return el("p", "hint", "（这次判定没有维度明细）");
    var wrap = el("div", "dims");
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
      wrap.appendChild(row);
    });
    return wrap;
  }

  function render(report, ctx) {
    var empty = document.getElementById("reportEmpty");
    var paper = document.getElementById("reportPaper");
    if (!report) {
      if (empty) empty.hidden = false;
      if (paper) paper.hidden = true;
      return;
    }
    if (empty) empty.hidden = true;
    if (paper) paper.hidden = false;

    var meta = document.getElementById("paperMeta");
    if (meta) {
      meta.textContent = "会话 " + (report.session_id || ctx.sessionId || "") +
        " · 生成于 " + (report.generated_at || "") +
        " · 共 " + (report.turns || (ctx.decisions || []).length) + " 轮";
    }

    var body = document.getElementById("paperBody");
    if (!body) return;
    body.innerHTML = "";

    SECTIONS.forEach(function (sec) {
      var box = el("section", "paper-sec");
      box.appendChild(el("h3", "", sec.title));
      box.appendChild(sectionBody(report[sec.key]));
      body.appendChild(box);
    });

    var chartBox = el("section", "paper-sec");
    chartBox.appendChild(el("h3", "", "逐轮风险分（前端按本会话记录绘制）"));
    chartBox.appendChild(sparkline((ctx.decisions || []).map(function (d) {
      return { score: d.score || 0, level: d.level || 0 };
    })));
    body.appendChild(chartBox);

    var dimBox = el("section", "paper-sec");
    dimBox.appendChild(el("h3", "", "维度得分率（最近一轮，来自 decision.dims）"));
    var lastDecision = (ctx.decisions || []).slice(-1)[0] || {};
    dimBox.appendChild(dimBars(lastDecision.dims || {}));
    body.appendChild(dimBox);

    var disc = document.getElementById("paperDisclaimer");
    if (disc) {
      disc.textContent = report.disclaimer ||
        "本报告由 A30 后端生成，指标为演示环境实测值；未接入的模型能力已标注“未启用”。";
    }
  }

  global.ReportUI = { render: render, sparkline: sparkline, dimBars: dimBars };
})(window);
