// © 2026 Andy217Ace
// Tabela Gara de Nord — „UI v3” (Beta 1.28): the interactive chart layer. Lazy-loaded by
// App.ui2.charts() on #statistici, #tren, #clasamente and #statie only (never in the service-worker
// shell). Self-hosted, no library (CSP: script-src 'self'; the only style writes are CSSOM
// properties — transform / custom properties — which CSP allows; no inline style attribute, no HTML
// strings). Exposes App.charts3:
//   bind(svg)            hover / touch scrub / keyboard tooltip + crosshair for a bar, line, column or
//                        heat-map SVG (marks are read from the DOM: .ss-mark / .st-bar-g with a <title>)
//   legend(root)         legend items become toggles: hover highlights a series, click shows / hides it
//   tools(sec, o)        „Copiază linkul” and „Ecran complet” (modal <dialog> with the data table beside)
//   toc(body, items)     sticky section chips with scroll-spy
//   snapshot / morph     ease between the old and the new data when a filter changes
//   calendar(host, o)    GitHub-style day grid;  smooth / areaPath / refLine / extremes  line helpers
//   enhance(root, o)     one pass over a rendered page: bind + legend + tools
// Rules kept: N shown, missing is never 0, small samples stay marked, colour is never the only carrier
// (the tooltip names the series), reduced motion = no transitions, one tab stop per chart.
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  var SVG_NS = "http://www.w3.org/2000/svg";
  var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var nf = new Intl.NumberFormat("ro-RO", { maximumFractionDigits: 1 });
  var seq = 0;

  function reduced() { return !!(mq && mq.matches); }
  function uid(p) { seq += 1; return "c3-" + p + "-" + seq; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function s(tag, attrs, text) {
    var n = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, String(attrs[k])); });
    if (text != null) n.textContent = text;
    return n;
  }

  // ---- shared gradients (one hidden SVG for the whole document) --------------------------

  var defsDone = false;
  function ensureDefs() {
    if (defsDone || !document.body) return;
    defsDone = true;
    var svg = s("svg", { class: "c3-defs", width: 0, height: 0, "aria-hidden": "true", focusable: "false" });
    var defs = s("defs");
    ["arr", "dep"].forEach(function (b) {
      [["v", 0, 0, 0, 1, 1, 0.58], ["h", 0, 0, 1, 0, 0.58, 1]].forEach(function (g) {
        var lg = s("linearGradient", { id: "c3-" + g[0] + "-" + b, x1: g[1], y1: g[2], x2: g[3], y2: g[4] });
        lg.append(s("stop", { offset: 0, class: "c3-s-" + b, "stop-opacity": g[5] }));
        lg.append(s("stop", { offset: 1, class: "c3-s-" + b, "stop-opacity": g[6] }));
        defs.append(lg);
      });
      var ar = s("linearGradient", { id: "c3-a-" + b, x1: 0, y1: 0, x2: 0, y2: 1 });
      ar.append(s("stop", { offset: 0, class: "c3-s-" + b, "stop-opacity": 0.15 }));
      ar.append(s("stop", { offset: 1, class: "c3-s-" + b, "stop-opacity": 0 }));
      defs.append(ar);
    });
    svg.append(defs);
    document.body.append(svg);
  }

  // ---- the floating tooltip (one for the whole page) -------------------------------------

  var tipEl = null;
  var liveEl = null;
  var tipOwner = null;
  var touchMode = false;

  function tipNode() {
    if (!tipEl) {
      tipEl = h("div", "c3-tip");
      tipEl.setAttribute("aria-hidden", "true");   // the text alternative lives on the chart (live region + table)
      tipEl.setAttribute("role", "presentation");
      document.body.append(tipEl);
    }
    return tipEl;
  }
  function liveNode() {
    if (!liveEl) {
      liveEl = h("div", "sr-only");
      liveEl.setAttribute("aria-live", "polite");
      liveEl.setAttribute("aria-atomic", "true");
      document.body.append(liveEl);
    }
    return liveEl;
  }

  // "Sosiri, 13:00–13:59: mediana 3 min, N = 12" → {series:"Sosiri", head:"13:00–13:59", body:"mediana 3 min, N = 12"}
  function parseTip(text) {
    var t = String(text || "");
    var m = /^(Sosiri|Plecări), (.*?): (.*)$/.exec(t);
    if (m) return { series: m[1], head: m[2], body: m[3] };
    m = /^(.*?): (.*)$/.exec(t);
    if (m) return { series: null, head: m[1], body: m[2] };
    return { series: null, head: "", body: t };
  }

  function fillTip(rows, head) {
    var el = tipNode();
    el.replaceChildren();
    if (head) el.append(h("div", "c3-tip-h", head));
    rows.forEach(function (r) {
      var row = h("div", "c3-tip-r");
      if (r.cls) { var k = h("span", "ss-key " + r.cls); k.setAttribute("aria-hidden", "true"); row.append(k); }
      var txt = h("div", "c3-tip-t");
      if (r.name) txt.append(h("strong", "c3-tip-n", r.name));
      txt.append(h("span", "c3-tip-b", r.body));
      row.append(txt);
      el.append(row);
    });
  }

  // Place the tooltip outside `rect` (the hovered mark(s)): above if it fits, else below, else beside;
  // always clamped inside the viewport. On touch it floats higher so a finger never hides it.
  function placeTip(rect, touch) {
    var el = tipNode();
    var vw = document.documentElement.clientWidth || window.innerWidth;
    var vh = window.innerHeight;
    var m = 8;
    var gap = touch ? 20 : 10;
    var w = el.offsetWidth, hgt = el.offsetHeight;
    var cx = rect.left + rect.width / 2;
    var x = clamp(cx - w / 2, m, Math.max(m, vw - w - m));
    var y, side = "above";
    if (rect.top - gap - hgt >= m) y = rect.top - gap - hgt;
    else if (rect.bottom + gap + hgt <= vh - m) { y = rect.bottom + gap; side = "below"; }
    else {
      side = "beside";
      var right = rect.right + gap;
      x = right + w <= vw - m ? right : Math.max(m, rect.left - gap - w);
      y = clamp(rect.top + rect.height / 2 - hgt / 2, m, Math.max(m, vh - hgt - m));
    }
    el.setAttribute("data-side", side);
    el.style.setProperty("--c3-caret", clamp(cx - x, 12, Math.max(12, w - 12)).toFixed(0) + "px");
    el.style.transform = "translate3d(" + Math.round(x) + "px," + Math.round(y) + "px,0)";
  }

  function showTip(rows, head, rect, owner, touch) {
    fillTip(rows, head);
    var el = tipNode();
    tipOwner = owner;
    touchMode = !!touch;
    el.classList.toggle("is-touch", !!touch);
    placeTip(rect, touch);
    el.classList.add("is-on");
  }
  function hideTip(owner) {
    if (owner && tipOwner !== owner) return;
    tipOwner = null;
    if (tipEl) tipEl.classList.remove("is-on");
  }

  var outsideBound = false;
  function bindOutside() {
    if (outsideBound) return;
    outsideBound = true;
    document.addEventListener("pointerdown", function (e) {
      if (!tipOwner) return;
      if (tipOwner.contains && tipOwner.contains(e.target)) return;
      if (tipOwner.__c3clear) tipOwner.__c3clear();
    }, true);
    window.addEventListener("scroll", function () {
      if (tipOwner && touchMode && tipOwner.__c3clear) tipOwner.__c3clear();
    }, { passive: true });
    window.addEventListener("resize", function () { if (tipOwner && tipOwner.__c3clear) tipOwner.__c3clear(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && tipOwner && tipOwner.__c3clear) tipOwner.__c3clear();
    });
  }

  // ---- bind: marks, categories, crosshair, pointer / touch / keyboard -----------------------

  var idleIO = null;

  function boardOf(el) {
    if (!el || !el.classList) return null;
    if (el.classList.contains("ss-arr")) return "ss-arr";
    if (el.classList.contains("ss-dep")) return "ss-dep";
    return null;
  }

  function unionRect(rects) {
    var r = { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity };
    rects.forEach(function (q) {
      r.left = Math.min(r.left, q.left); r.top = Math.min(r.top, q.top);
      r.right = Math.max(r.right, q.right); r.bottom = Math.max(r.bottom, q.bottom);
    });
    r.width = r.right - r.left;
    r.height = r.bottom - r.top;
    return r;
  }

  function bind(svg) {
    if (!svg || svg.__c3) return svg;
    svg.__c3 = true;
    ensureDefs();
    bindOutside();
    var fig = svg.closest(".ss-fig, .c3-dlg-body, .st-card, .ss-multiple") || svg.parentNode;
    var recs = [];
    [].forEach.call(svg.querySelectorAll(".ss-mark, .st-bar-g, .c3-mark"), function (g, idx) {
      var t = null;
      for (var c = g.firstChild; c; c = c.nextSibling) if (c.nodeName === "title") { t = c; break; }
      var text = t ? t.textContent : g.getAttribute("data-tip");
      if (!text) return;
      if (t) g.removeChild(t);          // the native tooltip is slow and absent on touch: replaced by ours
      g.setAttribute("data-tip", text);
      var vis = g.querySelector(".ss-bar, .ss-dot, .ss-cell, .st-bar, .ss-track") || g;
      recs.push({ g: g, el: vis, text: text, tip: parseTip(text), board: g.getAttribute("data-b") || boardOf(vis), idx: idx,
                  i: g.hasAttribute("data-i") ? Number(g.getAttribute("data-i")) : null });
    });
    var d = svg.querySelector("desc");
    if (d && recs.length) d.textContent += " Grafic interactiv: cu tastatura, săgețile schimbă valoarea, Esc închide.";
    if (!recs.length) return svg;

    var kind = svg.getAttribute("data-kind") || "unit";
    var grouped = kind === "col" || kind === "line";
    var plot = (svg.getAttribute("data-plot") || "").split(",").map(Number);
    var ncat = Number(svg.getAttribute("data-n")) || 0;
    var vbW = svg.viewBox && svg.viewBox.baseVal && svg.viewBox.baseVal.width || 1;
    var cross = null;
    if (grouped && plot.length === 4) {
      cross = kind === "line" ? s("line", { class: "c3-cross", "aria-hidden": "true" }) : s("rect", { class: "c3-band", "aria-hidden": "true" });
      var after = svg.querySelector("desc");
      svg.insertBefore(cross, after ? after.nextSibling : svg.firstChild);
    }
    svg.setAttribute("tabindex", "0");
    svg.classList.add("c3-bound");
    if (kind === "col" || kind === "line") svg.setAttribute("data-c3", kind);

    var units = null;      // [{key, recs, rect centre}] — rebuilt on each hover session
    var activeKey = null;
    var kbd = false;
    var liveT = null;

    function visible(r) { return !(r.board && fig.classList && fig.classList.contains("c3-off-" + r.board.slice(3))); }

    function buildUnits() {
      var list = [];
      if (grouped) {
        var by = {};
        recs.forEach(function (r) {
          if (!visible(r)) return;
          (by[r.i] = by[r.i] || []).push(r);
        });
        Object.keys(by).forEach(function (k) {
          var rs = by[k];
          var rects = rs.map(function (r) { return r.el.getBoundingClientRect(); });
          var u = unionRect(rects);
          list.push({ key: "i" + k, i: Number(k), recs: rs, rect: u, cx: (u.left + u.right) / 2, cy: (u.top + u.bottom) / 2 });
        });
        list.sort(function (a, b) { return a.cx - b.cx; });
      } else {
        recs.forEach(function (r, n) {
          if (!visible(r)) return;
          var u = r.el.getBoundingClientRect();
          list.push({ key: "u" + n, i: n, recs: [r], rect: u, cx: u.left + u.width / 2, cy: u.top + u.height / 2 });
        });
      }
      return list;
    }

    function unitRows(u) {
      var head = u.recs[0].tip.head;
      var rows = u.recs.map(function (r) {
        return { cls: r.board, name: r.tip.series, body: r.tip.body || r.tip.head };
      });
      if (!head && rows.length === 1) head = "";
      return { head: head, rows: rows };
    }

    function clearAct() {
      svg.classList.remove("c3-has-act");
      [].forEach.call(svg.querySelectorAll(".c3-act"), function (n) { n.classList.remove("c3-act"); });
      if (cross) cross.classList.remove("is-on");
    }

    function mirror(u, on) {
      // the other charts of the same figure (e.g. the N strip under a line) follow the crosshair
      if (!fig.__c3svgs) return;
      fig.__c3svgs.forEach(function (o) { if (o !== api && o.setCross) o.setCross(on ? u.i : null); });
    }

    function setCross(i) {
      if (!cross || plot.length !== 4) return;
      if (i == null || !ncat) { cross.classList.remove("is-on"); return; }
      var pitch = (plot[2] - plot[0]) / ncat;
      var cx = plot[0] + pitch * i + pitch / 2;
      if (kind === "line") {
        cross.setAttribute("x1", cx.toFixed(1)); cross.setAttribute("x2", cx.toFixed(1));
        cross.setAttribute("y1", plot[1]); cross.setAttribute("y2", plot[3]);
      } else {
        cross.setAttribute("x", (cx - pitch / 2).toFixed(1)); cross.setAttribute("y", plot[1]);
        cross.setAttribute("width", pitch.toFixed(1)); cross.setAttribute("height", plot[3] - plot[1]);
      }
      cross.classList.add("is-on");
    }

    function activate(u, touch, announce) {
      clearAct();
      activeKey = u.key;
      svg.classList.add("c3-has-act");
      u.recs.forEach(function (r) { r.g.classList.add("c3-act"); });
      setCross(grouped ? u.i : null);
      var m = unitRows(u);
      showTip(m.rows, m.head, u.rect, svg, touch);
      if (grouped) mirror(u, true);
      if (announce) {
        clearTimeout(liveT);
        liveT = setTimeout(function () {
          liveNode().textContent = (m.head ? m.head + ". " : "") + m.rows.map(function (r) { return (r.name ? r.name + ": " : "") + r.body; }).join(". ");
        }, 140);
      }
    }

    function clear() {
      clearAct();
      activeKey = null;
      units = null;
      hideTip(svg);
      if (grouped) mirror({ i: null }, false);
    }
    svg.__c3clear = clear;

    function unitAt(e) {
      if (!units) units = buildUnits();
      if (!units.length) return null;
      var t = e.target && e.target.closest ? e.target.closest(".ss-mark, .st-bar-g, .c3-mark") : null;
      var best = null, bd = Infinity;
      if (grouped) {
        units.forEach(function (u) { var dd = Math.abs(e.clientX - u.cx); if (dd < bd) { bd = dd; best = u; } });
        return best;
      }
      if (t && svg.contains(t)) {
        for (var n = 0; n < units.length; n++) if (units[n].recs[0].g === t) return units[n];
      }
      units.forEach(function (u) {
        var dd = Math.hypot(e.clientX - u.cx, e.clientY - u.cy);
        if (dd < bd) { bd = dd; best = u; }
      });
      return bd <= 36 ? best : null;
    }

    function handle(e, touch) {
      var u = unitAt(e);
      if (!u) { clear(); return; }
      if (u.key !== activeKey || touch) activate(u, touch, false);
    }

    var down = false;
    svg.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "mouse") return;
      down = true;
      units = null;
      handle(e, true);
    });
    svg.addEventListener("pointermove", function (e) {
      if (e.pointerType === "mouse") { if (!kbd) handle(e, false); return; }
      if (down) handle(e, true);
    });
    function up() { down = false; }
    svg.addEventListener("pointerup", up);
    svg.addEventListener("pointercancel", up);
    svg.addEventListener("pointerenter", function (e) { if (e.pointerType === "mouse") { kbd = false; units = null; } });
    svg.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse" && document.activeElement !== svg) clear(); });

    // keyboard: one tab stop; arrows walk the marks (nearest neighbour in that direction)
    function neighbour(dir) {
      if (!units) units = buildUnits();
      if (!units.length) return null;
      var cur = null;
      for (var n = 0; n < units.length; n++) if (units[n].key === activeKey) cur = units[n];
      if (!cur) return dir === "end" ? units[units.length - 1] : units[0];
      if (dir === "home") return units[0];
      if (dir === "end") return units[units.length - 1];
      if (grouped && (dir === "left" || dir === "right")) {
        // a column / line chart's marks are in category order: step to the next one, not by
        // screen geometry (a short neighbour bar could otherwise win over the adjacent tall one)
        return units[units.indexOf(cur) + (dir === "right" ? 1 : -1)] || null;
      }
      var best = null, bs = Infinity;
      units.forEach(function (u) {
        if (u === cur) return;
        var dx = u.cx - cur.cx, dy = u.cy - cur.cy;
        var along = dir === "right" ? dx : dir === "left" ? -dx : dir === "down" ? dy : -dy;
        var perp = (dir === "left" || dir === "right") ? Math.abs(dy) : Math.abs(dx);
        if (along <= 0.5) return;
        if (grouped && (dir === "up" || dir === "down")) return;
        var score = along + 2.5 * perp;
        if (score < bs) { bs = score; best = u; }
      });
      return best;
    }
    svg.addEventListener("keydown", function (e) {
      var dir = { ArrowRight: "right", ArrowLeft: "left", ArrowDown: "down", ArrowUp: "up", Home: "home", End: "end" }[e.key];
      if (e.key === "Escape") { if (activeKey) { e.preventDefault(); e.stopPropagation(); clear(); } return; }
      if (!dir) return;
      e.preventDefault();
      kbd = true;
      units = buildUnits();
      var u = neighbour(dir);
      if (u) activate(u, false, true);
    });
    svg.addEventListener("focus", function () {
      if (!svg.matches(":focus-visible")) return;
      kbd = true;
      units = buildUnits();
      var u = neighbour("home");
      if (u) activate(u, false, true);
    });
    svg.addEventListener("blur", function () { kbd = false; clear(); });

    var api = { svg: svg, setCross: setCross, clear: clear, units: function () { return buildUnits(); },
                activate: function (i) {
                  units = buildUnits();
                  var u = units.filter(function (x) { return x.i === i; })[0];
                  if (u) activate(u, false, false);
                } };
    if (fig) { fig.__c3svgs = fig.__c3svgs || []; fig.__c3svgs.push(api); }

    // off-screen charts do not animate until they are seen (no work for what nobody looks at)
    if (typeof IntersectionObserver !== "undefined" && !reduced()) {
      if (!idleIO) {
        idleIO = new IntersectionObserver(function (entries) {
          entries.forEach(function (en) {
            if (!en.isIntersecting) return;
            en.target.classList.remove("c3-idle");
            idleIO.unobserve(en.target);
          });
        }, { rootMargin: "80px 0px" });
      }
      svg.classList.add("c3-idle");
      idleIO.observe(svg);
    }
    return svg;
  }

  // ---- legend: hover highlights a series, click shows / hides it -------------------------

  function legend(root) {
    if (!root || root.__c3leg) return;
    var items = [].filter.call(root.querySelectorAll(".ss-legend-item"), function (it) {
      return it.querySelector(".ss-key.ss-arr, .ss-key.ss-dep");
    });
    if (!items.length) return;
    root.__c3leg = true;
    var boards = {};
    items.forEach(function (it) {
      var b = it.querySelector(".ss-key.ss-dep") ? "dep" : "arr";
      boards[b] = it;
    });
    var multi = Object.keys(boards).length > 1;
    Object.keys(boards).forEach(function (b) {
      var it = boards[b];
      it.classList.add("c3-leg");
      it.setAttribute("tabindex", "0");
      it.setAttribute("role", "button");
      it.setAttribute("aria-pressed", "true");
      var on = function () { root.classList.add("c3-hl-" + b); };
      var off = function () { root.classList.remove("c3-hl-" + b); };
      it.addEventListener("pointerenter", on);
      it.addEventListener("pointerleave", off);
      it.addEventListener("focus", on);
      it.addEventListener("blur", off);
      var toggle = function () {
        if (!multi) return;
        var other = b === "arr" ? "dep" : "arr";
        var hidden = root.classList.contains("c3-off-" + b);
        if (!hidden && root.classList.contains("c3-off-" + other)) return;   // never hide the last series
        root.classList.toggle("c3-off-" + b, !hidden);
        it.setAttribute("aria-pressed", hidden ? "true" : "false");
        (root.__c3svgs || []).forEach(function (o) { o.clear(); });
      };
      it.addEventListener("click", toggle);
      it.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
      });
      if (!multi) { it.removeAttribute("role"); it.removeAttribute("aria-pressed"); it.removeAttribute("tabindex"); }
    });
  }

  // ---- full screen + copy link -----------------------------------------------------------

  var ICON = {
    link: ["M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1", "M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"],
    full: ["M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"],
    close: ["M6 6l12 12M18 6L6 18"]
  };
  function icon(name) {
    var svg = s("svg", { viewBox: "0 0 24 24", class: "c3-ic", "aria-hidden": "true", focusable: "false" });
    ICON[name].forEach(function (d) { svg.append(s("path", { d: d })); });
    return svg;
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return legacyCopy(text); });
    }
    return Promise.resolve(legacyCopy(text));
  }
  function legacyCopy(text) {
    var ta = h("textarea", "sr-only");
    ta.value = text;
    ta.setAttribute("readonly", "");
    document.body.append(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  function rewriteIds(root, suffix) {
    var map = {};
    [].forEach.call(root.querySelectorAll("[id]"), function (n) { map[n.id] = n.id + suffix; n.id = n.id + suffix; });
    [].forEach.call(root.querySelectorAll("[aria-labelledby], [aria-describedby]"), function (n) {
      ["aria-labelledby", "aria-describedby"].forEach(function (a) {
        var v = n.getAttribute(a);
        if (v) n.setAttribute(a, v.split(/\s+/).map(function (id) { return map[id] ? map[id] : id; }).join(" "));
      });
    });
  }

  var FOCUSABLE = 'a[href], button:not([disabled]), summary, [tabindex="0"], input, select, textarea';

  function openFullscreen(sec, opener) {
    var title = sec.querySelector(".ss-fig-title");
    var dlg = h("dialog", "c3-dlg");
    var tid = uid("t");
    dlg.setAttribute("aria-labelledby", tid);
    var box = h("div", "c3-dlg-box");
    var head = h("div", "c3-dlg-head");
    var h2 = h("h2", "c3-dlg-title", title ? title.textContent : "Grafic");
    h2.id = tid;
    var close = h("button", "btn btn-ghost c3-dlg-close");
    close.type = "button";
    close.setAttribute("aria-label", "Închide ecranul complet");
    close.append(icon("close"), h("span", "c3-dlg-close-t", "Închide"));
    head.append(h2, close);
    var body = h("div", "c3-dlg-body");
    var left = h("div", "c3-dlg-chart");
    var lg = sec.querySelector(".ss-legend");
    if (lg) left.append(lg.cloneNode(true));
    var ch = sec.querySelector(".ss-chart");
    if (ch) left.append(ch.cloneNode(true));
    var right = h("div", "c3-dlg-side");
    var how = sec.querySelector(".ss-how");
    if (how) right.append(how.cloneNode(true));
    var det = sec.querySelector("details.ss-data");
    if (det) {
      var data = h("div", "c3-dlg-data");
      data.append(h("h3", "c3-dlg-h3", "Datele (tabel)"));
      [].forEach.call(det.children, function (n) { if (n.nodeName !== "SUMMARY") data.append(n.cloneNode(true)); });
      right.append(data);
    }
    var foot = sec.querySelector(".ss-n");
    if (foot) right.append(foot.cloneNode(true));
    body.append(left, right);
    box.append(head, body);
    dlg.append(box);
    rewriteIds(dlg, "-fs");
    document.body.append(dlg);
    // the tooltip lives inside the dialog while it is open (a modal dialog covers everything outside it)
    dlg.append(tipNode());
    legend(body);
    // the cloned legend lives in `left`; legend() works on the container that carries the c3-* state
    var cleanup = function () {
      hideTip();
      document.body.append(tipNode());
      dlg.remove();
      if (opener && opener.focus) opener.focus();
    };
    dlg.addEventListener("close", cleanup);
    close.addEventListener("click", function () { dlg.close(); });
    dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("keydown", function (e) {
      if (e.key !== "Tab") return;
      var f = [].filter.call(dlg.querySelectorAll(FOCUSABLE), function (n) { return n.offsetParent !== null || n === close; });
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (f.indexOf(document.activeElement) < 0) { e.preventDefault(); first.focus(); }
    });
    dlg.showModal();
    // line / column charts are drawn again at the size of the dialog (it must be laid out first); the others are scaled copies
    var orig = sec.querySelectorAll("svg.ss-svg");
    [].forEach.call(left.querySelectorAll("svg.ss-svg"), function (svg, i) {
      var o = orig[i];
      if (o && o.__build) {
        var tmp = h("div");
        o.__build(tmp, { width: Math.max(320, left.clientWidth), height: o.getAttribute("data-kind") === "col" && o.viewBox.baseVal.height < 100 ? undefined : Math.min(480, Math.round(window.innerHeight * 0.55)) });
        svg.replaceWith(tmp.firstChild);
        svg = tmp.firstChild || svg;
      }
    });
    [].forEach.call(left.querySelectorAll("svg.ss-svg"), function (svg) {
      svg.removeAttribute("width"); svg.removeAttribute("height");
      svg.__c3 = false;
      [].forEach.call(svg.querySelectorAll(".c3-cross, .c3-band"), function (n) { n.remove(); });
      svg.classList.remove("c3-idle", "c3-bound");
      bind(svg);
    });
    close.focus();
    return dlg;
  }

  function toast(msg) {
    var t = document.getElementById("toast");
    if (!t) return;
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { t.hidden = true; }, 2600);
  }

  // o: {key, url: function(key) -> absolute URL}
  function tools(sec, o) {
    if (!sec || sec.__c3tools) return;
    sec.__c3tools = true;
    var head = sec.querySelector(".ss-fig-head");
    if (!head) return;
    var box = h("div", "c3-tools");
    var link = h("button", "btn btn-ghost btn-sm c3-tool");
    link.type = "button";
    link.setAttribute("aria-label", "Copiază linkul către acest grafic");
    link.title = "Copiază linkul către acest grafic";
    link.append(icon("link"));
    link.addEventListener("click", function () {
      var url = o && o.url ? o.url(o.key) : location.href;
      Promise.resolve(copyText(url)).then(function (ok) {
        toast(ok ? "Link copiat: graficul se deschide direct la locul lui." : "Nu am putut copia linkul. Copiază-l din bara de adrese.");
      });
    });
    box.append(link);
    if (sec.querySelector("svg.ss-svg") && typeof HTMLDialogElement !== "undefined") {
      var full = h("button", "btn btn-ghost btn-sm c3-tool c3-full");
      full.type = "button";
      full.setAttribute("aria-label", "Deschide graficul pe tot ecranul, cu tabelul alături");
      full.title = "Ecran complet";
      full.append(icon("full"));
      full.addEventListener("click", function () { openFullscreen(sec, full); });
      box.append(full);
    }
    var csv = head.querySelector(".ss-csv");
    var acts = h("div", "c3-acts");     // tools + CSV stay together on the right of the title
    head.append(acts);
    acts.append(box);
    if (csv) acts.append(csv);
  }

  // ---- table of contents chips with scroll-spy ----------------------------------------------

  var navH = 0;
  function syncNavH() {
    var nav = document.querySelector(".navbar");
    var v = nav ? nav.offsetHeight : 0;
    if (v === navH) return;
    navH = v;
    document.documentElement.style.setProperty("--c3-nav-h", v + "px");
  }
  window.addEventListener("resize", syncNavH);

  // items: [{label, el}]
  function toc(body, items) {
    syncNavH();
    if (!items) items = statisticiItems(body);
    if (body.__c3toc) { body.__c3toc.disconnect(); body.__c3toc = null; }
    items = items.filter(function (it) { return it.el && it.el.isConnected !== false; });
    if (items.length < 3) return null;
    var nav = h("nav", "c3-toc");
    nav.setAttribute("aria-label", "Secțiunile paginii");
    var list = h("ul", "c3-toc-list");
    var chips = items.map(function (it) {
      var li = h("li");
      var b = h("button", "c3-chip", it.label);
      b.type = "button";
      b.addEventListener("click", function () {
        it.el.scrollIntoView({ block: "start", behavior: reduced() ? "auto" : "smooth" });
        var hd = it.el.querySelector("h2, h3") || it.el;
        if (!hd.hasAttribute("tabindex")) hd.setAttribute("tabindex", "-1");
        try { hd.focus({ preventScroll: true }); } catch (e) { hd.focus(); }
        setCur(items.indexOf(it));
      });
      li.append(b);
      list.append(li);
      return b;
    });
    nav.append(list);
    // a sibling before the body, not a child: sticky needs a containing block as tall as the page
    if (body.__c3nav) body.__c3nav.remove();
    body.parentNode.insertBefore(nav, body);
    body.__c3nav = nav;
    var cur = -1;
    function setCur(i) {
      if (i === cur) return;
      cur = i;
      chips.forEach(function (b, n) {
        if (n === i) {
          b.setAttribute("aria-current", "location");
          // keep the active chip inside the strip (scrolls the strip, never the page)
          var l = b.offsetLeft, w = b.offsetWidth, sc = list;
          if (l < sc.scrollLeft + 16) sc.scrollLeft = Math.max(0, l - 16);
          else if (l + w > sc.scrollLeft + sc.clientWidth - 16) sc.scrollLeft = l + w - sc.clientWidth + 16;
        } else b.removeAttribute("aria-current");
      });
    }
    // scroll-spy: the active chip is the last section that has started above the reading line (a few rect
    // reads per animation frame, no writes in between)
    var raf = 0;
    var spy = function () {
      if (raf) return;
      raf = requestAnimationFrame(function () {
        raf = 0;
        var line = navH + 56 + (window.innerHeight - navH - 56) * 0.3;
        var at = 0;
        for (var n = 0; n < items.length; n++) if (items[n].el.getBoundingClientRect().top <= line) at = n;
        setCur(at);
      });
    };
    window.addEventListener("scroll", spy, { passive: true });
    body.__c3toc = { disconnect: function () { window.removeEventListener("scroll", spy); } };
    spy();
    setCur(0);
    return nav;
  }

  // ---- line helpers: smooth curve, area, reference line, extremes ---------------------------

  // Monotone cubic (Fritsch–Carlson) through [[x, y], …]: smooth, never overshoots the data
  function smooth(pts) {
    var n = pts.length;
    if (!n) return "";
    var f = function (v) { return v.toFixed(1); };
    var d = "M" + f(pts[0][0]) + "," + f(pts[0][1]);
    if (n === 1) return d;
    if (n === 2) return d + "L" + f(pts[1][0]) + "," + f(pts[1][1]);
    var dx = [], m = [], t = [];
    for (var i = 0; i < n - 1; i++) {
      dx[i] = pts[i + 1][0] - pts[i][0];
      m[i] = dx[i] ? (pts[i + 1][1] - pts[i][1]) / dx[i] : 0;
    }
    t[0] = m[0];
    t[n - 1] = m[n - 2];
    for (i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
    for (i = 0; i < n - 1; i++) {
      if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
      var a = t[i] / m[i], b = t[i + 1] / m[i], r = a * a + b * b;
      if (r > 9) { var k = 3 / Math.sqrt(r); t[i] = k * a * m[i]; t[i + 1] = k * b * m[i]; }
    }
    for (i = 0; i < n - 1; i++) {
      var h3 = dx[i] / 3;
      d += "C" + f(pts[i][0] + h3) + "," + f(pts[i][1] + t[i] * h3) + " " +
        f(pts[i + 1][0] - h3) + "," + f(pts[i + 1][1] - t[i + 1] * h3) + " " + f(pts[i + 1][0]) + "," + f(pts[i + 1][1]);
    }
    return d;
  }
  function areaPath(curve, pts, base) {
    if (pts.length < 2) return "";
    return curve + "L" + pts[pts.length - 1][0].toFixed(1) + "," + base + "L" + pts[0][0].toFixed(1) + "," + base + "Z";
  }

  // dashed reference line with a label: o {y, x1, x2, label, cls, side: "above"|"below"}
  function refLine(root, o) {
    var g = s("g", { class: "c3-ref " + (o.cls || ""), "aria-hidden": "true" });
    g.append(s("line", { x1: o.x1, x2: o.x2, y1: o.y.toFixed(1), y2: o.y.toFixed(1) }));
    var below = o.side === "below";
    if (o.margin) {
      // label in the right margin, vertically centred on the line: never on top of the data
      g.append(s("text", { x: o.x2 + 4, y: (o.y + 3.5 + (o.shift || 0)).toFixed(1), class: "c3-ref-t c3-ref-l" }, o.label));
      root.append(g);
      return g;
    }
    var left = o.align === "left";
    g.append(s("text", { x: left ? o.x1 + 3 : o.x2 - 2, y: (o.y + (below ? 11 : -4)).toFixed(1), class: "c3-ref-t" + (left ? " c3-ref-l" : "") }, o.label));
    root.append(g);
    return g;
  }

  // Reference lines of a line chart; ctx {y(v), x(i), L, W, R, margin, series}. Labels go to the right margin on
  // wide charts, otherwise to whichever end of the plot is emptier around that height; two close lines don't collide.
  function lineRefs(root, refs, ctx) {
    var placed = [];
    refs.forEach(function (r) {
      var yy = ctx.y(r.value);
      if (r.value == null || r.value < 0 || yy < ctx.T - 1) return;
      var below = placed.some(function (p) { return Math.abs(p - yy) < 13; });
      placed.push(yy);
      if (ctx.margin) { refLine(root, { y: yy, x1: ctx.L, x2: ctx.W - ctx.R + 6, label: r.short || r.label, cls: r.cls, margin: true, shift: below ? 12 : -2 }); return; }
      var l = 0, rt = 0;
      ctx.series.forEach(function (se) {
        se.values.forEach(function (val, i) {
          if (val == null || Math.abs(ctx.y(val) - yy) > 16) return;
          if (ctx.x(i) < ctx.L + 110) l += 1;
          if (ctx.x(i) > ctx.W - ctx.R - 110) rt += 1;
        });
      });
      refLine(root, { y: yy, x1: ctx.L, x2: ctx.W - ctx.R, label: r.label, cls: r.cls, side: below ? "below" : r.side, align: l < rt ? "left" : "right" });
    });
  }

  // #statistici?...&grafic=<key>: scroll to that chart once it is drawn and mark it for a moment
  function focusKey(body, key) {
    var sec = body.querySelector('[data-key="' + String(key).replace(/[^a-z0-9-]/g, "") + '"]');
    if (!sec) return;
    requestAnimationFrame(function () {
      sec.scrollIntoView({ block: "start", behavior: "auto" });
      sec.classList.add("is-target");
      setTimeout(function () { sec.classList.remove("is-target"); }, 2400);
    });
  }

  // "max 12" above the highest column that has no value label of its own
  function colMax(root, top, o) {
    root.append(s("text", { x: clamp(top.x, o.L + 14, o.W - o.R - 14).toFixed(1), y: Math.max(11, top.y - 5).toFixed(1),
                            class: "c3-ext " + o.cls, "text-anchor": "middle" }, "max " + o.label));
  }

  // Label the highest (and lowest) point: pts [{x, y, v}]; `taken` = labels already placed [{x, y}]
  function extremes(root, pts, fmt, o) {
    var op = o || {};
    if (pts.length < 2) return;
    var hi = pts[0], lo = pts[0];
    pts.forEach(function (p) { if (p.v > hi.v) hi = p; if (p.v < lo.v) lo = p; });
    var taken = op.taken || [];
    var list = [[hi, "max", -9]];
    if (lo !== hi && lo.v !== hi.v) list.push([lo, "min", 15]);
    list.forEach(function (it) {
      var p = it[0];
      var ly = clamp(p.y + it[2], op.top != null ? op.top : 10, op.bottom != null ? op.bottom : 9999);
      var clash = taken.some(function (t) { return Math.abs(t.x - p.x) < 40 && Math.abs(t.y - ly) < 12; });
      if (clash) return;
      taken.push({ x: p.x, y: ly });
      var anchor = p.x < 30 ? "start" : (op.right && p.x > op.right - 30 ? "end" : "middle");
      var t = s("text", { x: p.x.toFixed(1), y: ly.toFixed(1), class: "c3-ext " + (op.cls || "") + " c3-ext-" + it[1], "text-anchor": anchor },
                fmt(p.v));
      root.append(t);
    });
  }

  // ---- morph: ease between the old and the new data ----------------------------------------

  var MORPH_MAX = 900;

  function snapshot(root) {
    var snap = {};
    if (!root || reduced()) return snap;
    [].forEach.call(root.querySelectorAll(".ss-fig[data-key]"), function (sec) {
      var key = sec.getAttribute("data-key");
      [].forEach.call(sec.querySelectorAll("svg.ss-svg"), function (svg, si) {
        var els = svg.querySelectorAll("[data-m]");
        if (els.length > MORPH_MAX) return;
        var vb = svg.viewBox && svg.viewBox.baseVal ? svg.viewBox.baseVal.width : 0;
        [].forEach.call(els, function (el) {
          var bb;
          try { bb = el.getBBox(); } catch (e) { return; }
          snap[key + "|" + si + "|" + el.getAttribute("data-m")] = {
            x: bb.x, y: bb.y, w: bb.width, h: bb.height, d: el.getAttribute("d"), vb: vb, cls: el.getAttribute("class") };
        });
      });
    });
    return snap;
  }

  function nums(d) { return (d.match(/-?\d*\.?\d+/g) || []).map(Number); }
  function skeletonOf(d) { return d.replace(/-?\d*\.?\d+/g, "#"); }
  function tweenPath(el, from, to, ms) {
    var a = nums(from), b = nums(to);
    var tpl = to.split(/-?\d*\.?\d+/);
    var t0 = null;
    function step(ts) {
      if (t0 === null) t0 = ts;
      var k = Math.min(1, (ts - t0) / ms);
      var e = 1 - Math.pow(1 - k, 3);
      var out = tpl[0];
      for (var i = 0; i < b.length; i++) out += (a[i] + (b[i] - a[i]) * e).toFixed(1) + tpl[i + 1];
      el.setAttribute("d", k >= 1 ? to : out);
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function morph(root, snap) {
    if (!root || reduced() || !snap || !Object.keys(snap).length || typeof Element.prototype.animate !== "function") return 0;
    var moved = 0;
    var ease = "cubic-bezier(0.2, 0.7, 0.2, 1)";
    var MS = 520;
    [].forEach.call(root.querySelectorAll(".ss-fig[data-key]"), function (sec) {
      var key = sec.getAttribute("data-key");
      var any = false;
      [].forEach.call(sec.querySelectorAll("svg.ss-svg"), function (svg, si) {
        var els = svg.querySelectorAll("[data-m]");
        if (els.length > MORPH_MAX) return;
        var vb = svg.viewBox && svg.viewBox.baseVal ? svg.viewBox.baseVal.width : 0;
        [].forEach.call(els, function (el) {
          var old = snap[key + "|" + si + "|" + el.getAttribute("data-m")];
          if (!old || old.vb !== vb) return;
          var bb;
          try { bb = el.getBBox(); } catch (e) { return; }
          var cl = el.classList;
          if (cl.contains("ss-vb") || cl.contains("ss-hb")) {
            var v = cl.contains("ss-vb");
            var o = v ? old.h : old.w, n = v ? bb.height : bb.width;
            if (!(n > 0)) return;
            var from = o > 0 ? o / n : 0;
            if (Math.abs(from - 1) < 0.01) return;
            el.animate([{ transform: v ? "scaleY(" + from + ")" : "scaleX(" + from + ")" }, { transform: "none" }], { duration: MS, easing: ease });
            any = true; moved += 1;
          } else if (cl.contains("ss-dot")) {
            var dx = old.x - bb.x, dy = old.y - bb.y;
            if (Math.abs(dx) + Math.abs(dy) < 0.5) return;
            el.animate([{ transform: "translate(" + dx + "px," + dy + "px)" }, { transform: "none" }], { duration: MS, easing: ease });
            any = true; moved += 1;
          } else if (el.nodeName === "path" && (cl.contains("ss-line") || cl.contains("c3-area"))) {
            var nd = el.getAttribute("d");
            if (old.d && nd && old.d !== nd && skeletonOf(old.d) === skeletonOf(nd)) { tweenPath(el, old.d, nd, MS); any = true; moved += 1; }
            else if (old.d !== nd) { el.animate([{ opacity: 0.15 }, { opacity: 1 }], { duration: MS, easing: ease }); any = true; moved += 1; }
          } else if (cl.contains("ss-cell")) {
            if (old.cls !== el.getAttribute("class")) { el.animate([{ opacity: 0.25 }, { opacity: 1 }], { duration: 360, easing: ease }); any = true; moved += 1; }
          }
        });
      });
      if (any) sec.classList.add("c3-morph");     // no draw-in on top of the morph
    });
    return moved;
  }

  // ---- calendar heat-map (GitHub-style day grid) --------------------------------------------

  var MONTHS = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.", "nov.", "dec."];
  var WD = ["L", "", "Mi", "", "V", "", "D"];

  function isoDate(d) {
    return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2);
  }

  // o: {days:[{key, …}], width, title, desc, cellClass(day|null) -> class, tipOf(day, key) -> text, maxWeeks}
  function calendar(host, o) {
    var byKey = {};
    o.days.forEach(function (x) { byKey[x.key] = x; });
    var keys = Object.keys(byKey).sort();
    if (!keys.length) return null;
    var first = new Date(keys[0] + "T12:00:00");
    var last = new Date(keys[keys.length - 1] + "T12:00:00");
    var wd0 = (first.getDay() + 6) % 7;                       // Monday = 0
    var start = new Date(first.getTime() - wd0 * 86400000);
    var weeks = Math.ceil(((last - start) / 86400000 + 1) / 7);
    var maxW = o.maxWeeks || 26;
    if (weeks > maxW) { start = new Date(start.getTime() + (weeks - maxW) * 7 * 86400000); weeks = maxW; }
    var W = Math.max(260, o.width || host.clientWidth || 320);
    var L = 22, T = 18;
    var pitch = clamp(Math.floor((W - L - 2) / weeks), 11, 32);
    var size = pitch - 3;
    var H = T + 7 * pitch + 2;
    var wTotal = L + weeks * pitch + 2;
    var id = uid("cal");
    var root = s("svg", { viewBox: "0 0 " + wTotal + " " + H, width: wTotal, height: H, class: "ss-svg c3-cal", role: "img",
                          "aria-labelledby": id + "-t " + id + "-d", "data-kind": "unit" });
    root.append(s("title", { id: id + "-t" }, o.title));
    root.append(s("desc", { id: id + "-d" }, o.desc));
    WD.forEach(function (t, r) {
      if (t) root.append(s("text", { x: L - 5, y: (T + r * pitch + size / 2 + 3.5).toFixed(1), class: "ss-tick ss-tick-y" }, t));
    });
    var lastMonth = -1;
    for (var w = 0; w < weeks; w++) {
      for (var r = 0; r < 7; r++) {
        var dt = new Date(start.getTime() + (w * 7 + r) * 86400000);
        if (dt < first || dt > last) continue;
        var key = isoDate(dt);
        var x = L + w * pitch, y = T + r * pitch;
        if (dt.getDate() <= 7 && r === 0 || (w === 0 && r === wd0 && dt.getMonth() !== lastMonth)) {
          if (dt.getMonth() !== lastMonth) {
            lastMonth = dt.getMonth();
            root.append(s("text", { x: x.toFixed(1), y: 11, class: "ss-tick c3-month" }, MONTHS[lastMonth]));
          }
        }
        var day = byKey[key] || null;
        var g = s("g", { class: "ss-mark" });
        g.append(s("rect", { x: x.toFixed(1), y: y.toFixed(1), width: size, height: size, rx: 3, class: "ss-cell " + o.cellClass(day),
                             "data-m": "c" + key }));
        g.append(s("title", {}, o.tipOf(day, key)));
        root.append(g);
      }
    }
    host.append(root);
    return root;
  }

  // The „Cum arată fiecare zi?” figure of Statistici (Beta 1.28): one calendar per board, coloured like the
  // hour × weekday map (mean read delay, darker = later). Only with a week of data. `x` = helpers of
  // statistici.js (figure, multiples, dataTable, formatters) so the page file stays small.
  function calendarFigure(x) {
    var d = x.d, boards = x.boards, p = d.params;
    var keys = {};
    boards.forEach(function (b) { (d.daily[b] || []).forEach(function (r) { keys[r.key] = true; }); });
    if (Object.keys(keys).length < 7) return;
    var f = x.figure({ title: "Cum arată fiecare zi?", set: "daily", wide: true, key: "calendar", legend: x.legend,
      how: "fiecare pătrat este o zi de serviciu, pe coloane de câte o săptămână (luni sus, duminică jos); cu cât culoarea e mai " +
        "închisă, cu atât întârzierea medie citită în ziua aceea a fost mai mare. Pătratele gri au sub " + p.min_sample +
        " călătorii cu întârziere citită; cele cu contur au călătorii, dar fără întârziere citită; cele goale n-au nicio călătorie." });
    var cells = x.multiples(f.host, boards.length);
    var rows = [];
    boards.forEach(function (b, bi) {
      var cell = cells[bi];
      var hd = x.el("h3", "ss-mult-h");
      hd.append(x.el("span", "ss-key " + (b === "arrival" ? "ss-arr" : "ss-dep")), document.createTextNode(x.BOARD_PL[b]));
      cell.append(hd);
      var list = d.daily[b] || [];
      if (!list.length) { cell.append(x.el("p", "ss-empty", "Nicio zi cu date.")); return; }
      calendar(cell, { days: list, width: x.width(cell),
        title: "Întârzierea medie pe zile — " + x.BOARD_PL[b],
        desc: "Calendar: câte un pătrat pe zi de serviciu, colorat după întârzierea medie citită; pătratele gri au eșantion mic.",
        cellClass: x.heatClass,
        tipOf: function (r, key) {
          return x.BOARD_PL[b] + ", " + x.dayText(key) + ": " + (!r ? "nicio călătorie" : !r.n ?
            x.plural(r.journeys, "călătorie", "călătorii") + ", nicio întârziere citită (N = 0)" :
            "medie " + x.minutes(r.mean) + ", mediana " + x.minutes(r.median) + ", N = " + r.n +
            (r.sufficient ? ", la timp " + x.pct(r.on_time_pct) : " (eșantion mic)"));
        } });
      list.forEach(function (r) { rows.push([x.BOARD_PL[b] + ", " + x.dayText(r.key), r.journeys, r.n, x.minutes(r.mean), x.minutes(r.median), x.pct(r.on_time_pct)]); });
    });
    f.foot.append(x.nLine("Fiecare zi apare în tabel (" + rows.length + " rânduri); procentele lipsesc sub " + p.min_sample + " călătorii."));
    f.foot.append(x.dataTable("Întârzierea pe zile (calendar)", ["Panou, ziua", "Călătorii", "N", "Medie", "Mediană", "% la timp"], rows));
  }

  // Default chips for #statistici: one per main block, in page order
  function statisticiItems(body) {
    var figBy = function (txt) {
      return [].filter.call(body.querySelectorAll(".ss-fig"), function (f) {
        var t = f.querySelector(".ss-fig-title");
        return t && t.textContent.indexOf(txt) === 0;
      })[0];
    };
    var parts = body.querySelectorAll(".ss-part");
    var list = [
      ["Probleme", body.querySelector(".ss-problems")], ["Ce merge bine", body.querySelector(".ss-good")],
      ["În detaliu", parts[0]], ["Cifre", body.querySelector(".ss-hero-strip")],
      ["Distribuție", figBy("Cât de mult")], ["Împărțire", figBy("Cum se împart")], ["Zile", figBy("Cum a evoluat")],
      ["Calendar", figBy("Cum arată")], ["Ore", figBy("La ce oră")], ["Hartă", figBy("Ce zile și ore")],
      ["Operatori", figBy("Care operatori")], ["Rute", figBy("Ce rute")], ["Vreme", figBy("Vremea")],
      ["Trafic", figBy("Când e gara")], ["Calitate", figBy("Cât de bune")]];
    return list.filter(function (r) { return r[1]; }).map(function (r) { return { label: r[0], el: r[1] }; })
      .sort(function (a, b) { return a.el.compareDocumentPosition(b.el) & 4 ? -1 : 1; });
  }

  // ---- enhance: one pass over a rendered page ---------------------------------------------

  // o: {url: function(key) -> absolute URL for „Copiază linkul”}
  function enhance(root, o) {
    if (!root) return;
    ensureDefs();
    [].forEach.call(root.querySelectorAll(".ss-fig"), function (sec) {
      [].forEach.call(sec.querySelectorAll("svg.ss-svg, svg.st-chart"), bind);
      legend(sec);
      var key = sec.getAttribute("data-key");
      if (key) tools(sec, { key: key, url: o && o.url });
    });
    [].forEach.call(root.querySelectorAll("svg.st-chart, svg.ss-svg"), bind);
  }

  App.charts3 = { bind: bind, legend: legend, tools: tools, toc: toc, snapshot: snapshot, morph: morph, calendar: calendar, calendarFigure: calendarFigure,
                  smooth: smooth, areaPath: areaPath, refLine: refLine, lineRefs: lineRefs, focusKey: focusKey, colMax: colMax, extremes: extremes, enhance: enhance,
                  openFullscreen: openFullscreen, parseTip: parseTip, ensureDefs: ensureDefs, reduced: reduced, fmt: nf };
})();
