// © 2026 Andy217Ace
// Val 5: strat lazy pentru sezoane (încarcă sezoane.js, aduce datele, desenează) și pentru
// estimarea întârzierii finale. Doar textContent (CSP). Montat din Statistici / fișa trenului.
(function () {
  "use strict";
  function T(k, p) { return window.I18N.t(k, p); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function loadScript(src) {
    return new Promise(function (ok, fail) {
      if (window.Sezoane) return ok();
      var s = document.createElement("script");
      s.src = src; s.onload = ok; s.onerror = fail;
      document.head.appendChild(s);
    });
  }
  function clear(h) { while (h.firstChild) h.removeChild(h.firstChild); }

  // query: șirul de parametri deja folosit de Statistici (board, from, to, prag, min, ...)
  function mountSeasons(host, query) {
    var q = query ? (query.charAt(0) === "?" ? query : "?" + query) : "";
    return Promise.all([loadScript("sezoane.js"),
      fetch("/api/stats/seasons" + q, { headers: { Accept: "application/json" } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })])
      .then(function (res) {
        clear(host);
        host.append(el("h2", null, T("val5.seasons.title")));
        var body = el("div", "val5-body");
        host.append(body);
        window.Sezoane.render(body, res[1]);
        var a = el("a", "val5-csv", T("val5.seasons.csv"));
        a.href = "/api/stats/seasons" + (q ? q + "&" : "?") + "format=csv";
        a.setAttribute("download", "");
        host.append(a);
      })
      .catch(function () { clear(host); host.append(el("p", "val5-note", T("val5.seasons.loadFail"))); });
  }

  function fmt(v) { return window.I18N.lang() === "en" ? String(v) : String(v).replace(".", ","); }

  // payload-ul GET /api/trains/{no}/prediction: etichetă, N, interval, separat de citit
  function renderPrediction(host, d) {
    clear(host);
    var box = el("section", "val5-pred");
    box.append(el("strong", null, T("val5.pred.label")));
    if (!d.published) {
      box.append(el("p", "val5-note", T("val5.pred.hidden", { reason: d.reason || "" })));
    } else if (!d.estimates.length) {
      box.append(el("p", "val5-note", T("val5.pred.none")));
    } else {
      d.estimates.forEach(function (e) {
        var row = el("p", "val5-row", [
          window.I18N.station(e.station), T("val5.pred.median", { v: fmt(Math.round(e.delay_min * 10) / 10) }),
          T("val5.pred.interval", { low: fmt(Math.round(e.low * 10) / 10), high: fmt(Math.round(e.high * 10) / 10) }),
          T("val5.pred.n", { n: e.n })].join(" · "));
        box.append(row);
      });
    }
    box.append(el("p", "val5-note", d.note));
    host.append(box);
  }

  window.Val5 = { mountSeasons: mountSeasons, renderPrediction: renderPrediction };
})();
