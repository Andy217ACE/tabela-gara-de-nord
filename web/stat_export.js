// © 2026 Andy217Ace
// Statistici v3, sub-proiectul 4 (export și performanță) — strat lazy (stat_export.js + stat_export.css, nu în
// precache; statistici.js îl încarcă înaintea primei afișări): export CSV (virgulă, UTF-8 cu BOM) și PNG
// (SVG serializat, desenat pe canvas, fără librării) pe fiecare grafic și tabel, „Tipărește” (@media print,
// PDF din browser) și indicatorul „Date actualizate acum X minute” (reîmprospătat la 60 s).
// Textul vine din date doar prin textContent (CSP, fără innerHTML). Fără acest strat pagina rămâne completă.
"use strict";

(function () {
  var App = window.TabelaApp;
  var BOM = "\uFEFF";
  var PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap", "stroke-linejoin", "opacity",
    "fill-opacity", "stroke-opacity", "font-family", "font-size", "font-weight", "text-anchor", "dominant-baseline"];

  function tr(key, vars) { return window.I18N.t(key, vars); }

  function mk(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // ---- CSV ---------------------------------------------------------------------------------
  function field(v) {
    var s = v == null ? "" : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  // rows: array of arrays. Separator comma, CRLF lines, BOM so that Excel reads UTF-8.
  function toCsv(rows) {
    return BOM + rows.map(function (r) { return r.map(field).join(","); }).join("\r\n") + "\r\n";
  }

  function tableRows(table) {
    var rows = [];
    table.querySelectorAll("tr").forEach(function (r) {
      var cells = [].map.call(r.children, function (c) { return c.textContent.replace(/\s+/g, " ").trim(); });
      if (cells.length) rows.push(cells);
    });
    return rows;
  }

  function save(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.style.display = "none";
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }

  function fileName(base, ext) {
    var d = new Date();
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    var slug = String(base || "statistici").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "statistici";
    return "tabela-" + slug + "-" + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "." + ext;
  }

  // ---- PNG ---------------------------------------------------------------------------------
  // Colors and fonts come from CSS classes/variables: copy the computed values into a clone before serializing.
  function inlineStyles(src, dst) {
    var cs = getComputedStyle(src);
    var st = dst.style;
    PROPS.forEach(function (p) { var val = cs.getPropertyValue(p); if (val) st.setProperty(p, val); });
    for (var i = 0; i < src.children.length; i++) inlineStyles(src.children[i], dst.children[i]);
  }

  function svgImage(svg) {
    var box = svg.getBoundingClientRect();
    var w = Math.max(1, Math.round(box.width)), h = Math.max(1, Math.round(box.height));
    var clone = svg.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", w);
    clone.setAttribute("height", h);
    inlineStyles(svg, clone);
    var xml = new XMLSerializer().serializeToString(clone);
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve({ img: img, w: w, h: h }); };
      img.onerror = function () { reject(new Error("svg")); };
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
    });
  }

  // Every chart of the figure, stacked on a canvas with the page background.
  function toPng(svgs) {
    return Promise.all(svgs.map(svgImage)).then(function (imgs) {
      var scale = 2, gap = 12;
      var w = Math.max.apply(null, imgs.map(function (i) { return i.w; }));
      var h = imgs.reduce(function (s, i) { return s + i.h + gap; }, gap);
      var cv = document.createElement("canvas");
      cv.width = w * scale;
      cv.height = h * scale;
      var ctx = cv.getContext("2d");
      ctx.scale(scale, scale);
      ctx.fillStyle = getComputedStyle(document.body).backgroundColor || "#fff";
      ctx.fillRect(0, 0, w, h);
      var y = gap;
      imgs.forEach(function (i) { ctx.drawImage(i.img, 0, y, i.w, i.h); y += i.h + gap; });
      return new Promise(function (resolve, reject) {
        try { cv.toBlob(function (b) { if (b) resolve(b); else reject(new Error("blob")); }, "image/png"); } catch (e) { reject(e); }
      });
    });
  }

  // ---- buttons -----------------------------------------------------------------------------
  function msgNode(host) {
    var m = host.querySelector(".ss-exp-msg");
    if (!m) {
      m = mk("p", "st-warn ss-warn ss-exp-msg");
      m.setAttribute("role", "status");
      m.hidden = true;
      host.append(m);
    }
    return m;
  }

  function say(host, key) {
    var m = msgNode(host);
    m.textContent = key ? tr(key) : "";
    m.hidden = !key;
    return m;
  }

  function btn(label, aria, onClick) {
    var b = mk("button", "btn btn-ghost btn-sm ss-exp-btn", label);
    b.type = "button";
    b.setAttribute("aria-label", aria);
    b.addEventListener("click", onClick);
    return b;
  }

  function csvButton(host, table, name, title) {
    return btn(tr("stats.sp4.csv"), tr("stats.sp4.csv") + ": " + title, function () {
      var rows = tableRows(table);
      if (rows.length < 2) { say(host, "stats.sp4.empty"); return; }   // header only: nothing to export
      say(host, "");
      save(new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" }), fileName(name, "csv"));
    });
  }

  function pngButton(host, svgs, table, name, title) {
    return btn(tr("stats.sp4.png"), tr("stats.sp4.png") + ": " + title, function () {
      say(host, "");
      toPng(svgs).then(function (blob) { save(blob, fileName(name, "png")); }).catch(function () {
        var m = say(host, "stats.sp4.png_failed");   // PNG failed: the CSV is offered instead
        if (table && !m.querySelector(".ss-exp-btn")) m.append(" ", csvButton(host, table, name, title));
      });
    });
  }

  function decorate(sec) {
    if (sec.querySelector(".ss-exp-btns")) return;
    var head = sec.querySelector(".ss-fig-head");
    if (!head) return;
    var title = (head.querySelector("h2") || head).textContent.trim();
    var name = sec.getAttribute("data-key") || title;
    var table = sec.querySelector("table");
    var svgs = [].slice.call(sec.querySelectorAll(".ss-chart svg"));
    if (!table && !svgs.length) return;
    var box = mk("span", "ss-exp-btns");
    if (table) box.append(csvButton(sec, table, name, title));
    if (svgs.length) box.append(pngButton(sec, svgs, table, name, title));
    head.append(box);
  }

  // Print: the „Vezi datele” tables are opened for the paper and closed again afterwards.
  var reopen = [];
  function printOpen() {
    reopen = [].filter.call(document.querySelectorAll("#st-statistici details.ss-data"), function (d) { return !d.open; });
    reopen.forEach(function (d) { d.open = true; });
  }
  function printClose() {
    reopen.forEach(function (d) { d.open = false; });
    reopen = [];
  }
  window.addEventListener("beforeprint", printOpen);
  window.addEventListener("afterprint", printClose);

  function printButton(ui) {
    if (ui.form.querySelector(".ss-sp4-print")) return;
    var b = btn(tr("stats.sp4.print"), tr("stats.sp4.print"), function () { window.print(); });
    b.classList.add("ss-sp4-print");
    ui.form.append(b);
  }

  // "Date actualizate acum X minute": from the payload time, refreshed every 60 s while the page is open.
  var stamp = 0, note = null, timer = 0;
  function paint() {
    if (!note || !note.isConnected) {   // the page was rebuilt (language switch): stop the old timer
      if (timer) clearInterval(timer);
      timer = 0;
      return;
    }
    var min = Math.max(0, Math.floor((Date.now() - stamp) / 60000));
    note.textContent = min < 1 ? tr("stats.sp4.updated_now") : tr("stats.sp4.updated_min", { n: min });
  }

  function updated(ui, d, at) {
    var t = d && d.generated_at ? Date.parse(d.generated_at) : NaN;
    stamp = isNaN(t) ? (at || Date.now()) : t;
    if (stamp > Date.now()) stamp = Date.now();   // a server clock ahead of the browser
    note = ui.form.querySelector(".ss-sp4-updated");
    if (!note) {
      note = mk("p", "ss-sp4-updated");
      note.setAttribute("role", "status");
      ui.form.append(note);
    }
    paint();
    if (!timer) timer = setInterval(paint, 60000);
  }

  function enhance(ui, d, at) {
    updated(ui, d, at);
    printButton(ui);
    ui.body.querySelectorAll(".ss-fig").forEach(decorate);
  }

  // Sections with their own endpoint (platform changes, dwell) run at the first visit, not at render.
  function lazy(x, body, p) {
    var box = mk("div", "ss-lazy"), done = false, io = null;
    body.append(box);
    function run() {
      if (done) return;
      done = true;
      if (io) io.disconnect();
      window.removeEventListener("scroll", near);
      x(box, p);
    }
    function near() {   // a jump past the box (End key, anchor) never makes it "intersecting": the scroll position decides too
      if (!box.isConnected) window.removeEventListener("scroll", near);
      // getClientRects: a box in a closed group (phones) is display:none, its rect top is 0
      else if (box.getClientRects().length && box.getBoundingClientRect().top < window.innerHeight + 100) run();
    }
    if (!window.IntersectionObserver) { run(); return; }
    io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) run(); }, { rootMargin: "100px" });
    io.observe(box);
    window.addEventListener("scroll", near, { passive: true });
  }

  App.statExport = { enhance: enhance, lazy: lazy, toCsv: toCsv, tableRows: tableRows };
})();
