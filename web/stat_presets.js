// © 2026 Andy217Ace
// Statistici — saved filter presets (up to 5 named sets, localStorage key tabela.statsPresets, this
// device only). Lazy layer: loaded by statistici.js the first time the „Presetări” menu opens (own
// file, not in the SW shell: precache budget). statistici.js owns the filters; this file only keeps
// the list and draws the menu: App.statPresets.fill(menu, msg, h) with h = { el, tt, current(),
// apply(filters), close() }. localStorage in try/catch: when it is unavailable the menu says so.
// Text via textContent only (CSP-safe DOM).
"use strict";

(function () {
  var App = window.TabelaApp;
  var KEY = "tabela.statsPresets";
  var MAX = 5;

  // the list, or null when localStorage is unavailable (blocked, private mode, quota…)
  function load() {
    try {
      var raw = window.localStorage.getItem(KEY);
      var arr = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(arr)) return [];
      return arr.filter(function (x) { return x && typeof x.name === "string" && x.name && x.filters && typeof x.filters === "object"; })
        .slice(0, MAX);
    } catch (e) { return null; }
  }

  function write(list) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(list));
      return true;
    } catch (e) { return false; }
  }

  // "ok", "full" (5 already and a new name) or "unavailable"
  function save(name, filters) {
    var list = load();
    if (!list) return "unavailable";
    var at = -1;
    list.forEach(function (x, i) { if (x.name === name) at = i; });
    if (at < 0 && list.length >= MAX) return "full";
    var entry = { name: name, filters: filters };
    if (at >= 0) list[at] = entry; else list.push(entry);
    return write(list) ? "ok" : "unavailable";
  }

  function remove(i) {
    var list = load();
    if (!list) return;
    list.splice(i, 1);
    write(list);
  }

  function fill(menu, msg, h) {
    var tt = h.tt;
    var list = load();
    if (!list) {
      msg.textContent = tt("stats.preset.unavailable");
      menu.replaceChildren(msg);
      return;
    }
    var nodes = [];
    if (!list.length) nodes.push(h.el("p", "ss-preset-empty", tt("stats.preset.none")));
    else {
      var ul = h.el("ul", "ss-preset-list");
      list.forEach(function (x, i) {
        var li = h.el("li", "ss-preset-item");
        var ap = h.el("button", "btn btn-ghost btn-sm ss-preset-apply", x.name);
        ap.type = "button";
        ap.addEventListener("click", function () { h.apply(x.filters); h.close(); });
        var del = h.el("button", "btn btn-ghost btn-sm ss-preset-del", "×");
        del.type = "button";
        del.setAttribute("aria-label", tt("stats.preset.delete", { name: x.name }));
        del.addEventListener("click", function () { remove(i); msg.textContent = ""; fill(menu, msg, h); });
        li.append(ap, del);
        ul.append(li);
      });
      nodes.push(ul);
    }
    var row = h.el("div", "ss-preset-new");
    var inp = h.el("input", "ss-preset-name");
    inp.type = "text";
    inp.maxLength = 30;
    inp.placeholder = tt("stats.preset.name");
    inp.setAttribute("aria-label", tt("stats.preset.name"));
    var sv = h.el("button", "btn btn-sm ss-preset-save", tt("stats.preset.save"));
    sv.type = "button";
    function doSave() {
      var name = inp.value.trim();
      if (!name) { msg.textContent = tt("stats.preset.need_name"); return; }
      var r = save(name, h.current());
      if (r === "full") { msg.textContent = tt("stats.preset.full", { max: MAX }); return; }
      fill(menu, msg, h);
      if (r === "ok") msg.textContent = tt("stats.preset.saved", { name: name });
    }
    sv.addEventListener("click", doSave);
    inp.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); doSave(); } });
    row.append(inp, sv);
    nodes.push(row, msg);
    menu.replaceChildren.apply(menu, nodes);
  }

  App.statPresets = { fill: fill };
})();
