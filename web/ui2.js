// © 2026 Andy217Ace
// Tabela Gara de Nord — „UI v2” (Beta 1.26): helpers shared by the pages that are not the live
// board (Istoric, Urmărite, Trenuri, Tren, Statistici, Clasamente, Stații, Stație, Versiuni).
// Self-hosted, no library: SVG + CSS only (CSP: script-src 'self', no inline styles — every
// value is an SVG attribute or a CSS class). Exposes App.ui2:
//   donut(host, o)     part-to-whole chart: ring + centre figure + legend, hover/focus tooltips
//   countUp(node, v, fmt)  number that counts up once it is on screen (not with reduced motion)
//   meter(pct, o)      thin proportion bar (SVG), spark(values, o)  inline line (SVG)
//   skeleton(kind)     shimmer placeholders; enterView(section)  page-enter animation
//   decorate()         icon chip in every page header; stagger(list)  staggered rise
// Beta 1.28: gauge(pct, o), empty(o), transition(fn) (View Transitions), charts() (lazy charts3.js/css)
// Rules kept: N next to every figure, missing is „—” never 0, colour is never the only carrier
// (labels in the legend, a pattern per slice), prefers-reduced-motion switches motion off.
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  var SVG_NS = "http://www.w3.org/2000/svg";
  var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var nf1 = new Intl.NumberFormat("ro-RO", { maximumFractionDigits: 1 });
  var nf0 = new Intl.NumberFormat("ro-RO", { maximumFractionDigits: 0 });
  var seq = 0;

  function reduced() { return !!(mq && mq.matches); }
  function uid(p) { seq += 1; return "ui-" + p + "-" + seq; }

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

  // ---- count-up ------------------------------------------------------------------------

  // The final text is always in the DOM first (screen readers, no-JS, print, a node below the
  // fold). When motion is allowed and the node is on screen at its first paint, it counts
  // 0 → value once; a node that is not on screen is simply left at its final value.
  function countUp(node, to, fmt, ms) {
    var f = fmt || function (x) { return nf0.format(x); };
    var final = f(to);
    node.textContent = final;
    node.setAttribute("data-final", final);
    if (reduced() || !(to > 0) || typeof IntersectionObserver === "undefined" ||
        typeof requestAnimationFrame === "undefined") return node;
    var io = new IntersectionObserver(function (entries) {
      io.disconnect();
      if (!entries[0].isIntersecting) return;
      var t0 = null;
      var dur = ms || 900;
      var step = function (ts) {
        if (t0 === null) t0 = ts;
        var k = Math.min(1, (ts - t0) / dur);
        node.textContent = k >= 1 ? final : f(to * (1 - Math.pow(1 - k, 3)));
        if (k < 1) requestAnimationFrame(step);
      };
      node.textContent = f(0);
      requestAnimationFrame(step);
    }, { threshold: 0.25 });
    io.observe(node);
    return node;
  }

  // ---- donut / pie ---------------------------------------------------------------------

  var CX = 50, CY = 50, R = 36, SW = 15;
  var GAP = 0.8;          // visual gap between slices, in % of the ring
  var MIN_SLICE = 1.4;    // a real but tiny slice stays visible
  var PAT_COUNT = 4;      // none, diagonal lines, dots, crosshatch — one per slice position

  function patternDefs(id) {
    var defs = s("defs");
    [["l", "M-1,5 L5,-1 M3,5 L5,3 M-1,1 L1,-1"], ["x", "M0,2 L4,2 M2,0 L2,4"]].forEach(function (p) {
      var pat = s("pattern", { id: id + "-p" + p[0], width: 4, height: 4, patternUnits: "userSpaceOnUse", class: "ui-pat" });
      pat.append(s("path", { d: p[1] }));
      defs.append(pat);
    });
    var dots = s("pattern", { id: id + "-pd", width: 4, height: 4, patternUnits: "userSpaceOnUse", class: "ui-pat ui-pat-dot" });
    dots.append(s("circle", { cx: 2, cy: 2, r: 0.9 }));
    defs.append(dots);
    return defs;
  }
  function patternRef(id, i) {
    var k = i % PAT_COUNT;
    return k === 0 ? null : "url(#" + id + "-p" + (k === 1 ? "l" : k === 2 ? "d" : "x") + ")";
  }

  function fmtPct(v) { return nf1.format(v) + " %"; }

  // o: {title, desc, segments:[{key,label,value,slot,sub}], total?, centerValue, centerLabel,
  //     showPct (default true), valueUnit ("călătorii"), id}
  // slot = categorical slot 1..6 (colour --cat-N), or "other"/"ok"/"mid"/"bad"/"arr"/"dep"/"mute".
  function donut(host, o) {
    var segs = (o.segments || []).map(function (x) { return x; });
    var total = o.total != null ? o.total : segs.reduce(function (a, x) { return a + (x.value || 0); }, 0);
    var showPct = o.showPct !== false && total > 0;
    var id = uid("dn");
    var box = h("figure", "ui-donut");
    var plot = h("div", "ui-donut-plot");
    var svg = s("svg", { viewBox: "0 0 100 100", class: "ui-donut-svg", role: "img",
                         "aria-labelledby": id + "-t " + id + "-d" });
    svg.append(s("title", { id: id + "-t" }, o.title));
    svg.append(s("desc", { id: id + "-d" }, o.desc || o.title));
    svg.append(patternDefs(id));
    var mask = s("mask", { id: id + "-m", maskUnits: "userSpaceOnUse", x: 0, y: 0, width: 100, height: 100 });
    mask.append(s("circle", { class: "ui-sweep", cx: CX, cy: CY, r: R, pathLength: 100, "stroke-dasharray": "100 100",
                              "stroke-dashoffset": 0, "stroke-width": SW + 10 }));
    svg.append(mask);
    svg.append(s("circle", { class: "ui-ring", cx: CX, cy: CY, r: R, "stroke-width": SW }));
    var g = s("g", { transform: "rotate(-90 " + CX + " " + CY + ")", mask: "url(#" + id + "-m)" });
    var arcs = [];
    var acc = 0;
    segs.forEach(function (x, i) {
      var len = total > 0 ? (100 * (x.value || 0)) / total : 0;
      x.pct = len;
      if (!(x.value > 0)) { arcs.push(null); return; }
      var drawn = Math.max(MIN_SLICE, len);
      var gap = segs.length > 1 && len < 99.9 ? GAP : 0;
      var dash = Math.max(0.2, drawn - gap);
      var attrs = { class: "ui-seg ui-c-" + (x.slot || (i + 1)), cx: CX, cy: CY, r: R, "stroke-width": SW, pathLength: 100,
                    "stroke-dasharray": dash.toFixed(2) + " " + (100 - dash).toFixed(2),
                    "stroke-dashoffset": (-(acc + gap / 2)).toFixed(2) };
      var arc = s("circle", attrs);
      g.append(arc);
      var pr = patternRef(id, i);
      var over = null;
      if (pr) {
        over = s("circle", { class: "ui-seg-pat", cx: CX, cy: CY, r: R, "stroke-width": SW, pathLength: 100, stroke: pr,
                             "stroke-dasharray": attrs["stroke-dasharray"], "stroke-dashoffset": attrs["stroke-dashoffset"] });
        g.append(over);
      }
      arcs.push({ arc: arc, over: over });
      acc += len;
    });
    svg.append(g);
    // share printed on slices that are wide enough
    if (showPct) {
      var lab = s("g", { class: "ui-seg-labs", "aria-hidden": "true" });
      var from = 0;
      segs.forEach(function (x) {
        var len = x.pct || 0;
        if (len >= 9) {
          var ang = ((from + len / 2) / 100) * 2 * Math.PI - Math.PI / 2;
          lab.append(s("text", { class: "ui-seg-lab", x: (CX + R * Math.cos(ang)).toFixed(1), y: (CY + R * Math.sin(ang)).toFixed(1) },
                       nf0.format(len) + "%"));
        }
        from += len;
      });
      if (lab.childNodes.length) svg.append(lab);
    }
    plot.append(svg);

    var centre = h("div", "ui-dc");
    var cv = h("span", "ui-dc-v");
    var cl = h("span", "ui-dc-l");
    var cs = h("span", "ui-dc-s");
    centre.append(cv, cl, cs);
    plot.append(centre);
    box.append(plot);

    var legend = h("ul", "ui-legend");
    var items = [];
    var unit = o.valueUnit || "";
    segs.forEach(function (x, i) {
      var li = h("li", "ui-leg-item");
      li.setAttribute("tabindex", i === 0 ? "0" : "-1");   // one tab stop per chart, arrows move inside
      var txt = x.label + ": " + nf0.format(x.value || 0) + (unit ? " " + unit : "") +
        (showPct && x.value > 0 ? " (" + fmtPct(x.pct) + ")" : "");
      li.setAttribute("aria-label", txt);
      var sw = h("span", "ui-sw ui-c-" + (x.slot || (i + 1)) + " ui-pat-" + (i % PAT_COUNT));
      sw.setAttribute("aria-hidden", "true");
      var lab = h("span", "ui-leg-l", x.label);
      var val = h("span", "ui-leg-v", nf0.format(x.value || 0));
      li.append(sw, lab, val);
      if (showPct) li.append(h("span", "ui-leg-p", x.value > 0 ? fmtPct(x.pct) : "—"));
      legend.append(li);
      items.push(li);
    });
    box.append(legend);

    function rest() {
      box.classList.remove("has-active");
      cv.textContent = o.centerValue != null ? o.centerValue : nf0.format(total);
      cl.textContent = o.centerLabel || "";
      cs.textContent = o.centerSub || "";
      items.forEach(function (li) { li.classList.remove("is-active"); });
      arcs.forEach(function (a) { if (a) { a.arc.classList.remove("is-active"); if (a.over) a.over.classList.remove("is-active"); } });
    }
    function setActive(i) {
      rest();
      var x = segs[i];
      if (!x) return;
      box.classList.add("has-active");
      items[i].classList.add("is-active");
      if (arcs[i]) { arcs[i].arc.classList.add("is-active"); if (arcs[i].over) arcs[i].over.classList.add("is-active"); }
      cv.textContent = showPct && x.value > 0 ? fmtPct(x.pct) : nf0.format(x.value || 0);
      cl.textContent = x.label;
      cs.textContent = (showPct ? nf0.format(x.value || 0) + (unit ? " " + unit : "") : unit) + (x.sub ? " · " + x.sub : "");
    }
    items.forEach(function (li, i) {
      li.addEventListener("keydown", function (e) {
        var n = items.length, j = -1;
        if (e.key === "ArrowDown" || e.key === "ArrowRight") j = (i + 1) % n;
        else if (e.key === "ArrowUp" || e.key === "ArrowLeft") j = (i - 1 + n) % n;
        else if (e.key === "Home") j = 0;
        else if (e.key === "End") j = n - 1;
        if (j < 0) return;
        e.preventDefault();
        li.setAttribute("tabindex", "-1");
        items[j].setAttribute("tabindex", "0");
        items[j].focus();
      });
      li.addEventListener("pointerenter", function () { setActive(i); });
      li.addEventListener("focus", function () { setActive(i); });
      li.addEventListener("pointerleave", rest);
      li.addEventListener("blur", rest);
    });
    arcs.forEach(function (a, i) {
      if (!a) return;
      var enter = function () { setActive(i); };
      [a.arc, a.over].forEach(function (n) {
        if (!n) return;
        n.addEventListener("pointerenter", enter);
        n.addEventListener("pointerleave", rest);
        n.append(s("title", {}, segs[i].label + ": " + nf0.format(segs[i].value) + (unit ? " " + unit : "") +
          (showPct ? " (" + fmtPct(segs[i].pct) + ")" : "")));
      });
    });
    rest();
    host.append(box);
    return { figure: box, setActive: setActive, reset: rest };
  }

  // ---- meter, sparkline ----------------------------------------------------------------

  // pct 0..100 | null (= no figure: dashed track). tone: ok | mid | bad | acc | arr | dep
  function meter(pct, o) {
    var op = o || {};
    var root = s("svg", { viewBox: "0 0 100 8", preserveAspectRatio: "none", class: "ui-meter" + (pct == null ? " is-none" : ""),
                          role: "img", "aria-label": op.label || (pct == null ? "fără valoare" : nf1.format(pct) + " %") });
    root.append(s("rect", { class: "ui-meter-track", x: 0, y: 1, width: 100, height: 6, rx: 3 }));
    if (pct != null && pct > 0) {
      root.append(s("rect", { class: "ui-meter-fill ui-t-" + (op.tone || "acc"), x: 0, y: 1,
                              width: Math.max(1.5, Math.min(100, pct)).toFixed(1), height: 6, rx: 3 }));
    }
    return root;
  }

  // values: numbers or null (a gap); o: {w, h, label, tone}
  function spark(values, o) {
    var op = o || {};
    var W = op.w || 120, H = op.h || 32, P = 3;
    var nums = values.filter(function (v) { return v != null; });
    var root = s("svg", { viewBox: "0 0 " + W + " " + H, class: "ui-spark", role: "img",
                          "aria-label": op.label || "evoluție" });
    if (!nums.length) { root.classList.add("is-none"); return root; }
    var lo = op.min != null ? op.min : Math.min.apply(null, nums.concat([0]));
    var hi = op.max != null ? Math.max(op.max, lo + 1) : Math.max.apply(null, nums.concat([lo + 1]));
    var n = values.length;
    var x = function (i) { return n === 1 ? W / 2 : P + (i * (W - 2 * P)) / (n - 1); };
    var y = function (v) { return H - P - ((Math.min(v, hi) - lo) / (hi - lo)) * (H - 2 * P); };
    var d = "", pen = false, area = "", first = null, last = null;
    if (op.compact) root.classList.add("ui-spark-sm");
    values.forEach(function (v, i) {
      if (v == null) { pen = false; return; }
      d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1);
      pen = true;
      if (first === null) first = i;
      last = i;
    });
    if (nums.length > 1) {
      area = d + "L" + x(last).toFixed(1) + "," + (H - P) + "L" + x(first).toFixed(1) + "," + (H - P) + "Z";
      root.append(s("path", { class: "ui-spark-area ui-t-" + (op.tone || "acc"), d: area }));
    }
    root.append(s("path", { class: "ui-spark-line ui-t-" + (op.tone || "acc"), d: d, pathLength: 1 }));
    root.append(s("circle", { class: "ui-spark-dot ui-t-" + (op.tone || "acc"), cx: x(last).toFixed(1), cy: y(values[last]).toFixed(1), r: 2.6 }));
    return root;
  }

  // two-part proportion (e.g. arrivals / departures) as one thin bar: a, b = counts
  function split(a, b, o) {
    var op = o || {};
    var tot = (a || 0) + (b || 0);
    var root = s("svg", { viewBox: "0 0 100 8", preserveAspectRatio: "none", class: "ui-meter ui-split", role: "img",
                          "aria-label": op.label || ("sosiri " + (a || 0) + ", plecări " + (b || 0)) });
    root.append(s("rect", { class: "ui-meter-track", x: 0, y: 1, width: 100, height: 6, rx: 3 }));
    if (tot > 0) {
      var wa = (100 * a) / tot;
      if (a > 0) root.append(s("rect", { class: "ui-meter-fill ui-t-arr", x: 0, y: 1, width: Math.max(2, wa - 0.8).toFixed(1), height: 6, rx: 3 }));
      if (b > 0) root.append(s("rect", { class: "ui-meter-fill ui-t-dep", x: (a > 0 ? wa + 0.8 : 0).toFixed(1),
                                         y: 1, width: Math.max(2, 100 - wa - (a > 0 ? 0.8 : 0)).toFixed(1), height: 6, rx: 3 }));
    }
    return root;
  }


  // radial punctuality ring (270°): pct | null
  function gauge(pct, o) {
    var op = o || {};
    var root = s("svg", { viewBox: "0 0 56 56", class: "ui-gauge" + (pct == null ? " is-none" : ""), role: "img",
                          "aria-label": op.label || (pct == null ? "fără valoare" : nf1.format(pct) + " %") });
    var arc = { cx: 28, cy: 28, r: 22, pathLength: 100, transform: "rotate(135 28 28)" };
    root.append(s("circle", Object.assign({ class: "ui-gauge-track", "stroke-dasharray": "75 25" }, arc)));
    if (pct != null && pct > 0) {
      var v = Math.max(1.2, Math.min(100, pct)) * 0.75;
      var fill = s("circle", Object.assign({ class: "ui-gauge-fill ui-t-" + (op.tone || "arr"), "stroke-dasharray": v.toFixed(2) + " 100" }, arc));
      root.append(fill);
      if (!reduced() && fill.animate) {
        fill.animate([{ strokeDashoffset: v }, { strokeDashoffset: 0 }], { duration: 900, easing: "cubic-bezier(0.2, 0.7, 0.2, 1)" });
      }
    }
    return root;
  }

  // empty state: o {art, title, text, action:{label, run}}
  function empty(o) {
    var box = h("div", "empty ui-empty");
    box.append(art(o.art || "search"));
    box.append(h("p", "ui-empty-t", o.title));
    if (o.text) box.append(h("p", "ui-empty-s", o.text));
    if (o.action) {
      var b = h("button", "btn btn-ghost btn-sm ui-empty-a", o.action.label);
      b.type = "button";
      b.addEventListener("click", o.action.run);
      box.append(b);
    }
    return box;
  }

  // ---- hero strip: [{label, value (number|null), fmt, unit, sub, tone, meter (pct|undefined), text}] ----

  function hero(items) {
    var grid = h("div", "ui-hero");
    items.forEach(function (it) {
      var box = h("div", "ui-stat" + (it.tone ? " ui-t-" + it.tone : ""));
      box.append(h("p", "ui-stat-l", it.label));
      var num = h("p", "ui-stat-v" + (it.cls ? " " + it.cls : ""));
      var fmt = it.fmt || function (x) { return nf0.format(Math.round(x)); };
      var shown = function (x) { return fmt(x) + (it.unit || ""); };
      if (it.text != null) num.textContent = it.text;
      else if (it.value == null) num.textContent = "—";
      else countUp(num, it.value, shown);
      box.append(num);
      if (it.sub) box.append(h("p", "ui-stat-s", it.sub));
      var tone = it.tone === "dep" ? "dep" : it.tone === "ok" ? "ok" : "arr";
      if (it.meter !== undefined && it.gauge) {
        box.classList.add("has-gauge");
        box.append(gauge(it.meter, { tone: tone, label: it.label + ": " + (it.meter == null ? "fără valoare" : nf1.format(it.meter) + " %") }));
      } else if (it.meter !== undefined) box.append(meter(it.meter, { tone: it.tone === "dep" ? "dep" : it.tone === "ok" ? "ok" : "arr",
                                                               label: it.label + ": " + (it.meter == null ? "fără valoare" : nf1.format(it.meter) + " %") }));
      grid.append(box);
    });
    return grid;
  }

  // On time / late / very late for one stats object ({n, on_time, over_30, sufficient, on_time_pct})
  function delayDonut(host, st, p, label, idp) {
    var late = Math.max(0, (st.n || 0) - (st.on_time || 0) - (st.over_30 || 0));
    var ok = !!st.sufficient;
    return donut(host, { id: idp, valueUnit: "călătorii", showPct: ok,
      title: "La timp, întârziate și peste 30 min — " + label,
      desc: "Din " + st.n + " călătorii încheiate cu întârziere citită: " + st.on_time + " la timp (cel mult " + p.on_time_max_min +
        " min), " + late + " întârziate până la 30 min, " + st.over_30 + " peste 30 min.",
      centerValue: ok ? nf1.format(st.on_time_pct) + " %" : String(st.n), centerLabel: ok ? "la timp" : "călătorii (N)",
      segments: [
        { label: "la timp (≤ " + p.on_time_max_min + " min)", value: st.on_time || 0, slot: "ok" },
        { label: "întârziate " + (p.on_time_max_min + 1) + "–30 min", value: late, slot: "mid" },
        { label: "peste 30 min", value: st.over_30 || 0, slot: "bad" }] });
  }

  // small line illustrations for empty states (decorative, aria-hidden)
  var ART = {
    bell: ["M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z", "M10 20.5a2 2 0 0 0 4 0", "M3 5.5c.6-1.3 1.5-2.4 2.7-3.2M21 5.5c-.6-1.3-1.5-2.4-2.7-3.2"],
    train: ["M8 3h8a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z", "M5 10h14M9 17l-2.5 4M15 17l2.5 4", "M8.5 13.5h.01M15.5 13.5h.01"],
    search: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "M20 20l-4-4"]
  };
  function art(kind) {
    var svg = s("svg", { viewBox: "0 0 24 24", class: "ui-art", "aria-hidden": "true", focusable: "false" });
    (ART[kind] || ART.search).forEach(function (d) { svg.append(s("path", { d: d })); });
    return svg;
  }

  // ---- skeletons -----------------------------------------------------------------------

  function skeleton(kind, n) {
    var box = h("div", "ui-skel ui-skel-" + (kind || "cards"));
    box.setAttribute("aria-hidden", "true");
    var count = n || (kind === "table" ? 6 : kind === "hero" ? 3 : 3);
    for (var i = 0; i < count; i++) {
      var b = h("div", "ui-skel-block");
      if (kind === "chart") {
        for (var k = 1; k <= 8; k++) b.append(h("span", "ui-skel-bar"));
        box.append(b);
        continue;
      }
      b.append(h("span", "ui-skel-line ui-skel-w1"), h("span", "ui-skel-line ui-skel-w2"), h("span", "ui-skel-line ui-skel-w3"));
      box.append(b);
    }
    return box;
  }

  // ---- motion --------------------------------------------------------------------------

  var vt = false;
  function enterView(section) {
    if (!section || reduced() || vt) return;   // a running View Transition already animates the page
    section.classList.remove("view-enter");
    void section.offsetWidth; // restart the animation
    section.classList.add("view-enter");
    section.addEventListener("animationend", function done(e) {
      if (e.target !== section) return;
      section.classList.remove("view-enter");
      section.removeEventListener("animationend", done);
    });
  }

  // One-shot scroll reveal: what is already on screen stays as it is; what is below the fold
  // fades up the first time it comes into view (and stays). Not used with reduced motion, and
  // without IntersectionObserver nothing is ever hidden.
  var REVEAL = ".ss-fig, .ss-glossary, .ss-good, .ss-problems, .ss-part, .st-card, .st-section, .v-entry, .st-scroll, .ss-kpis, .st-cards, .h-group";
  var revealIO = null;
  function reveal(root) {
    if (!root || reduced() || typeof IntersectionObserver === "undefined") return;
    if (!revealIO) {
      revealIO = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting) return;
          e.target.classList.add("ui-rv-in");
          revealIO.unobserve(e.target);
        });
      }, { rootMargin: "0px 0px -6% 0px", threshold: 0.04 });
    }
    var vh = window.innerHeight || 800;
    var below = [];
    root.querySelectorAll(REVEAL).forEach(function (n) {
      if (n.classList.contains("ui-rv")) return;
      if (n.getBoundingClientRect().top >= vh * 0.96) below.push(n);   // already in view: leave it alone
    });
    below.forEach(function (n) { n.classList.add("ui-rv"); revealIO.observe(n); });
  }

  // route change inside a View Transition when available; else the plain call (+ the CSS page-enter)
  function transition(fn) {
    if (reduced() || typeof document.startViewTransition !== "function") { fn(); return; }
    var t;
    try {
      vt = true;
      t = document.startViewTransition(function () { fn(); });
    } catch (e) { vt = false; fn(); return; }
    var done = function () { vt = false; };
    t.finished.then(done, done);
  }

  // lazy chart layer (charts3.js/css): pages with charts only, never in the SW shell; resolves null if it can't load
  var CHARTS_V = "1.32";
  var chartsP = null;
  function charts() {
    if (App.charts3) return Promise.resolve(App.charts3);
    if (chartsP) return chartsP;
    chartsP = new Promise(function (resolve) {
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "charts3.css?v=" + CHARTS_V;
      var script = document.createElement("script");
      script.src = "charts3.js?v=" + CHARTS_V;
      var left = 2, failed = false;
      var one = function () { left -= 1; if (left === 0) resolve(failed ? null : (App.charts3 || null)); };
      link.onload = one;
      script.onload = one;
      link.onerror = script.onerror = function () { failed = true; chartsP = null; one(); };
      document.head.append(link, script);
    });
    return chartsP;
  }

  function stagger(list) {
    if (!list || reduced()) return;
    var kids = list.children;
    for (var i = 0; i < kids.length && i < 12; i++) kids[i].classList.add("ui-rise", "ui-d" + i);
  }

  // ---- page headers: an icon chip (same glyphs as the menu) -----------------------------

  var HEAD_ICONS = {
    istoric: ["M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z", "M12 7.5V12l3 2"],
    urmarite: ["M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z", "M10 20.5a2 2 0 0 0 4 0"],
    trenuri: ["M8 3h8a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z", "M5 10h14M9 17l-2.5 4M15 17l2.5 4"],
    tren: ["M8 3h8a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z", "M5 10h14M9 17l-2.5 4M15 17l2.5 4"],
    statistici: ["M4 20h16", "M7 16.5v-5M12 16.5V6M17 16.5v-8"],
    clasamente: ["M8 4h8v5a4 4 0 0 1-8 0z", "M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M8.5 20h7"],
    statii: ["M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z", "M12 7.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z"],
    statie: ["M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z", "M12 7.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z"],
    versiuni: ["M4 7.5 12 3l8 4.5v9L12 21l-8-4.5z", "M4 7.5 12 12l8-4.5M12 12v9"]
  };

  function decorate() {
    Object.keys(HEAD_ICONS).forEach(function (k) {
      var head = document.querySelector("#view-" + k + " .page-head");
      if (!head || head.querySelector(".ph-icon")) return;
      var chip = h("span", "ph-icon");
      chip.setAttribute("aria-hidden", "true");
      var svg = s("svg", { viewBox: "0 0 24 24", focusable: "false" });
      HEAD_ICONS[k].forEach(function (d) { svg.append(s("path", { d: d })); });
      chip.append(svg);
      head.prepend(chip);
    });
  }

  App.ui2 = { donut: donut, countUp: countUp, meter: meter, split: split, art: art, hero: hero, gauge: gauge, empty: empty,
              transition: transition, charts: charts, delayDonut: delayDonut, spark: spark, skeleton: skeleton,
              enterView: enterView, stagger: stagger, reveal: reveal, decorate: decorate, reduced: reduced,
              fmtPct: fmtPct, h: h, s: s };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", decorate);
  else decorate();
})();
