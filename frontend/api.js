/* 后端接口封装。所有请求都走相对路径 /api/v1，不引任何库。
 *
 * 后端真实的响应形状（2026-11 实测）：
 *   POST /detect/text        -> { session_id, decision, alert|null, latency_ms }
 *   GET  /alerts/{id}        -> { alert: {...} }        ← 外层包一层
 *   POST /alerts/{id}/ack    -> { alert: {...} }
 *   GET  /report/{sid}       -> { report: {...} }       ← 外层包一层
 *   GET  /kb/scripts         -> { count, scripts: [...] }
 *   GET  /stats, /health     -> 裸对象
 */
(function (global) {
  "use strict";

  var API = "/api/v1";

  function ApiError(message, status, code) {
    this.name = "ApiError";
    this.message = message;
    this.status = status || 0;
    this.code = code || "";
  }
  ApiError.prototype = Object.create(Error.prototype);

  function readBody(res) {
    var type = res.headers.get("content-type") || "";
    if (type.indexOf("application/json") === -1) {
      return res.text().then(function (t) { return { raw: t }; });
    }
    return res.json().catch(function () { return { raw: "" }; });
  }

  function request(path, options) {
    var opts = options || {};
    var init = {
      method: opts.method || "GET",
      headers: { Accept: "application/json" }
    };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }

    return fetch(API + path, init).then(
      function (res) {
        return readBody(res).then(function (data) {
          if (res.ok) return data;
          var err = (data && data.error) || {};
          throw new ApiError(
            err.message || "请求失败（HTTP " + res.status + "）",
            res.status,
            err.code || ""
          );
        });
      },
      function () {
        throw new ApiError("连不上后端（服务没起？端口不对？）", 0, "network_error");
      }
    );
  }

  var api = {
    ApiError: ApiError,

    health: function () { return request("/health"); },

    stats: function () { return request("/stats"); },

    detectText: function (text, sessionId, role) {
      return request("/detect/text", {
        method: "POST",
        body: { text: text, session_id: sessionId, role: role }
      });
    },

    getAlert: function (id) {
      return request("/alerts/" + encodeURIComponent(id)).then(function (d) {
        return (d && d.alert) || d;
      });
    },

    ackAlert: function (id, action, note) {
      return request("/alerts/" + encodeURIComponent(id) + "/ack", {
        method: "POST",
        body: { action: action, note: note || "" }
      }).then(function (d) {
        return (d && d.alert) || d;
      });
    },

    getReport: function (sessionId) {
      return request("/report/" + encodeURIComponent(sessionId)).then(function (d) {
        return (d && d.report) || d;
      });
    },

    listScripts: function () { return request("/kb/scripts"); },

    listCases: function () { return request("/kb/cases"); }
  };

  global.API_BASE = API;
  global.api = api;
})(window);
