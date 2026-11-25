/* 本地状态：会话 id、对话轮次、每轮分数、告警列表、画像、监护人设置。
 *
 * 为什么存 sessionStorage 而不是后端：
 *   后端没有"告警列表"接口（只能按 id 取），report 里也没有逐轮历史。
 *   这两样是演示必需的，所以由前端按会话累积；刷新后恢复，关掉标签页即清。
 *   这不是理想设计，是当前契约下的降级方案，已写进 T-15 的「已知限制」。
 */
(function (global) {
  "use strict";

  var K = {
    session: "a30.session",
    turns: "a30.turns.",
    decisions: "a30.decisions.",
    alerts: "a30.alerts",
    profile: "a30.profile",
    settings: "a30.settings",
    lastReport: "a30.report."
  };

  function read(key, fallback) {
    try {
      var raw = sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function write(key, value) {
    try {
      sessionStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      /* 隐私模式下可能写不进去，忽略即可：状态退化到内存 */
    }
  }

  function newId() {
    var rand = Math.random().toString(36).slice(2, 8);
    return "s-" + Date.now().toString(36) + "-" + rand;
  }

  var store = {
    sessionId: function () {
      var id = read(K.session, "");
      if (!id) {
        id = newId();
        write(K.session, id);
      }
      return id;
    },

    resetSession: function () {
      var id = newId();
      write(K.session, id);
      return id;
    },

    turns: function (sid) { return read(K.turns + sid, []); },

    saveTurns: function (sid, turns) {
      write(K.turns + sid, turns.slice(-40));
    },

    decisions: function (sid) { return read(K.decisions + sid, []); },

    pushDecision: function (sid, entry) {
      var list = read(K.decisions + sid, []);
      list.push(entry);
      write(K.decisions + sid, list.slice(-40));
    },

    alerts: function () { return read(K.alerts, []); },

    saveAlerts: function (list) { write(K.alerts, (list || []).slice(-20)); },

    profile: function () { return read(K.profile, null); },

    saveProfile: function (p) { write(K.profile, p); },

    settings: function () {
      return read(K.settings, { name: "", rel: "", second: "", hook: "local" });
    },

    saveSettings: function (s) { write(K.settings, s); },

    cacheReport: function (sid, report) { write(K.lastReport + sid, report); },

    cachedReport: function (sid) { return read(K.lastReport + sid, null); },

    clear: function () {
      Object.keys(K).forEach(function (k) {
        try { sessionStorage.removeItem(K[k]); } catch (e) { /* ignore */ }
      });
    }
  };

  global.store = store;
})(window);
