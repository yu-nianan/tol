/* 画像：零提问推断 + 来源标注 + 少量追问。
 *
 * 三个原则（来自原型 README）：
 *  ① 画像只影响"建议怎么说"，不影响分数 —— 分数由后端 scoring.py 决定，这里只做展示；
 *  ② 每一格都标来源：自选 / 推断 / 回答 / 待确认；
 *  ③ 追问要克制：L2 以上静默、每会话 ≤2 次、每 3 轮 ≤1 次。
 */
(function (global) {
  "use strict";

  var FIELDS = [
    { key: "age", name: "年龄段" },
    { key: "live", name: "居住" },
    { key: "job", name: "职业" },
    { key: "digital", name: "手机熟练度" },
    { key: "state", name: "当前处境" }
  ];

  var ROLE_DEFAULT = {
    normal: { age: "30–45 岁", live: "", job: "", digital: "中等", state: "" },
    elder: { age: "60 岁以上", live: "", job: "已退休", digital: "偏低", state: "" },
    student: { age: "18–24 岁", live: "学校宿舍/合租", job: "在校学生", digital: "高", state: "" },
    child: { age: "18 岁以下", live: "", job: "在校学生", digital: "高", state: "" },
    finance: { age: "25–45 岁", live: "", job: "财务/出纳", digital: "高", state: "经手对公款项" }
  };

  var SOURCE_TEXT = { self: "自选", infer: "推断", answer: "回答", pending: "待确认" };

  function blankProfile(role) {
    var base = ROLE_DEFAULT[role] || ROLE_DEFAULT.normal;
    var out = {};
    FIELDS.forEach(function (f) {
      var v = base[f.key] || "";
      out[f.key] = { value: v, source: v ? "self" : "pending", why: "" };
    });
    return out;
  }

  function has(text, words) {
    for (var i = 0; i < words.length; i++) {
      if (text.indexOf(words[i]) !== -1) return true;
    }
    return false;
  }

  /* 从已发生的对话里推断，返回 { patch: {key:{value,source,why}}, why: [..] }。
   * 只做"能说清依据"的几条规则，不做猜谜。 */
  function infer(turns, profile, role) {
    var patch = {};
    var why = [];
    var all = turns.map(function (t) { return t.text; }).join("\n");
    var lastIdx = turns.length;

    function set(key, value, reason) {
      var cur = profile[key] || {};
      if (cur.value === value) return;
      if (cur.source === "answer" || cur.source === "self") return; // 人给的优先，不覆盖
      patch[key] = { value: value, source: "infer", why: reason };
      why.push(FIELDS.filter(function (f) { return f.key === key; })[0].name + "：" + reason);
    }

    if (has(all, ["退休", "养老金", "退休金", "老年机", "看不清字"])) {
      set("age", "60 岁以上", "第 " + lastIdx + " 轮提到「退休/养老金」");
      set("digital", "偏低", "同一条里出现老年机/看不清");
    }
    if (has(all, ["我妈", "我爸", "我奶奶", "我爷爷", "老人家"])) {
      set("age", "60 岁以上", "对话里出现「我妈/我爸」这类称呼");
    }
    if (has(all, ["学生", "宿舍", "同学", "学费", "辅导员", "实习"])) {
      set("age", "18–24 岁", "出现学生/宿舍/学费等词");
      set("job", "在校学生", "同上");
    }
    if (has(all, ["孩子", "儿子", "女儿", "幼儿园", "家长群"])) {
      set("live", "与家人同住", "对话里提到孩子/家长群");
    }
    if (has(all, ["公司", "货款", "对公", "发票", "报销", "老板"])) {
      set("job", "财务/出纳", "出现货款/对公/报销等词");
      set("state", "经手对公款项", "同上");
    }
    if (has(all, ["微信", "支付宝", "网银", "验证码", "收款码"])) {
      set("digital", "高", "出现微信/支付宝/网银/验证码");
    }
    if (has(all, ["不会弄", "怎么操作", "看不清", "帮我点", "你帮我弄"])) {
      set("digital", "偏低", "出现「不会弄/看不清/你帮我点」");
    }
    if (has(all, ["房租", "押金", "房东"])) set("live", "租房", "出现房租/押金");
    if (has(all, ["买房", "首付", "看病", "手术", "急用钱"])) {
      set("state", "有大额资金需求", "出现买房/看病/急用钱");
    }

    return { patch: patch, why: why };
  }

  /* 是否该追问。返回 null 或 { text, options: [{key,value,label}] } */
  function nextQuestion(ctx) {
    var turns = ctx.turns || [];
    var profile = ctx.profile || {};
    var level = ctx.level === undefined ? 0 : ctx.level;
    var asked = ctx.asked || 0;

    if (level >= 2) return null;                 // 已经在报警，别再问
    if (turns.length < 2) return null;           // 还没聊起来
    if (asked >= 2) return null;                 // 每会话最多两次
    if (turns.length % 3 !== 0) return null;     // 每 3 轮最多一次

    var askable = FIELDS.filter(function (f) {
      var v = profile[f.key];
      return !v || v.source === "pending" || (v.source === "infer" && !v.value);
    });
    if (!askable.length) return null;

    if (!profile.age || profile.age.source === "pending") {
      return {
        text: "（系统）为了把建议说得更准，问一句：这个账号平时主要是谁在用？",
        options: [
          { key: "age", value: "60 岁以上", label: "家里老人" },
          { key: "age", value: "18–24 岁", label: "我自己（学生）" },
          { key: "age", value: "30–45 岁", label: "我自己（上班）" },
          { key: "age", value: "18 岁以下", label: "孩子" }
        ]
      };
    }
    if (!profile.digital || profile.digital.source === "pending") {
      return {
        text: "（系统）再确认一下：手机银行、验证码这类操作，平时是你自己弄吗？",
        options: [
          { key: "digital", value: "高", label: "自己操作" },
          { key: "digital", value: "中等", label: "简单的会" },
          { key: "digital", value: "偏低", label: "一般让家人帮" }
        ]
      };
    }
    return null;
  }

  function render(profile, whyList) {
    var box = document.getElementById("profileFields");
    if (!box) return;
    box.innerHTML = "";
    FIELDS.forEach(function (f) {
      var item = profile[f.key] || { value: "", source: "pending" };
      var row = document.createElement("div");
      row.className = "field";

      var k = document.createElement("span");
      k.className = "k";
      k.textContent = f.name;

      var v = document.createElement("span");
      v.className = "v";
      v.textContent = item.value || "—";

      var tag = document.createElement("span");
      tag.className = "tag " + (item.source || "pending");
      tag.textContent = SOURCE_TEXT[item.source] || "待确认";

      row.appendChild(k);
      row.appendChild(v);
      row.appendChild(tag);
      box.appendChild(row);
    });

    var why = document.getElementById("profileWhy");
    if (why) {
      why.textContent = (whyList && whyList.length)
        ? "推断依据：" + whyList.join("；")
        : "还没有推断依据，先录两轮对话。";
    }
  }

  function applyPatch(profile, patch) {
    Object.keys(patch).forEach(function (key) {
      profile[key] = patch[key];
    });
    return profile;
  }

  function setField(profile, key, value, source) {
    if (!profile[key]) profile[key] = { value: "", source: "pending", why: "" };
    profile[key].value = value;
    profile[key].source = source || "answer";
    return profile;
  }

  global.Profile = {
    FIELDS: FIELDS,
    blank: blankProfile,
    infer: infer,
    nextQuestion: nextQuestion,
    render: render,
    applyPatch: applyPatch,
    setField: setField
  };
})(window);
