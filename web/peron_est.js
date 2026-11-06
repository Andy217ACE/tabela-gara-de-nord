// © 2026 Andy217Ace
// Coloana „Peron estimat" din tabela principală (carduri Sosiri/Plecări). Comutator implicit
// OPRIT. Valoarea e o ESTIMARE din istoricul observat (GET /api/predict/peron), nu informație
// oficială CFR; apare doar peste pragul din backtest, altfel „—". DOM doar cu
// createElement/textContent (CSP), fără stiluri inline; localStorage în try/catch.
"use strict";

(function () {
  var KEY = "tabela.peronEst";
  var REFRESH_MS = 300000;
  var NOTICE = "estimare din istoricul observat, nu informație oficială CFR";
  var info = new WeakMap();   // li -> { t, board, cell, val }
  var estimates = new Map();  // cheie tren -> { platform, n, share_pct }
  var backtest = null;
  var enabled = false;
  var timer = null;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function $(id) { return document.getElementById(id); }

  function load() {
    try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; }
  }
  function store(on) {
    try { localStorage.setItem(KEY, on ? "1" : "0"); } catch (e) { /* storage indisponibil */ }
  }

  function keyOf(board, t) {
    return [board, t.train_no, t.station || "", t.sched_time || "", t.service_date || ""].join("|");
  }

  function announced(t) { return t.platform != null && t.platform !== ""; }

  // estimarea unui tren (null: oprit, peron deja anunțat sau sub prag)
  function lookup(board, t) {
    if (!enabled || announced(t)) return null;
    return estimates.get(keyOf(board, t)) || null;
  }

  function labelOf(est) {
    return est
      ? "Peron estimat " + est.platform + ", încredere " + est.share_pct + "% din " + est.n +
        " observații; " + NOTICE
      : "Peron estimat indisponibil; " + NOTICE;
  }

  function render(rec) {
    var cell = rec.cell;
    cell.hidden = !enabled;
    if (!enabled) return;
    var est = lookup(rec.board, rec.t);
    rec.val.textContent = est ? est.platform + " · " + est.share_pct + "%" : "—";
    rec.val.classList.toggle("pe-none", !est);
    var label = labelOf(est);
    cell.setAttribute("aria-label", label);
    cell.title = label;
  }

  function renderAll() {
    document.querySelectorAll("#boards .train").forEach(function (li) {
      var rec = info.get(li);
      if (rec) render(rec);
    });
    var box = $("pe-toggle");
    if (box && box.checked !== enabled) box.checked = enabled;
    var boards = $("boards");
    if (boards) boards.classList.toggle("pe-on", enabled);
    var note = $("pe-note");
    if (note) {
      note.hidden = !enabled;
      var s = "Peron estimat: " + NOTICE + ".";
      if (backtest) {
        s += " În testul pe istoric, estimările afișate (cel puțin 5 observații, același peron" +
          " în cel puțin 80% din ele) au fost corecte în ~" + backtest.accuracy_pct +
          "% din cazuri (" + backtest.n + " cazuri). Nu e o garanție.";
      }
      note.textContent = s;
    }
  }

  function onCard(li, t, board) {
    var rec = info.get(li);
    if (!rec) {
      var cell = el("div", "pe-cell");
      var label = el("span", "pe-label", "peron estimat");
      label.setAttribute("aria-hidden", "true");
      var val = el("span", "pe-val", "—");
      cell.append(label, val);
      cell.hidden = true;
      li.append(cell);
      rec = { t: t, board: board, cell: cell, val: val };
      info.set(li, rec);
    }
    rec.t = t;
    rec.board = board;
    render(rec);
  }

  function ingest(d) {
    estimates = new Map();
    backtest = d && d.backtest ? d.backtest : null;
    var all = (d && d.estimates) || {};
    ["arrivals", "departures"].forEach(function (board) {
      (all[board] || []).forEach(function (e) {
        estimates.set(keyOf(board, e), e);
      });
    });
  }

  function refresh() {
    if (!enabled) return;
    fetch("/api/predict/peron", { cache: "no-store", headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then(ingest, function () { ingest(null); })
      .then(changed);
  }

  // cardurile se actualizează aici; panoul (panel.js) ascultă evenimentul
  function changed() {
    renderAll();
    document.dispatchEvent(new CustomEvent("tabela:peronest"));
  }

  function setEnabled(on) {
    if (enabled === on && (timer !== null || !on)) return;
    enabled = on;
    clearInterval(timer);
    timer = null;
    store(on);
    changed();
    if (on) {
      refresh();
      timer = setInterval(refresh, REFRESH_MS);
    }
  }

  function init() {
    var box = $("pe-toggle");
    if (!box) return;
    box.checked = box.checked || load();   // încărcat lazy: utilizatorul poate fi apăsat deja
    box.addEventListener("change", function () { setEnabled(box.checked); });
    if (box.checked) setEnabled(true);
  }

  window.TabelaApp = window.TabelaApp || {};
  window.TabelaApp.peronEst = {
    enabled: function () { return enabled; },
    set: setEnabled,
    lookup: lookup,
    label: labelOf
  };
  window.TabelaApp.onCard = onCard;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
