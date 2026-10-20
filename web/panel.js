// © 2026 Andy217Ace
// Tabela Gara de Nord — mod „Panou" (afișaj de gară). Consumă datele pe care app.js le
// publică prin evenimentul `tabela:board` (nu face un al doilea polling). DOM construit
// doar cu createElement/textContent; fără stiluri inline (CSP). Culorile vin din CSS
// (panel.css) prin atributul data-level; pragurile vin din GET /api/config.
"use strict";

(function () {
  var TZ = "Europe/Bucharest";
  var DEFAULTS = { delay_thresholds: { low: 5, mid: 15, high: 30 }, stale_after_s: 180, refresh_s: 10 };
  var CONF_MIN = 0.6;          // rânduri cu `confidence` sub prag = neconfirmate (gri)
  var RECENT_S = 120;          // „modificare recentă" (albastru) — observată de această pagină
  var BOARDS = ["arrivals", "departures"];
  var KEYS = { view: "tabela.view", board: "tabela.panel.board", cols: "tabela.panel.cols", fav: "tabela.fav" };
  var TITLES = {
    arrivals: "SOSIRI — GARA DE NORD BUCUREȘTI",
    departures: "PLECĂRI — GARA DE NORD BUCUREȘTI",
    all: "SOSIRI ȘI PLECĂRI — GARA DE NORD BUCUREȘTI"
  };
  // id, antet, se poate ascunde, implicit vizibil, cheie de sortare
  var COLS = [
    { id: "time", label: "Ora", full: "Ora programată", fixed: true, sort: "time" },
    { id: "train", label: "Tren", full: "Tren / numărul cursei", fixed: true, sort: "number" },
    { id: "station", label: "Din / spre", full: "Origine sau destinație" },
    { id: "op", label: "Operator", full: "Operator" },
    { id: "delay", label: "Întârziere", full: "Întârziere afișată", sort: "delay" },
    { id: "plat", label: "Linia", full: "Linia / peronul" },
    { id: "msg", label: "Stare", full: "Mesaj de stare" },
    { id: "changed", label: "Modificat", full: "Ultima modificare (observată aici)", off: true }
  ];
  var SVG_NS = "http://www.w3.org/2000/svg";

  var S = {
    cfg: DEFAULTS,
    data: null, failed: false, receivedAt: 0, waiting: false,
    view: "panou", board: "arrivals",
    hidden: new Set(), favs: new Set(),
    q: "", fDelay: "all", fOp: "", fPlat: "", onlyFav: false,
    sort: "time", dir: 1,
    selected: null, lastTrain: null,
    changes: new Map(),
    pseudoFs: false,
    dom: {}
  };

  // ---- helpers ---------------------------------------------------------------------

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function icon(paths) {
    var s = document.createElementNS(SVG_NS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("aria-hidden", "true");
    s.setAttribute("focusable", "false");
    s.setAttribute("class", "pnl-ico");
    paths.forEach(function (d) {
      var p = document.createElementNS(SVG_NS, "path");
      p.setAttribute("d", d);
      s.appendChild(p);
    });
    return s;
  }

  var ICONS = {
    refresh: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 4v7h-7"],
    full: ["M4 9V4h5", "M20 9V4h-5", "M4 15v5h5", "M20 15v5h-5"],
    exitFull: ["M9 4v5H4", "M15 4v5h5", "M9 20v-5H4", "M15 20v-5h5"],
    star: ["M12 3.8l2.5 5.2 5.7.8-4.1 4 1 5.6-5.1-2.7-5.1 2.7 1-5.6-4.1-4 5.7-.8z"],
    close: ["M6 6l12 12", "M18 6 6 18"],
    cols: ["M4 5h16v14H4z", "M9.5 5v14", "M14.5 5v14"],
    reset: ["M4 12a8 8 0 1 0 2.3-5.7", "M4 4v5h5"],
    history: ["M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z", "M12 7.5V12l3 2"]
  };

  function load(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function save(key, val) {
    try { localStorage.setItem(key, val); } catch (e) { /* storage indisponibil */ }
  }

  // valoare lipsă: nu o inventăm, o arătăm explicit
  function unknown(what) {
    var s = el("span", "pnl-unk", "—");
    s.setAttribute("role", "img");
    s.setAttribute("aria-label", what ? what + " necunoscut" : "necunoscut");
    s.title = what ? what + ": necunoscut" : "necunoscut";
    return s;
  }

  function norm(s) {
    return String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
  }

  function ago(sec) {
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return sec + " s";
    var min = Math.floor(sec / 60);
    if (min < 60) return min + " min";
    return Math.floor(min / 60) + " h " + (min % 60) + " min";
  }

  var fmtTime = new Intl.DateTimeFormat("ro-RO", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  var fmtHM = new Intl.DateTimeFormat("ro-RO", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
  var fmtDate = new Intl.DateTimeFormat("ro-RO", { timeZone: TZ, weekday: "long", day: "numeric", month: "long", year: "numeric" });
  var fmtISO = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });

  function todayISO() { return fmtISO.format(new Date()); }

  function trainKey(board, t) {
    return board + "|" + t.train_no + "|" + t.sched_time + "|" + (t.service_date || "");
  }

  function historyHref(t) {
    var d = t.service_date || todayISO();
    return "#istoric?train=" + encodeURIComponent(String(t.train_no)) + "&date=" + encodeURIComponent(d);
  }

  // ---- data state ------------------------------------------------------------------

  function age() {
    if (!S.data || S.data.age_s == null) return null;
    return S.data.age_s + (performance.now() - S.receivedAt) / 1000;
  }

  // live | stale | offline | none
  function freshness() {
    if (!S.data) return S.failed ? "offline" : "none";
    if (S.failed) return "offline";
    var a = age();
    if (a == null || S.data.stale || a > S.cfg.stale_after_s) return "stale";
    return "live";
  }

  // Nivelul de culoare. Niciodată „la timp" fără o întârziere citită pe un rând sigur.
  function levelOf(t) {
    if (t.uncertain === true) return "unknown";
    if (typeof t.confidence === "number" && t.confidence < CONF_MIN) return "unknown";
    var d = t.delay_min;
    if (t.delay_min == null || typeof d !== "number" || !isFinite(d) || d < 0) return "unknown";
    if (d === 0) return "ok";
    var th = S.cfg.delay_thresholds;
    if (d > th.high) return "high";
    if (d > th.mid) return "mid";
    return "low";
  }

  function hasDelay(t) { return levelOf(t) !== "unknown"; }

  function trackChanges(data) {
    var now = Date.now();
    var seen = new Set();
    BOARDS.forEach(function (b) {
      (data[b] || []).forEach(function (t) {
        var k = trainKey(b, t);
        seen.add(k);
        var sig = String(t.delay_min) + "|" + String(t.platform);
        var prev = S.changes.get(k);
        if (!prev) S.changes.set(k, { sig: sig, at: null });
        else if (prev.sig !== sig) S.changes.set(k, { sig: sig, at: now });
      });
    });
    S.changes.forEach(function (_, k) { if (!seen.has(k)) S.changes.delete(k); });
  }

  function changedAt(board, t) {
    if (t.changed_at) {
      var d = new Date(t.changed_at);
      if (!isNaN(d)) return d.getTime();
    }
    var c = S.changes.get(trainKey(board, t));
    return c && c.at ? c.at : null;
  }

  function isRecent(board, t) {
    var at = changedAt(board, t);
    return at != null && Date.now() - at < RECENT_S * 1000;
  }

  // ---- filtering / sorting ---------------------------------------------------------

  function matches(t) {
    if (S.onlyFav && !S.favs.has(String(t.train_no))) return false;
    if (S.q) {
      var q = norm(S.q);
      if (/^\d+$/.test(q)) {
        if (String(t.train_no).indexOf(q) < 0) return false;
      } else if (norm(t.station).indexOf(q) < 0 && norm(t.train_type + " " + t.train_no).indexOf(q) < 0) {
        return false;
      }
    }
    if (S.fDelay !== "all") {
      if (!hasDelay(t) || !(t.delay_min > S.cfg.delay_thresholds[S.fDelay])) return false;
    }
    if (S.fOp && t.operator !== S.fOp) return false;
    if (S.fPlat) {
      var known = t.platform != null && t.platform !== "";
      if (S.fPlat === "__none" ? known : String(t.platform) !== S.fPlat) return false;
    }
    return true;
  }

  function sorted(list) {
    var rows = list.map(function (t, i) { return { t: t, i: i }; });
    var dir = S.dir;
    rows.sort(function (a, b) {
      var r = 0;
      if (S.sort === "delay") {
        var da = hasDelay(a.t) ? a.t.delay_min : null;
        var db = hasDelay(b.t) ? b.t.delay_min : null;
        if (da == null && db == null) r = 0;
        else if (da == null) return 1;      // necunoscut mereu la final
        else if (db == null) return -1;
        else r = db - da;                    // implicit: cea mai mare întârziere sus
      } else if (S.sort === "number") {
        r = a.t.train_no - b.t.train_no;
      }
      if (r === 0) r = a.i - b.i;            // „time" = ordinea tabelei (zi + oră)
      return r * dir;
    });
    return rows.map(function (x) { return x.t; });
  }

  // ---- building the panel ----------------------------------------------------------

  function button(cls, label, ico) {
    var b = el("button", "pnl-btn " + (cls || ""));
    b.type = "button";
    if (ico) b.appendChild(icon(ico));
    b.appendChild(el("span", "pnl-btn-text", label));
    return b;
  }

  function selectField(id, label, options) {
    var wrap = el("label", "pnl-field");
    wrap.htmlFor = id;
    wrap.appendChild(el("span", "pnl-field-label", label));
    var s = el("select", "pnl-select");
    s.id = id;
    setOptions(s, options);
    wrap.appendChild(s);
    return { wrap: wrap, select: s };
  }

  function setOptions(select, options) {
    var cur = select.value;
    select.replaceChildren();
    options.forEach(function (o) {
      var opt = el("option", null, o[1]);
      opt.value = o[0];
      select.appendChild(opt);
    });
    if (options.some(function (o) { return o[0] === cur; })) select.value = cur;
  }

  function delayOptions() {
    var th = S.cfg.delay_thresholds;
    return [["all", "Toate"], ["low", "> " + th.low + " min"], ["mid", "> " + th.mid + " min"],
            ["high", "> " + th.high + " min"]];
  }

  function build() {
    var root = $("panel-root");
    if (!root) return false;
    var d = S.dom;

    // comutator Panou / Carduri (vizibil în ambele moduri)
    d.switch = el("div", "pnl-switch");
    d.switch.setAttribute("role", "group");
    d.switch.setAttribute("aria-label", "Mod de afișare");
    d.btnPanou = button("pnl-seg", "Panou");
    d.btnCards = button("pnl-seg", "Carduri");
    d.btnPanou.addEventListener("click", function () { setView("panou", true); });
    d.btnCards.addEventListener("click", function () { setView("carduri", true); });
    d.switch.append(d.btnPanou, d.btnCards);

    var pnl = d.pnl = el("section", "pnl");
    pnl.id = "pnl";
    pnl.setAttribute("aria-labelledby", "pnl-title");
    pnl.tabIndex = -1;

    // antet: titlu + ceas
    var head = el("div", "pnl-head");
    d.title = el("h2", "pnl-title");
    d.title.id = "pnl-title";
    var clock = el("div", "pnl-clock");
    d.clockTime = el("span", "pnl-clock-time", "--:--:--");
    d.clockDate = el("span", "pnl-clock-date", "");
    clock.append(d.clockTime, d.clockDate);
    head.append(d.title, clock);

    // linia de stare
    var status = el("ul", "pnl-status");
    status.setAttribute("aria-label", "Starea datelor");
    d.stFresh = el("li", "pnl-chip pnl-fresh");
    d.stCapture = el("li", "pnl-chip");
    d.stSystem = el("li", "pnl-chip");
    d.stSource = el("li", "pnl-chip");
    d.stCount = el("li", "pnl-chip");
    status.append(d.stFresh, d.stCapture, d.stSystem, d.stSource, d.stCount);

    d.banner = el("p", "pnl-banner");
    d.banner.setAttribute("role", "status");
    d.banner.hidden = true;

    // comenzi
    var controls = el("div", "pnl-controls");
    var seg = el("div", "pnl-boardseg");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "Ce afișez");
    d.segBtns = {};
    [["arrivals", "Sosiri"], ["departures", "Plecări"], ["all", "Toate"]].forEach(function (p) {
      var b = button("pnl-seg", p[1]);
      b.dataset.board = p[0];
      b.addEventListener("click", function () { setBoard(p[0]); });
      d.segBtns[p[0]] = b;
      seg.appendChild(b);
    });

    var search = el("label", "pnl-field pnl-search");
    search.htmlFor = "pnl-q";
    search.appendChild(el("span", "pnl-field-label", "Caută"));
    d.q = el("input", "pnl-input");
    d.q.id = "pnl-q";
    d.q.type = "search";
    d.q.placeholder = "Nr. tren sau localitate";
    d.q.autocomplete = "off";
    d.q.addEventListener("input", function () { S.q = d.q.value; render(); });
    search.appendChild(d.q);

    var fDelay = selectField("pnl-f-delay", "Întârziere", delayOptions());
    d.fDelay = fDelay.select;
    d.fDelay.addEventListener("change", function () { S.fDelay = d.fDelay.value; render(); });
    var fOp = selectField("pnl-f-op", "Operator", [["", "Toți"]]);
    d.fOp = fOp.select;
    d.fOp.addEventListener("change", function () { S.fOp = d.fOp.value; render(); });
    var fPlat = selectField("pnl-f-plat", "Linia", [["", "Toate"]]);
    d.fPlat = fPlat.select;
    d.fPlat.addEventListener("change", function () { S.fPlat = d.fPlat.value; render(); });
    var fSort = selectField("pnl-sort", "Sortare", [["time", "Oră programată"], ["delay", "Întârziere"],
                                                    ["number", "Număr tren"]]);
    d.sort = fSort.select;
    d.sort.addEventListener("change", function () { S.sort = d.sort.value; S.dir = 1; render(); });

    var fav = el("label", "pnl-check");
    d.onlyFav = el("input");
    d.onlyFav.type = "checkbox";
    d.onlyFav.addEventListener("change", function () { S.onlyFav = d.onlyFav.checked; render(); });
    fav.append(d.onlyFav, el("span", null, "Doar Favorite (local)"));

    var actions = el("div", "pnl-actions");
    d.btnReset = button("", "Resetează", ICONS.reset);
    d.btnReset.title = "Resetează filtrele și ordinea";
    d.btnReset.addEventListener("click", resetFilters);

    d.cols = el("details", "pnl-cols");
    var sum = el("summary", "pnl-btn");
    sum.append(icon(ICONS.cols), el("span", "pnl-btn-text", "Coloane"));
    var colBox = el("fieldset", "pnl-cols-box");
    colBox.appendChild(el("legend", null, "Coloane afișate"));
    COLS.forEach(function (c) {
      if (c.fixed) return;
      var lab = el("label", "pnl-check");
      var cb = el("input");
      cb.type = "checkbox";
      cb.checked = !S.hidden.has(c.id);
      cb.addEventListener("change", function () {
        if (cb.checked) S.hidden.delete(c.id); else S.hidden.add(c.id);
        save(KEYS.cols, JSON.stringify(Array.from(S.hidden)));
        applyCols();
      });
      lab.append(cb, el("span", null, c.full));
      colBox.appendChild(lab);
    });
    d.cols.append(sum, colBox);

    d.btnRefresh = button("", "Reîmprospătează", ICONS.refresh);
    d.btnRefresh.addEventListener("click", manualRefresh);
    d.btnFs = button("", "Ecran complet", ICONS.full);
    d.btnFs.setAttribute("aria-pressed", "false");
    d.btnFs.addEventListener("click", toggleFullscreen);
    actions.append(d.btnReset, d.cols, d.btnRefresh, d.btnFs);

    // filtrele: deschise mereu pe ecrane late, pliate implicit pe telefon
    d.filters = el("details", "pnl-filters");
    var fsum = el("summary", "pnl-btn pnl-filters-sum");
    fsum.append(el("span", "pnl-btn-text", "Caută, filtrează, sortează"));
    var fbox = el("div", "pnl-filters-box");
    fbox.append(search, fDelay.wrap, fOp.wrap, fPlat.wrap, fSort.wrap, fav);
    d.filters.append(fsum, fbox);
    var wide = window.matchMedia ? window.matchMedia("(min-width: 760px)") : null;
    var syncFilters = function () { if (!wide || wide.matches) d.filters.open = true; };
    syncFilters();
    if (wide && wide.addEventListener) wide.addEventListener("change", syncFilters);

    controls.append(seg, d.filters, actions);

    // legendă
    d.legend = el("ul", "pnl-legend");
    d.legend.setAttribute("aria-label", "Legenda culorilor");

    // tabele
    d.body = el("div", "pnl-body");
    d.sections = {};
    BOARDS.forEach(function (b) {
      var sec = el("section", "pnl-board");
      sec.dataset.board = b;
      var h = el("h3", "pnl-board-title");
      var hText = el("span", null, b === "arrivals" ? "SOSIRI" : "PLECĂRI");
      var hCount = el("span", "pnl-board-count");
      h.append(hText, hCount);
      var table = el("table", "pnl-table");
      var cap = el("caption", "sr-only", b === "arrivals" ? "Sosiri în Gara de Nord" : "Plecări din Gara de Nord");
      var thead = el("thead");
      var hr = el("tr");
      var thFav = el("th", "c-fav");
      thFav.scope = "col";
      thFav.appendChild(el("span", "sr-only", "Favorite (local)"));
      hr.appendChild(thFav);
      var ths = {};
      COLS.forEach(function (c) {
        var th = el("th", "c-" + c.id);
        th.scope = "col";
        var label = c.id === "station" ? (b === "arrivals" ? "Din" : "Spre") : c.label;
        if (c.sort) {
          var sb = el("button", "pnl-sortbtn", label);
          sb.type = "button";
          sb.title = "Sortează după " + c.full.toLowerCase();
          sb.addEventListener("click", function () { sortBy(c.sort); });
          th.appendChild(sb);
        } else {
          th.textContent = label;
        }
        th.title = c.full;
        ths[c.id] = th;
        hr.appendChild(th);
      });
      thead.appendChild(hr);
      var tbody = el("tbody");
      tbody.addEventListener("click", onRowClick);
      tbody.addEventListener("keydown", onRowKey);
      table.append(cap, thead, tbody);
      var empty = el("p", "pnl-empty", "Niciun tren nu corespunde filtrelor.");
      empty.hidden = true;
      sec.append(h, table, empty);
      d.body.appendChild(sec);
      d.sections[b] = { sec: sec, tbody: tbody, count: hCount, empty: empty, ths: ths };
    });

    // detaliu (în interiorul panoului, ca să fie vizibil și în ecran complet)
    d.detail = el("aside", "pnl-detail");
    d.detail.setAttribute("aria-labelledby", "pnl-detail-title");
    d.detail.hidden = true;
    d.detail.tabIndex = -1;

    pnl.append(head, status, d.banner, controls, d.legend, d.body, d.detail);
    root.append(d.switch, pnl);
    return true;
  }

  // ---- render ----------------------------------------------------------------------

  function renderLegend() {
    var th = S.cfg.delay_thresholds;
    var items = [
      ["ok", "La timp (0 min citit)"],
      ["low", "1–" + th.mid + " min"],
      ["mid", (th.mid + 1) + "–" + th.high + " min"],
      ["high", "> " + th.high + " min"],
      ["unknown", "Necitit / neconfirmat / vechi"],
      ["recent", "Modificat recent"]
    ];
    S.dom.legend.replaceChildren();
    items.forEach(function (it) {
      var li = el("li", "pnl-legend-item");
      li.dataset.level = it[0];
      var sw = el("span", "pnl-swatch");
      sw.setAttribute("aria-hidden", "true");
      li.append(sw, el("span", null, it[1]));
      S.dom.legend.appendChild(li);
    });
  }

  function cell(cls, content) {
    var td = el("td", "c-" + cls);
    if (content instanceof Node) td.appendChild(content);
    else if (content != null) td.textContent = content;
    return td;
  }

  function message(board, t, lvl, fresh) {
    var parts = [];
    if (fresh !== "live") parts.push("neconfirmat — date vechi");
    else if (lvl === "ok") parts.push("la timp");
    else if (lvl === "unknown") parts.push("întârziere necitită");
    else parts.push("întârziat");
    if (t.flagged) parts.push("marcat * pe tabela CFR");
    if (isRecent(board, t)) parts.push("modificat recent");
    return parts.join(" · ");
  }

  function delayNode(t, lvl, fresh) {
    if (lvl === "unknown" && !(typeof t.delay_min === "number" && t.delay_min >= 0)) {
      return unknown("întârziere");
    }
    var d = t.delay_min;
    var s = el("span", "pnl-delay", d === 0 ? "la timp" : "+" + d + " min");
    var label = d === 0 ? "La timp" : "Întârziere " + d + " minute";
    if (fresh !== "live" || lvl === "unknown") label += " (neconfirmat)";
    s.setAttribute("aria-label", label);
    return s;
  }

  function buildRow(board, t, fresh) {
    var key = trainKey(board, t);
    var lvl = levelOf(t);
    var tr = el("tr", "pnl-row");
    tr.dataset.key = key;
    tr.dataset.board = board;
    tr.dataset.level = lvl;
    tr.tabIndex = 0;
    if (isRecent(board, t)) tr.classList.add("is-recent");
    if (S.selected === key) tr.classList.add("is-selected");
    tr.setAttribute("aria-label", (t.train_type || "") + " " + t.train_no + ", " +
      (board === "arrivals" ? "din " : "spre ") + (t.station || "stație necunoscută") +
      ", ora " + (t.sched_time || "necunoscută") + ". Enter pentru detalii.");

    var isFav = S.favs.has(String(t.train_no));
    var star = el("button", "pnl-star");
    star.type = "button";
    star.dataset.fav = String(t.train_no);
    star.setAttribute("aria-pressed", isFav ? "true" : "false");
    star.setAttribute("aria-label", (isFav ? "Scoate din" : "Adaugă la") + " Favorite (local): tren " + t.train_no);
    star.title = "Favorite (local) — doar în acest browser";
    star.appendChild(icon(ICONS.star));
    tr.appendChild(cell("fav", star));

    tr.appendChild(cell("time", t.sched_time ? t.sched_time : unknown("oră")));

    var train = el("span", "pnl-train");
    var type = el("span", typeClass(t.train_type), t.train_type || "?");
    type.title = "Tip tren " + (t.train_type || "necunoscut");
    train.append(type, el("span", "pnl-no", String(t.train_no)));
    if (t.flagged) {
      var flag = el("span", "pnl-flag", "*");
      flag.title = "Marcat cu * pe tabela CFR";
      flag.setAttribute("aria-label", "marcat cu steluță pe tabela CFR");
      train.appendChild(flag);
    }
    tr.appendChild(cell("train", train));

    tr.appendChild(cell("station", t.station ? t.station : unknown("stație")));
    tr.appendChild(cell("op", t.operator ? t.operator : unknown("operator")));
    tr.appendChild(cell("delay", delayNode(t, lvl, fresh)));

    var known = t.platform != null && t.platform !== "";
    var plat = known ? el("span", "pnl-plat", String(t.platform)) : unknown("linie");
    if (known) plat.setAttribute("aria-label", "Linia " + t.platform);
    tr.appendChild(cell("plat", plat));

    tr.appendChild(cell("msg", message(board, t, lvl, fresh)));

    var at = changedAt(board, t);
    if (at != null) {
      var ch = el("span", "pnl-changed", fmtHM.format(new Date(at)));
      ch.title = "Modificare de întârziere/linie observată de această pagină";
      tr.appendChild(cell("changed", ch));
    } else {
      tr.appendChild(cell("changed", unknown("ultima modificare")));
    }
    return tr;
  }

  function typeClass(type) {
    var k = String(type || "").toLowerCase();
    return ["ir", "irn", "re", "r", "rm"].indexOf(k) >= 0 ? "type type-" + k : "type";
  }

  function refreshOptions() {
    var ops = new Set(), plats = new Set(), noPlat = false;
    BOARDS.forEach(function (b) {
      ((S.data && S.data[b]) || []).forEach(function (t) {
        if (t.operator) ops.add(t.operator);
        if (t.platform != null && t.platform !== "") plats.add(String(t.platform));
        else noPlat = true;
      });
    });
    var opOpts = [["", "Toți"]].concat(Array.from(ops).sort().map(function (o) { return [o, o]; }));
    if (S.fOp && !ops.has(S.fOp)) opOpts.push([S.fOp, S.fOp]);
    setOptions(S.dom.fOp, opOpts);
    var plOpts = [["", "Toate"]].concat(Array.from(plats).sort(function (a, b) {
      return (parseInt(a, 10) || 0) - (parseInt(b, 10) || 0);
    }).map(function (p) { return [p, "Linia " + p]; }));
    if (noPlat) plOpts.push(["__none", "Neanunțată"]);
    if (S.fPlat && S.fPlat !== "__none" && !plats.has(S.fPlat)) plOpts.push([S.fPlat, "Linia " + S.fPlat]);
    setOptions(S.dom.fPlat, plOpts);
    S.dom.fOp.value = S.fOp;
    S.dom.fPlat.value = S.fPlat;
  }

  function render() {
    if (!S.dom.pnl) return;
    var d = S.dom;
    var fresh = freshness();
    d.pnl.dataset.fresh = fresh;
    d.pnl.dataset.board = S.board;
    d.title.textContent = TITLES[S.board];
    Object.keys(d.segBtns).forEach(function (k) {
      d.segBtns[k].setAttribute("aria-pressed", k === S.board ? "true" : "false");
    });
    d.sort.value = S.sort;

    var focused = document.activeElement && document.activeElement.closest &&
      document.activeElement.closest(".pnl-row");
    var focusKey = focused ? focused.dataset.key : null;
    var focusStar = !!(document.activeElement && document.activeElement.classList &&
      document.activeElement.classList.contains("pnl-star"));

    var shown = 0, total = 0;
    BOARDS.forEach(function (b) {
      var sec = d.sections[b];
      var visible = S.board === "all" || S.board === b;
      sec.sec.hidden = !visible;
      var list = (S.data && S.data[b]) || [];
      var rows = sorted(list.filter(matches));
      sec.tbody.replaceChildren.apply(sec.tbody, rows.map(function (t) { return buildRow(b, t, fresh); }));
      sec.count.textContent = rows.length === list.length ? String(list.length) : rows.length + " / " + list.length;
      sec.empty.hidden = rows.length > 0 || !S.data;
      sec.empty.textContent = list.length ? "Niciun tren nu corespunde filtrelor." : "Momentan nu sunt trenuri afișate.";
      COLS.forEach(function (c) {
        if (!c.sort) return;
        var th = sec.ths[c.id];
        if (S.sort === c.sort) th.setAttribute("aria-sort", S.dir === 1 ? (c.sort === "delay" ? "descending" : "ascending")
          : (c.sort === "delay" ? "ascending" : "descending"));
        else th.removeAttribute("aria-sort");
      });
      if (visible) { shown += rows.length; total += list.length; }
    });

    if (focusKey) {
      var again = d.body.querySelector('.pnl-row[data-key="' + cssEscape(focusKey) + '"]');
      if (again) (focusStar ? again.querySelector(".pnl-star") : again).focus({ preventScroll: true });
    }
    d.stCount.textContent = S.data ? (shown === total ? shown + " trenuri afișate" : shown + " din " + total + " trenuri afișate") : "— trenuri";
    renderStatus();
    renderDetail();
  }

  function cssEscape(s) {
    return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/["\\]/g, "\\$&");
  }

  function renderStatus() {
    var d = S.dom;
    var fresh = freshness();
    var a = age();
    d.pnl.dataset.fresh = fresh;
    d.stFresh.dataset.state = fresh;
    d.stFresh.textContent = { live: "ACTUALIZAT", stale: "DATE VECHI", offline: "INDISPONIBIL", none: "SE ÎNCARCĂ" }[fresh];

    if (a != null) {
      var when = new Date(Date.now() - a * 1000);
      d.stCapture.textContent = "Ultima captură reușită: " + fmtTime.format(when) + " (acum " + ago(a) + ")";
    } else {
      d.stCapture.textContent = S.data ? "Ultima captură reușită: necunoscut (nicio citire)" : "Ultima captură reușită: —";
    }
    d.stSystem.textContent = {
      live: "OCR / sistem: funcționează",
      stale: a == null ? "OCR / sistem: nicio citire încă" : "OCR / sistem: fără citire nouă de " + ago(a),
      offline: "OCR / sistem: server indisponibil",
      none: "OCR / sistem: se verifică…"
    }[fresh];
    d.stSystem.dataset.state = fresh;
    d.stSource.textContent = fresh === "live" ? "Sursa CFR: răspunde" : "Sursa CFR: necunoscut";
    d.stSource.dataset.state = fresh;

    var text = "";
    if (fresh === "offline") {
      text = S.data
        ? "Conexiune pierdută — afișez ultimele date primite" + (a != null ? " (captură de acum " + ago(a) + ")" : "") +
          ". Culorile sunt dezactivate până la reconectare. Reîncerc automat."
        : "Nu am putut încărca tabela. Reîncerc automat.";
    } else if (fresh === "stale") {
      text = a == null
        ? "Tabela CFR nu a fost încă citită — datele pot lipsi."
        : "Datele nu s-au mai actualizat de " + ago(a) + " — pot fi depășite, culorile sunt dezactivate. Verifică și cfr.ro.";
    }
    d.banner.textContent = text;
    d.banner.hidden = !text;
  }

  function tickClock() {
    if (!S.dom.pnl) return;
    var now = new Date();
    S.dom.clockTime.textContent = fmtTime.format(now);
    S.dom.clockDate.textContent = fmtDate.format(now);
    if (S.view === "panou") renderStatus();
  }

  // ---- detail ----------------------------------------------------------------------

  function findTrain(key) {
    if (!S.data || !key) return null;
    var out = null;
    BOARDS.forEach(function (b) {
      (S.data[b] || []).forEach(function (t) { if (trainKey(b, t) === key) out = { board: b, t: t }; });
    });
    return out;
  }

  function openDetail(key) {
    var found = findTrain(key);
    if (!found) return;
    S.selected = key;
    S.lastTrain = found;
    S.dom.body.querySelectorAll(".pnl-row.is-selected").forEach(function (r) { r.classList.remove("is-selected"); });
    var row = S.dom.body.querySelector('.pnl-row[data-key="' + cssEscape(key) + '"]');
    if (row) row.classList.add("is-selected");
    renderDetail();
    S.dom.detail.focus({ preventScroll: true });
  }

  function closeDetail() {
    var key = S.selected;
    S.selected = null;
    S.lastTrain = null;
    S.detailSig = null;
    S.dom.detail.hidden = true;
    S.dom.pnl.classList.remove("has-detail");
    var row = key && S.dom.body.querySelector('.pnl-row[data-key="' + cssEscape(key) + '"]');
    if (row) { row.classList.remove("is-selected"); row.focus(); }
  }

  function dlRow(dl, label, value) {
    dl.appendChild(el("dt", null, label));
    var dd = el("dd");
    if (value instanceof Node) dd.appendChild(value); else dd.textContent = value;
    dl.appendChild(dd);
  }

  function renderDetail() {
    var d = S.dom;
    if (!S.selected) { d.detail.hidden = true; d.pnl.classList.remove("has-detail"); return; }
    var found = findTrain(S.selected);
    var gone = !found;
    if (found) S.lastTrain = found; else found = S.lastTrain;
    if (!found) { d.detail.hidden = true; return; }
    var t = found.t, b = found.board, fresh = freshness(), lvl = levelOf(t);
    var sig = JSON.stringify([S.selected, t, fresh, gone, changedAt(b, t), isRecent(b, t),
                              S.favs.has(String(t.train_no))]);
    if (sig === S.detailSig && !d.detail.hidden) return;
    S.detailSig = sig;

    var head = el("div", "pnl-detail-head");
    var h = el("h3", "pnl-detail-title", (t.train_type || "") + " " + t.train_no);
    h.id = "pnl-detail-title";
    var close = el("button", "pnl-icon-btn");
    close.type = "button";
    close.setAttribute("aria-label", "Închide detaliile");
    close.appendChild(icon(ICONS.close));
    close.addEventListener("click", closeDetail);
    head.append(h, close);

    var dl = el("dl", "pnl-dl");
    var station = t.station || null;
    var route = b === "arrivals"
      ? (station ? station : "?") + " → București Nord"
      : "București Nord → " + (station ? station : "?");
    dlRow(dl, "Panou", b === "arrivals" ? "Sosiri" : "Plecări");
    dlRow(dl, "Rută (cum apare pe tabelă)", station ? route : unknown("rută"));
    dlRow(dl, "Ora programată", t.sched_time || unknown("oră"));
    var dd = delayNode(t, lvl, fresh);
    var dWrap = el("span", "pnl-detail-delay");
    dWrap.dataset.level = lvl;
    dWrap.appendChild(dd);
    dlRow(dl, "Ultima întârziere citită", dWrap);
    var known = t.platform != null && t.platform !== "";
    dlRow(dl, "Linia", known ? String(t.platform) : unknown("linie"));
    dlRow(dl, "Operator", t.operator || unknown("operator"));
    dlRow(dl, "Stare", message(b, t, lvl, fresh));
    var at = changedAt(b, t);
    dlRow(dl, "Ultima modificare observată", at != null ? fmtTime.format(new Date(at)) : unknown("ultima modificare"));

    var note = el("p", "pnl-detail-note", gone
      ? "Trenul nu mai apare pe tabela curentă; se afișează ultimele date văzute."
      : (fresh === "live" ? "Date din ultima captură a tabelei CFR." : "Date vechi — neconfirmate."));

    var acts = el("div", "pnl-detail-actions");
    var hist = el("a", "pnl-btn pnl-btn-primary");
    hist.href = historyHref(t);
    hist.append(icon(ICONS.history), el("span", "pnl-btn-text", "Istoricul trenului"));
    var isFav = S.favs.has(String(t.train_no));
    var favBtn = button("", isFav ? "Scoate din Favorite (local)" : "Adaugă la Favorite (local)", ICONS.star);
    favBtn.setAttribute("aria-pressed", isFav ? "true" : "false");
    favBtn.addEventListener("click", function () { toggleFav(String(t.train_no)); });
    acts.append(hist, favBtn);
    if (window.TabelaApp && typeof window.TabelaApp.onFollow === "function") {
      var follow = button("", "Urmărește (notificări)");
      follow.addEventListener("click", function () { window.TabelaApp.onFollow(t, follow); });
      acts.appendChild(follow);
    }

    var hadFocus = d.detail.contains(document.activeElement);
    d.detail.replaceChildren(head, dl, note, acts);
    d.detail.hidden = false;
    d.pnl.classList.add("has-detail");
    if (hadFocus) d.detail.focus({ preventScroll: true });
  }

  // ---- interactions ------------------------------------------------------------------

  function onRowClick(e) {
    var star = e.target.closest(".pnl-star");
    if (star) { toggleFav(star.dataset.fav); return; }
    var row = e.target.closest(".pnl-row");
    if (row) openDetail(row.dataset.key);
  }

  function onRowKey(e) {
    var row = e.target.closest(".pnl-row");
    if (!row || e.target.closest(".pnl-star")) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openDetail(row.dataset.key);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      var next = e.key === "ArrowDown" ? row.nextElementSibling : row.previousElementSibling;
      if (next) { e.preventDefault(); next.focus(); }
    }
  }

  function toggleFav(no) {
    if (S.favs.has(no)) S.favs.delete(no); else S.favs.add(no);
    save(KEYS.fav, JSON.stringify(Array.from(S.favs)));
    render();
  }

  function sortBy(key) {
    if (S.sort === key) S.dir = -S.dir;
    else { S.sort = key; S.dir = 1; }
    render();
  }

  function resetFilters() {
    S.q = ""; S.fDelay = "all"; S.fOp = ""; S.fPlat = ""; S.onlyFav = false; S.sort = "time"; S.dir = 1;
    var d = S.dom;
    d.q.value = ""; d.fDelay.value = "all"; d.fOp.value = ""; d.fPlat.value = ""; d.onlyFav.checked = false;
    render();
  }

  function setBoard(b) {
    S.board = b;
    save(KEYS.board, b);
    render();
  }

  function setView(v, remember) {
    S.view = v;
    document.documentElement.dataset.view = v;
    if (S.dom.pnl) S.dom.pnl.hidden = v !== "panou";
    if (S.dom.btnPanou) {
      S.dom.btnPanou.setAttribute("aria-pressed", v === "panou" ? "true" : "false");
      S.dom.btnCards.setAttribute("aria-pressed", v === "carduri" ? "true" : "false");
    }
    if (remember) save(KEYS.view, v);
    if (v === "panou") render();
  }

  function applyCols() {
    COLS.forEach(function (c) {
      S.dom.body.classList.toggle("hide-" + c.id, S.hidden.has(c.id));
    });
  }

  function manualRefresh() {
    if (!window.TabelaApp || typeof window.TabelaApp.refresh !== "function") return;
    S.waiting = true;
    S.dom.btnRefresh.setAttribute("aria-busy", "true");
    S.dom.btnRefresh.disabled = true;
    window.TabelaApp.refresh();
  }

  // ---- fullscreen ------------------------------------------------------------------------

  function fsElement() {
    return document.fullscreenElement || document.webkitFullscreenElement || null;
  }

  function setPseudoFs(on) {
    S.pseudoFs = on;
    S.dom.pnl.classList.toggle("is-pseudo-fs", on);
    document.documentElement.classList.toggle("pnl-noscroll", on);
    updateFsButton();
  }

  function toggleFullscreen() {
    var p = S.dom.pnl;
    if (fsElement()) {
      var exit = document.exitFullscreen || document.webkitExitFullscreen;
      if (exit) exit.call(document);
      return;
    }
    if (S.pseudoFs) { setPseudoFs(false); return; }
    var req = p.requestFullscreen || p.webkitRequestFullscreen;
    if (!req) { setPseudoFs(true); return; }
    try {
      var r = req.call(p);
      if (r && typeof r.catch === "function") r.catch(function () { setPseudoFs(true); });
    } catch (e) {
      setPseudoFs(true);
    }
  }

  function updateFsButton() {
    var on = !!fsElement() || S.pseudoFs;
    var b = S.dom.btnFs;
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.replaceChildren(icon(on ? ICONS.exitFull : ICONS.full),
      el("span", "pnl-btn-text", on ? "Ieși din ecran complet" : "Ecran complet"));
    S.dom.pnl.classList.toggle("is-fs", on);
  }

  // ---- data ------------------------------------------------------------------------------

  function onBoard(e) {
    var det = e.detail || {};
    if (det.data && det.data !== S.data) {
      S.receivedAt = performance.now();
      trackChanges(det.data);
    }
    S.data = det.data || S.data;
    S.failed = !!det.failed;
    if (S.waiting) {
      S.waiting = false;
      S.dom.btnRefresh.removeAttribute("aria-busy");
      S.dom.btnRefresh.disabled = false;
    }
    if (!S.dom.pnl) return;
    refreshOptions();
    render();
  }

  function loadConfig() {
    return fetch("/api/config", { cache: "no-store", headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (c) {
        var th = c && c.delay_thresholds;
        if (th && th.low > 0 && th.low < th.mid && th.mid < th.high) {
          S.cfg = {
            delay_thresholds: { low: th.low, mid: th.mid, high: th.high },
            stale_after_s: c.stale_after_s > 0 ? c.stale_after_s : DEFAULTS.stale_after_s,
            refresh_s: c.refresh_s > 0 ? c.refresh_s : DEFAULTS.refresh_s
          };
        }
      })
      .catch(function () { /* rămân valorile implicite */ });
  }

  // ---- boot ------------------------------------------------------------------------------

  function restore() {
    var v = load(KEYS.view);
    S.view = v === "panou" || v === "carduri" ? v
      : (window.matchMedia && window.matchMedia("(min-width: 1024px)").matches ? "panou" : "carduri");
    var b = load(KEYS.board);
    S.board = b === "arrivals" || b === "departures" || b === "all" ? b : "arrivals";
    try {
      var cols = JSON.parse(load(KEYS.cols) || "null");
      S.hidden = new Set(Array.isArray(cols) ? cols.map(String) : ["changed"]);
    } catch (e) { S.hidden = new Set(["changed"]); }
    try {
      var favs = JSON.parse(load(KEYS.fav) || "[]");
      S.favs = new Set(Array.isArray(favs) ? favs.map(String) : []);
    } catch (e) { S.favs = new Set(); }
  }

  // ascultăm imediat: primul fetch al app.js poate termina înainte de init
  document.addEventListener("tabela:board", onBoard);

  function init() {
    restore();
    if (!build()) return;
    applyCols();
    renderLegend();
    setView(S.view, false);
    tickClock();
    setInterval(tickClock, 1000);
    document.addEventListener("fullscreenchange", updateFsButton);
    document.addEventListener("webkitfullscreenchange", updateFsButton);
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (S.selected && !S.dom.detail.hidden) closeDetail();
      else if (S.pseudoFs) setPseudoFs(false);
    });
    loadConfig().then(function () {
      setOptions(S.dom.fDelay, delayOptions());
      S.dom.fDelay.value = S.fDelay;
      renderLegend();
      render();
    });
    refreshOptions();
    render();
  }

  window.TabelaPanel = { setView: setView, setBoard: setBoard, levelOf: levelOf };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
