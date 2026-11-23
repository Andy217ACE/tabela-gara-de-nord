// © 2026 Andy217Ace
// Tabela Gara de Nord — mod „Panou" (afișaj de gară). Consumă datele pe care app.js le
// publică prin evenimentul `tabela:board` (nu face un al doilea polling). DOM construit
// doar cu createElement/textContent; fără stiluri inline (CSP). Culorile vin din CSS
// (panel.css) prin atributul data-level; pragurile vin din GET /api/config, încărcat o
// singură dată de app.js (TabelaApp.config) — aceeași sursă și pentru intervalul de refresh.
"use strict";

(function () {
  var TZ = "Europe/Bucharest";
  var DEFAULTS = { delay_thresholds: { low: 5, mid: 15, high: 30 }, stale_after_s: 180, refresh_s: 10 };
  var RECENT_S = 120;          // „modificare recentă" (albastru) — observată de această pagină
  var BOARDS = ["arrivals", "departures"];
  var KEYS = { view: "tabela.view", board: "tabela.panel.board", cols: "tabela.panel.cols", fav: "tabela.fav" };
  // titles: i18n keys panel.title.<board>; columns: panel.col.<id>.label / .full (+ .tip), panel.sortBy.<id>
  // id, se poate ascunde, implicit vizibil, cheie de sortare
  var COLS = [
    { id: "time", fixed: true, sort: "time" },
    { id: "train", fixed: true, sort: "number" },
    { id: "station" },
    { id: "op" },
    { id: "delay", sort: "delay" },
    { id: "plat" },
    // estimare, nu citire: implicit ascunsă; starea e în peron_est.js (cheia tabela.peronEst)
    { id: "pest", est: true, tip: true },
    { id: "msg" },
    { id: "changed", off: true }
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

  // ---- i18n (web/i18n/i18n.js) -------------------------------------------------------
  function T(key, params) { return window.I18N ? window.I18N.t(key, params) : key; }
  function loc() { return window.I18N && window.I18N.lang() === "en" ? "en-GB" : "ro-RO"; }
  // plural form by the active language's Intl.PluralRules: keys base.one / base.few / base.other
  function plural(base, n, params) {
    var cat = "other";
    try { cat = new Intl.PluralRules(loc()).select(Math.abs(n)); } catch (e) { /* ignore */ }
    var k = base + "." + cat, v = T(k, params);
    return v === k ? T(base + ".other", params) : v;
  }
  // formatters that follow the active language (created once per locale)
  function dtf(opts) {
    var cache = {};
    return { format: function (d) {
      var l = loc();
      return (cache[l] || (cache[l] = new Intl.DateTimeFormat(l, opts))).format(d);
    } };
  }
  var nfInt = { format: function (v) { return new Intl.NumberFormat(loc()).format(v); } };
  function unsureText() { return T("board.unsure"); }

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
    history: ["M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z", "M12 7.5V12l3 2"],
    bell: ["M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z", "M10 20.5a2 2 0 0 0 4 0"],
    theme: ["M12 4a8 8 0 1 0 0 16a8 8 0 1 0 0-16z", "M12 4v16"]
  };

  function load(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function save(key, val) {
    try { localStorage.setItem(key, val); } catch (e) { /* storage indisponibil */ }
  }

  // valoare lipsă: nu o inventăm, o arătăm explicit
  // `what` = key suffix of panel.what.* (delay, time, station, op, plat, route, changed)
  function unknown(what) {
    var s = el("span", "pnl-unk", "—");
    var label = what ? T("panel.unk", { what: T("panel.what." + what) }) : T("panel.unkBare");
    s.setAttribute("role", "img");
    s.setAttribute("aria-label", label);
    s.title = label;
    return s;
  }

  function norm(s) {
    return String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
  }

  // duration (no "ago" wording): 12 s / 5 min / 2 h 5 min
  function dur(sec) {
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return T("time.s", { n: sec });
    var min = Math.floor(sec / 60);
    if (min < 60) return T("time.min", { n: min });
    return T("time.hm", { h: Math.floor(min / 60), m: min % 60 });
  }
  function ago(sec) { return T("time.ago", { age: dur(sec) }); }

  var fmtTime = dtf({ timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  var fmtHM = dtf({ timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
  var fmtDate = dtf({ timeZone: TZ, weekday: "long", day: "numeric", month: "long", year: "numeric" });
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
  // `uncertain` (A2) privește doar numele stației/operatorului, nu cifrele întârzierii:
  // numele primesc marcajul „citire nesigură", culoarea întârzierii rămâne.
  // `delay_read` (API) e true doar când celula de întârziere a fost citită efectiv:
  // fără el nu există „la timp" (verde) — rândul rămâne gri, „necitit".
  function levelOf(t) {
    if (t.delay_read !== true) return "unknown";
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
      } else if (norm(t.station + " " + window.I18N.station(t.station)).indexOf(q) < 0 && norm(t.train_type + " " + t.train_no).indexOf(q) < 0) {
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

  // element whose text is an i18n key (re-filled by I18N.applyDom on a language change)
  function ti(tag, cls, key) {
    var n = el(tag, cls, T(key));
    n.setAttribute("data-i18n", key);
    return n;
  }

  // attribute (aria-label, title, placeholder) from an i18n key, kept in sync by I18N.applyDom
  function ta(n, attr, key) {
    n.setAttribute(attr, T(key));
    var cur = n.getAttribute("data-i18n-attr");
    n.setAttribute("data-i18n-attr", (cur ? cur + ";" : "") + attr + ":" + key);
  }

  function button(cls, key, ico) {
    var b = el("button", "pnl-btn " + (cls || ""));
    b.type = "button";
    if (ico) b.appendChild(icon(ico));
    b.appendChild(ti("span", "pnl-btn-text", key));
    return b;
  }

  function selectField(id, labelKey, options) {
    var wrap = el("label", "pnl-field");
    wrap.htmlFor = id;
    wrap.appendChild(ti("span", "pnl-field-label", labelKey));
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
    return [["all", T("panel.all")], ["low", "> " + th.low + " min"], ["mid", "> " + th.mid + " min"],
            ["high", "> " + th.high + " min"]];
  }

  function sortOptions() {
    return [["time", T("panel.sortTime")], ["delay", T("panel.sortDelay")], ["number", T("panel.sortNumber")]];
  }

  function build() {
    var root = $("panel-root");
    if (!root) return false;
    var d = S.dom;

    // comutator Panou / Carduri (vizibil în ambele moduri)
    d.switch = el("div", "pnl-switch");
    d.switch.setAttribute("role", "group");
    ta(d.switch, "aria-label", "panel.modeAria");
    d.btnPanou = button("pnl-seg", "panel.modePanel");
    d.btnCards = button("pnl-seg", "panel.modeCards");
    d.btnPanou.addEventListener("click", function () { setView("panou", true); });
    d.btnCards.addEventListener("click", function () { setView("carduri", true); });
    d.switch.append(d.btnPanou, d.btnCards);

    var pnl = d.pnl = el("section", "pnl");
    pnl.id = "pnl";
    pnl.setAttribute("aria-labelledby", "pnl-title");
    pnl.tabIndex = -1;

    // antet: titlu + ceas
    var head = el("div", "pnl-head");
    var brand = el("div", "pnl-brand");
    var logo = el("img", "logo pnl-logo");
    logo.src = "icons/logo-96.png";
    logo.srcset = "icons/logo-96.png 1x, icons/logo-192.png 2x";
    logo.alt = "";
    logo.width = 40;
    logo.height = 40;
    d.title = el("h2", "pnl-title");
    d.title.id = "pnl-title";
    brand.append(logo, d.title);
    var clock = el("div", "pnl-clock");
    d.clockTime = el("span", "pnl-clock-time", "--:--:--");
    d.clockDate = el("span", "pnl-clock-date", "");
    clock.append(d.clockTime, d.clockDate);
    // vremea lângă ceas (completată de web/weather.js)
    var clockWx = el("div", "pnl-clockwx");
    var wx = el("div", "wx-slot pnl-weather");
    wx.setAttribute("data-weather-slot", "panel");
    clockWx.append(wx, clock);
    head.append(brand, clockWx);

    // linia de stare
    var status = el("ul", "pnl-status");
    ta(status, "aria-label", "panel.statusAria");
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
    ta(seg, "aria-label", "panel.showAria");
    d.segBtns = {};
    [["arrivals", "board.arrivals"], ["departures", "board.departures"], ["all", "panel.all"]].forEach(function (p) {
      var b = button("pnl-seg", p[1]);
      b.dataset.board = p[0];
      b.addEventListener("click", function () { setBoard(p[0]); });
      d.segBtns[p[0]] = b;
      seg.appendChild(b);
    });

    var search = el("label", "pnl-field pnl-search");
    search.htmlFor = "pnl-q";
    search.appendChild(ti("span", "pnl-field-label", "panel.search"));
    d.q = el("input", "pnl-input");
    d.q.id = "pnl-q";
    d.q.type = "search";
    ta(d.q, "placeholder", "panel.searchPh");
    d.q.autocomplete = "off";
    d.q.addEventListener("input", function () { S.q = d.q.value; render(); });
    search.appendChild(d.q);

    var fDelay = selectField("pnl-f-delay", "panel.fDelay", delayOptions());
    d.fDelay = fDelay.select;
    d.fDelay.addEventListener("change", function () { S.fDelay = d.fDelay.value; render(); });
    var fOp = selectField("pnl-f-op", "panel.fOp", [["", T("panel.allMasc")]]);
    d.fOp = fOp.select;
    d.fOp.addEventListener("change", function () { S.fOp = d.fOp.value; render(); });
    var fPlat = selectField("pnl-f-plat", "panel.fPlat", [["", T("panel.all")]]);
    d.fPlat = fPlat.select;
    d.fPlat.addEventListener("change", function () { S.fPlat = d.fPlat.value; render(); });
    var fSort = selectField("pnl-sort", "panel.sort", sortOptions());
    d.sort = fSort.select;
    d.sort.addEventListener("change", function () { S.sort = d.sort.value; S.dir = 1; render(); });

    var fav = el("label", "pnl-check");
    d.onlyFav = el("input");
    d.onlyFav.type = "checkbox";
    d.onlyFav.addEventListener("change", function () { S.onlyFav = d.onlyFav.checked; render(); });
    fav.append(d.onlyFav, ti("span", null, "panel.onlyFav"));

    var actions = el("div", "pnl-actions");
    d.btnReset = button("", "panel.reset", ICONS.reset);
    ta(d.btnReset, "title", "panel.resetTitle");
    d.btnReset.addEventListener("click", resetFilters);

    d.cols = el("details", "pnl-cols");
    var sum = el("summary", "pnl-btn");
    sum.append(icon(ICONS.cols), ti("span", "pnl-btn-text", "panel.columns"));
    var colBox = el("fieldset", "pnl-cols-box");
    colBox.appendChild(ti("legend", null, "panel.columnsShown"));
    COLS.forEach(function (c) {
      if (c.fixed) return;
      var lab = el("label", "pnl-check");
      var cb = el("input");
      cb.type = "checkbox";
      cb.checked = !S.hidden.has(c.id);
      if (c.est) cb.id = "pnl-col-pest";
      cb.addEventListener("change", function () {
        if (c.est) {  // starea comună cu peron_est.js; nu intră în lista de coloane ascunse
          var ta = window.TabelaApp || {};
          if (typeof ta.peronEstLoad === "function") {  // stratul lazy (app.js)
            ta.peronEstLoad().then(function () { if (ta.peronEst) ta.peronEst.set(cb.checked); });
          }
          return;
        }
        if (cb.checked) S.hidden.delete(c.id); else S.hidden.add(c.id);
        save(KEYS.cols, JSON.stringify(Array.from(S.hidden)));
        applyCols();
      });
      lab.append(cb, ti("span", null, "panel.col." + c.id + ".full"));
      colBox.appendChild(lab);
    });
    d.cols.append(sum, colBox);

    d.btnRefresh = button("", "panel.refresh", ICONS.refresh);
    d.btnRefresh.addEventListener("click", manualRefresh);
    d.btnFs = button("", "panel.fullscreen", ICONS.full);
    d.btnFs.setAttribute("aria-pressed", "false");
    d.btnFs.addEventListener("click", toggleFullscreen);
    // tema (Auto / Luminoasă / Întunecată) — și aici, ca să fie la îndemână în ecran complet
    if (window.TabelaTheme) {
      d.btnTheme = button("pnl-theme", "panel.theme", ICONS.theme);
      d.btnTheme.setAttribute("data-theme-toggle", "");
      d.btnTheme.addEventListener("click", function () { window.TabelaTheme.next(); });
    }
    actions.append(d.btnReset, d.cols, d.btnRefresh, d.btnFs);
    if (d.btnTheme) actions.appendChild(d.btnTheme);

    // filtrele: deschise mereu pe ecrane late, pliate implicit pe telefon
    d.filters = el("details", "pnl-filters");
    var fsum = el("summary", "pnl-btn pnl-filters-sum");
    fsum.append(ti("span", "pnl-btn-text", "panel.filtersSummary"));
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
    ta(d.legend, "aria-label", "panel.legendAria");

    // tabele
    d.body = el("div", "pnl-body");
    d.sections = {};
    BOARDS.forEach(function (b) {
      var sec = el("section", "pnl-board");
      sec.dataset.board = b;
      var h = el("h3", "pnl-board-title");
      var hText = ti("span", null, b === "arrivals" ? "panel.hdr.arrivals" : "panel.hdr.departures");
      var hCount = el("span", "pnl-board-count");
      h.append(hText, hCount);
      var table = el("table", "pnl-table");
      var cap = ti("caption", "sr-only", b === "arrivals" ? "panel.cap.arrivals" : "panel.cap.departures");
      var thead = el("thead");
      var hr = el("tr");
      var thFav = el("th", "c-fav");
      thFav.scope = "col";
      thFav.appendChild(ti("span", "sr-only", "panel.favSr"));
      hr.appendChild(thFav);
      var ths = {};
      COLS.forEach(function (c) {
        var th = el("th", "c-" + c.id);
        th.scope = "col";
        var labelKey = c.id === "station" ? (b === "arrivals" ? "panel.col.from" : "panel.col.to") : "panel.col." + c.id + ".label";
        if (c.sort) {
          var sb = ti("button", "pnl-sortbtn", labelKey);
          sb.type = "button";
          ta(sb, "title", "panel.sortBy." + c.id);
          sb.addEventListener("click", function () { sortBy(c.sort); });
          th.appendChild(sb);
        } else {
          th.appendChild(ti("span", "pnl-th-label", labelKey));
        }
        ta(th, "title", c.tip ? "panel.col." + c.id + ".tip" : "panel.col." + c.id + ".full");
        if (c.tip) ta(th, "aria-label", "panel.col." + c.id + ".tip");
        ths[c.id] = th;
        hr.appendChild(th);
      });
      thead.appendChild(hr);
      var tbody = el("tbody");
      tbody.addEventListener("click", onRowClick);
      tbody.addEventListener("keydown", onRowKey);
      table.append(cap, thead, tbody);
      var empty = el("p", "pnl-empty", T("panel.noMatch"));
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

    // atribuirea rămâne vizibilă și în ecran complet (unde footer-ul paginii nu se vede)
    var credit = el("p", "pnl-credit");
    var cfr = el("a", null, "cfr.ro");
    cfr.href = "https://cfr.ro";
    cfr.target = "_blank";
    cfr.rel = "noopener noreferrer";
    // same text as the page footer (text nodes kept so a language change can refresh them)
    d.creditText = document.createTextNode("");
    credit.append(d.creditText, cfr);
    var om = el("a", null, "Open-Meteo.com");
    om.href = "https://open-meteo.com/";
    om.target = "_blank";
    om.rel = "noopener noreferrer";
    var wxCredit = el("span", "wx-credit");
    d.wxLead = document.createTextNode("");
    wxCredit.append(d.wxLead, om, " · CC BY 4.0");
    credit.appendChild(wxCredit);
    renderCredit();

    pnl.append(head, status, d.banner, controls, d.legend, d.body, d.detail, credit);
    root.append(d.switch, pnl);
    return true;
  }

  // ---- render ----------------------------------------------------------------------

  function renderCredit() {
    var d = S.dom;
    if (d.creditText) d.creditText.nodeValue = "© 2026 Andy217Ace · " + T("footer.credit") + " ";
    if (d.wxLead) d.wxLead.nodeValue = " · " + T("footer.meteo") + " ";
  }

  function renderLegend() {
    var th = S.cfg.delay_thresholds;
    var items = [
      ["ok", T("panel.legend.ok")],
      ["low", "1–" + th.mid + " min"],
      ["mid", (th.mid + 1) + "–" + th.high + " min"],
      ["high", "> " + th.high + " min"],
      ["unknown", T("panel.legend.unknown")],
      ["recent", T("panel.legend.recent")]
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

  // Celulă cu text lung (stație, operator, mesaj): cel mult 2 rânduri, apoi „…" (CSS).
  // Valoarea completă rămâne în `title` (tooltip), în aria-label-ul rândului și în detaliu,
  // astfel încât lățimea coloanelor și înălțimea rândurilor nu depind de date.
  function clipCell(cls, content, full) {
    var clip = el("span", "pnl-clip");
    if (content instanceof Node) clip.appendChild(content);
    else if (content != null) clip.textContent = content;
    var td = el("td", "c-" + cls);
    if (full) td.title = full;
    td.appendChild(clip);
    return td;
  }

  function fullName(text, t) {
    if (!text) return "";
    return t.uncertain === true ? text + " (" + unsureText() + ")" : text;
  }

  function message(board, t, lvl, fresh) {
    var parts = [];
    if (fresh !== "live") parts.push(T("panel.msg.stale"));
    else if (lvl === "ok") parts.push(T("board.onTime"));
    else if (lvl === "unknown") parts.push(T("panel.msg.unread"));
    else parts.push(T("panel.msg.late"));
    if (t.flagged) parts.push(T("panel.msg.flagged"));
    if (t.uncertain === true) parts.push(T("panel.msg.uncertain"));
    if (isRecent(board, t)) parts.push(T("panel.msg.recent"));
    return parts.join(" · ");
  }

  function delayNode(t, lvl, fresh) {
    // reflexie pe rând: ultima întârziere citită sigur a trenului, cu vechimea ei
    if (t.delay_read !== true && typeof t.delay_last_read_age_s === "number" &&
        typeof t.delay_min === "number" && t.delay_min >= 0) {
      var mins = Math.max(0, Math.round(t.delay_last_read_age_s / 60));
      var ageTxt = mins < 1 ? T("time.agoUnder") : T("time.ago", { age: T("time.min", { n: mins }) });
      var last = el("span", "pnl-delay pnl-last",
        (t.delay_min === 0 ? T("board.onTime") : "+" + t.delay_min + " min") + " (" + T("board.lastRead", { age: ageTxt }) + ")");
      last.setAttribute("aria-label", plural("panel.lastDelayAria", t.delay_min, { n: t.delay_min, age: ageTxt }));
      last.title = T("panel.lastDelayTitle");
      return last;
    }
    if (t.delay_read !== true) {
      var nr = el("span", "pnl-delay pnl-unread", T("board.unread"));
      nr.setAttribute("aria-label", T("board.delayAria.unread"));
      nr.title = T("board.delayTitle.unread");
      return nr;
    }
    if (lvl === "unknown" && !(typeof t.delay_min === "number" && t.delay_min >= 0)) {
      return unknown("delay");
    }
    var d = t.delay_min;
    var s = el("span", "pnl-delay", d === 0 ? T("board.onTime") : "+" + d + " min");
    var label = d === 0 ? T("board.delayAria.onTime") : plural("board.delayAria.late", d, { n: d });
    if (fresh !== "live" || lvl === "unknown") label += " " + T("panel.unconfirmed");
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
    tr.setAttribute("aria-label", T("panel.rowAria", {
      train: (t.train_type || "") + " " + t.train_no,
      where: T(board === "arrivals" ? "board.from" : "board.to") + " " + (t.station ? window.I18N.station(t.station) : T("board.stationUnknown")),
      time: t.sched_time || T("board.timeUnknown") }));

    var isFav = S.favs.has(String(t.train_no));
    var star = el("button", "pnl-star");
    star.type = "button";
    star.dataset.fav = String(t.train_no);
    star.setAttribute("aria-pressed", isFav ? "true" : "false");
    star.setAttribute("aria-label", T(isFav ? "panel.favRemoveAria" : "panel.favAddAria", { no: t.train_no }));
    star.title = T("panel.favTitle");
    star.appendChild(icon(ICONS.star));
    var btns = el("span", "pnl-rowbtns");
    btns.appendChild(star);
    var fol = followButton(t);
    if (fol) btns.appendChild(fol);
    tr.appendChild(cell("fav", btns));

    tr.appendChild(cell("time", t.sched_time ? t.sched_time : unknown("time")));

    var train = el("span", "pnl-train");
    var A = window.TabelaApp || {};
    var abbr = A.typeAbbr ? A.typeAbbr(t.train_type) : t.train_type;
    var type = el("span", typeClass(t.train_type), abbr || "?");
    type.title = T("board.typeTitle", { type: (A.typeName && A.typeName(t.train_type)) || abbr || T("board.typeUnknown") });
    train.append(type, el("span", "pnl-no", String(t.train_no)));
    if (t.flagged) {
      var flag = el("span", "pnl-flag", "*");
      flag.title = T("board.flagTitle");
      flag.setAttribute("aria-label", T("panel.flagAria"));
      train.appendChild(flag);
    }
    tr.appendChild(cell("train", train));

    tr.appendChild(clipCell("station", t.station ? stationLink(t.station, t) : unknown("station"),
      fullName(t.station && window.I18N.station(t.station), t)));
    tr.appendChild(clipCell("op", t.operator ? nameNode(t.operator, t) : unknown("op"),
      fullName(t.operator, t)));
    tr.appendChild(cell("delay", delayNode(t, lvl, fresh)));

    var known = t.platform != null && t.platform !== "";
    var plat = known ? el("span", "pnl-plat", String(t.platform)) : unknown("plat");
    if (known) plat.setAttribute("aria-label", T("board.platAria", { p: t.platform }));
    tr.appendChild(cell("plat", plat));

    tr.appendChild(cell("pest", pestNode(board, t)));

    var msg = message(board, t, lvl, fresh);
    tr.appendChild(clipCell("msg", msg, msg));

    var at = changedAt(board, t);
    if (at != null) {
      var ch = el("span", "pnl-changed", fmtHM.format(new Date(at)));
      ch.title = T("panel.changedTitle");
      tr.appendChild(cell("changed", ch));
    } else {
      tr.appendChild(cell("changed", unknown("changed")));
    }
    return tr;
  }

  // Peron estimat (peron_est.js): doar peste pragul din backtest, altfel „—"; mereu etichetat.
  function pestNode(board, t) {
    var pe = window.TabelaApp && window.TabelaApp.peronEst;
    var est = pe && pe.enabled() ? pe.lookup(board, t) : null;
    var s = el("span", est ? "pnl-pest" : "pnl-unk", est ? est.platform + " · " + est.share_pct + "%" : "—");
    var label = pe ? pe.label(est) : T("panel.pestUnavail");
    s.setAttribute("role", "img");
    s.setAttribute("aria-label", label);
    s.title = label;
    return s;
  }

  // Nume canonic (A2). Dacă potrivirea a fost nesigură: subliniere punctată + titlu.
  function nameNode(text, t) {
    if (t.uncertain !== true) return document.createTextNode(text);
    var s = el("span", "is-uncertain", text);
    s.title = text + " (" + unsureText() + ")";
    s.appendChild(el("span", "sr-only", " (" + unsureText() + ")"));
    return s;
  }

  // Numele stației = link spre pagina ei (#statie?nume=, stats.js); aspectul e moștenit.
  function stationLink(name, t) {
    var a = el("a", "station-link station-link-plain");
    a.href = "#statie?nume=" + encodeURIComponent(name);
    a.appendChild(nameNode(window.I18N.station(name), t));
    return a;
  }

  // Butonul „urmărește" (notificări) din rând — logica e în follows.js (TabelaApp.onFollow).
  function followButton(t) {
    var App = window.TabelaApp;
    if (!App || typeof App.onFollow !== "function") return null;
    var st = typeof App.followState === "function" ? App.followState(t) : null;
    var on = !!(st && st.followed), off = !!(st && st.unsupported);
    var b = el("button", "pnl-star pnl-follow");
    b.type = "button";
    b.setAttribute("aria-pressed", on ? "true" : "false");
    if (off) b.setAttribute("aria-disabled", "true");
    var label = T(on ? "panel.followAria.on" : "panel.followAria.off", { no: t.train_no });
    b.setAttribute("aria-label", label + (off ? ". " + st.reason : ""));
    b.title = off ? st.reason : T(on ? "panel.followTitle.on" : "panel.followTitle.off");
    b.appendChild(icon(ICONS.bell));
    return b;
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
    var opOpts = [["", T("panel.allMasc")]].concat(Array.from(ops).sort().map(function (o) { return [o, o]; }));
    if (S.fOp && !ops.has(S.fOp)) opOpts.push([S.fOp, S.fOp]);
    setOptions(S.dom.fOp, opOpts);
    var plOpts = [["", T("panel.all")]].concat(Array.from(plats).sort(function (a, b) {
      return (parseInt(a, 10) || 0) - (parseInt(b, 10) || 0);
    }).map(function (p) { return [p, T("panel.platOpt", { p: p })]; }));
    if (noPlat) plOpts.push(["__none", T("panel.platNone")]);
    if (S.fPlat && S.fPlat !== "__none" && !plats.has(S.fPlat)) plOpts.push([S.fPlat, T("panel.platOpt", { p: S.fPlat })]);
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
    d.title.textContent = T("panel.title." + S.board);
    Object.keys(d.segBtns).forEach(function (k) {
      d.segBtns[k].setAttribute("aria-pressed", k === S.board ? "true" : "false");
    });
    d.sort.value = S.sort;

    var focused = document.activeElement && document.activeElement.closest &&
      document.activeElement.closest(".pnl-row");
    var focusKey = focused ? focused.dataset.key : null;
    var ae = document.activeElement;
    var focusBtn = ae && ae.classList && ae.classList.contains("pnl-follow") ? ".pnl-follow"
      : (ae && ae.classList && ae.classList.contains("pnl-star") ? ".pnl-star"
      : (ae && ae.classList && ae.classList.contains("station-link") ? ".station-link" : null));

    var shown = 0, total = 0;
    BOARDS.forEach(function (b) {
      var sec = d.sections[b];
      var visible = S.board === "all" || S.board === b;
      sec.sec.hidden = !visible;
      // one panel stale alone (its frames rejected): mark only that panel
      var pb = S.data && S.data.boards && S.data.boards[b];
      sec.sec.dataset.stale = pb && pb.stale && !S.data.stale ? "true" : "false";
      var list = (S.data && S.data[b]) || [];
      var rows = sorted(list.filter(matches));
      sec.tbody.replaceChildren.apply(sec.tbody, rows.map(function (t) { return buildRow(b, t, fresh); }));
      sec.count.textContent = rows.length === list.length ? String(list.length) : rows.length + " / " + list.length;
      sec.empty.hidden = rows.length > 0 || !S.data;
      sec.empty.textContent = list.length ? T("panel.noMatch") : T("app.empty");
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
      if (again) ((focusBtn && again.querySelector(focusBtn)) || again).focus({ preventScroll: true });
    }
    d.stCount.textContent = S.data
      ? (shown === total ? plural("panel.count", shown, { n: nfInt.format(shown) })
        : plural("panel.countOf", total, { n: nfInt.format(shown), total: nfInt.format(total) }))
      : T("panel.countNone");
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
    d.stFresh.textContent = T("panel.fresh." + fresh);

    if (a != null) {
      var when = new Date(Date.now() - a * 1000);
      d.stCapture.textContent = T("panel.capture", { time: fmtTime.format(when), ago: ago(a) });
    } else {
      d.stCapture.textContent = T(S.data ? "panel.captureUnknown" : "panel.captureNone");
    }
    d.stSystem.textContent = fresh === "stale"
      ? (a == null ? T("panel.sys.staleNone") : T("panel.sys.stale", { age: dur(a) }))
      : T("panel.sys." + fresh);
    d.stSystem.dataset.state = fresh;
    d.stSource.textContent = T(fresh === "live" ? "panel.src.live" : "panel.src.unknown");
    d.stSource.dataset.state = fresh;

    var text = "";
    if (fresh === "offline") {
      text = S.data
        ? T("panel.banner.offline", { capture: a != null ? " " + T("panel.banner.captureFrom", { ago: ago(a) }) : "" })
        : T("app.loadFail");
    } else if (fresh === "stale") {
      text = a == null
        ? T("app.banner.neverRead")
        : T("panel.banner.outdated", { age: dur(a) });
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
    var fst = window.TabelaApp && typeof window.TabelaApp.followState === "function"
      ? window.TabelaApp.followState(t) : null;
    var sig = JSON.stringify([S.selected, t, fresh, gone, changedAt(b, t), isRecent(b, t),
                              S.favs.has(String(t.train_no)), fst]);
    if (sig === S.detailSig && !d.detail.hidden) return;
    S.detailSig = sig;

    var head = el("div", "pnl-detail-head");
    var h = el("h3", "pnl-detail-title", (t.train_type || "") + " " + t.train_no);
    h.id = "pnl-detail-title";
    var close = el("button", "pnl-icon-btn");
    close.type = "button";
    close.setAttribute("aria-label", T("panel.closeDetails"));
    close.appendChild(icon(ICONS.close));
    close.addEventListener("click", closeDetail);
    head.append(h, close);

    var dl = el("dl", "pnl-dl");
    var station = t.station ? window.I18N.station(t.station) : null;
    var route = b === "arrivals"
      ? (station ? station : "?") + " → București Nord"
      : "București Nord → " + (station ? station : "?");
    dlRow(dl, T("panel.dl.board"), T(b === "arrivals" ? "board.arrivals" : "board.departures"));
    dlRow(dl, T("panel.dl.route"), station ? nameNode(route, t) : unknown("route"));
    dlRow(dl, T("panel.col.time.full"), t.sched_time || unknown("time"));
    var dd = delayNode(t, lvl, fresh);
    var dWrap = el("span", "pnl-detail-delay");
    dWrap.dataset.level = lvl;
    dWrap.appendChild(dd);
    dlRow(dl, T("panel.dl.lastDelay"), dWrap);
    var known = t.platform != null && t.platform !== "";
    dlRow(dl, T("panel.col.plat.label"), known ? String(t.platform) : unknown("plat"));
    dlRow(dl, T("panel.col.op.label"), t.operator ? nameNode(t.operator, t) : unknown("op"));
    dlRow(dl, T("panel.col.msg.label"), message(b, t, lvl, fresh));
    var at = changedAt(b, t);
    dlRow(dl, T("panel.dl.lastChange"), at != null ? fmtTime.format(new Date(at)) : unknown("changed"));

    var note = el("p", "pnl-detail-note", gone
      ? T("panel.note.gone")
      : T(fresh === "live" ? "panel.note.live" : "panel.note.stale"));

    var acts = el("div", "pnl-detail-actions");
    var hist = el("a", "pnl-btn pnl-btn-primary");
    hist.href = historyHref(t);
    hist.append(icon(ICONS.history), ti("span", "pnl-btn-text", "panel.trainHistory"));
    var isFav = S.favs.has(String(t.train_no));
    var favBtn = button("", isFav ? "panel.favRemoveBtn" : "panel.favAddBtn", ICONS.star);
    favBtn.setAttribute("aria-pressed", isFav ? "true" : "false");
    favBtn.addEventListener("click", function () { toggleFav(String(t.train_no)); });
    acts.append(hist, favBtn);
    if (window.TabelaApp && typeof window.TabelaApp.onFollow === "function") {
      var on = !!(fst && fst.followed);
      var follow = button("", on ? "panel.followBtn.on" : "panel.followBtn.off", ICONS.bell);
      follow.setAttribute("aria-pressed", on ? "true" : "false");
      if (fst && fst.unsupported) { follow.setAttribute("aria-disabled", "true"); follow.title = fst.reason; }
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
    var fol = e.target.closest(".pnl-follow");
    if (fol) {
      var row0 = fol.closest(".pnl-row");
      var found = row0 && findTrain(row0.dataset.key);
      if (found && window.TabelaApp && typeof window.TabelaApp.onFollow === "function") {
        window.TabelaApp.onFollow(found.t, fol);
      }
      return;
    }
    var star = e.target.closest(".pnl-star");
    if (star && star.dataset.fav) { toggleFav(star.dataset.fav); return; }
    if (e.target.closest("a")) return; // link de stație: navighează, nu deschide detaliile
    var row = e.target.closest(".pnl-row");
    if (row) openDetail(row.dataset.key);
  }

  function onRowKey(e) {
    var row = e.target.closest(".pnl-row");
    if (!row || e.target.closest(".pnl-star, a")) return;
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
      el("span", "pnl-btn-text", T(on ? "panel.exitFullscreen" : "panel.fullscreen")));
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

  // GET /api/config e încărcat o singură dată de app.js (sursă unică); aici doar îl aplicăm.
  function loadConfig() {
    var App = window.TabelaApp;
    var p = App && typeof App.config === "function" ? App.config() : Promise.resolve(DEFAULTS);
    return Promise.resolve(p)
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
    S.hidden.delete("pest");
    if (!peronOn()) S.hidden.add("pest");  // estimarea e implicit ascunsă
    try {
      var favs = JSON.parse(load(KEYS.fav) || "[]");
      S.favs = new Set(Array.isArray(favs) ? favs.map(String) : []);
    } catch (e) { S.favs = new Set(); }
  }

  function peronOn() {
    try { return localStorage.getItem("tabela.peronEst") === "1"; } catch (e) { return false; }
  }

  // comutatorul „Arată peron estimat" (peron_est.js) sau estimările noi au schimbat starea
  document.addEventListener("tabela:peronest", function () {
    if (!S.dom || !S.dom.body) return;
    var pe = window.TabelaApp && window.TabelaApp.peronEst;
    var on = pe ? pe.enabled() : false;
    if (on) S.hidden.delete("pest"); else S.hidden.add("pest");
    var cb = document.getElementById("pnl-col-pest");
    if (cb) cb.checked = on;
    applyCols();
    if (S.view === "panou") render();
  });

  // limba s-a schimbat: textele statice (data-i18n), apoi tot ce se construiește din date
  document.addEventListener("i18n:change", function () {
    var d = S.dom;
    if (!d || !d.pnl) return;
    if (window.I18N) { window.I18N.applyDom(d.switch); window.I18N.applyDom(d.pnl); }
    setOptions(d.fDelay, delayOptions());
    setOptions(d.sort, sortOptions());
    renderCredit();
    renderLegend();
    refreshOptions();
    updateFsButton();
    if (window.TabelaApp && typeof window.TabelaApp.renderThemeButtons === "function") {
      window.TabelaApp.renderThemeButtons();
    }
    S.detailSig = null;
    render();
  });

  // ascultăm imediat: primul fetch al app.js poate termina înainte de init
  document.addEventListener("tabela:board", onBoard);
  // starea „urmărit" s-a schimbat (follows.js → TabelaApp.refreshFollowButtons)
  document.addEventListener("tabela:follows", function () { if (S.view === "panou") render(); });

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
    if (window.TabelaApp && typeof window.TabelaApp.renderThemeButtons === "function") {
      window.TabelaApp.renderThemeButtons();
    }
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

  // the dictionaries must be loaded before the first build (t() returns the key until then)
  function boot() { (window.I18N ? window.I18N.ready : Promise.resolve()).then(init); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
