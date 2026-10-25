// Draws a points-leaders block: a leader card for Overall and each position,
// plus a collapsible full leaderboard with tabs. Used by legacy.html and team-legacy.html.
(function () {
  var TABS = ["overall", "QB", "RB", "WR", "TE", "K", "DEF"];
  var LABEL = { overall: "Overall", QB: "QB", RB: "RB", WR: "WR", TE: "TE", K: "K", DEF: "DEF" };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function years(list) {
    if (!list || !list.length) return "";
    return list.length === 1 ? String(list[0]) : list[0] + "–" + list[list.length - 1];
  }

  // leaders: { overall: [...], QB: [...], ... }
  // opts.teamsFor(row) -> text listing teams (league view only)
  window.renderLeaders = function (container, leaders, opts) {
    opts = opts || {};
    container.innerHTML = "";
    if (!leaders || !leaders.overall || !leaders.overall.length) {
      container.appendChild(el("p", "muted", "Points leaders fill in once games are played."));
      return;
    }

    // Leader cards
    var cards = el("div", "leader-cards");
    TABS.forEach(function (key) {
      var top = (leaders[key] || [])[0];
      var card = el("div", "leader-card" + (key === "overall" ? " overall" : ""));
      card.appendChild(el("div", "leader-label", LABEL[key] + " leader"));
      if (!top) {
        card.appendChild(el("div", "muted", "None yet"));
      } else {
        card.appendChild(el("div", "leader-name", top.player));
        card.appendChild(el("div", "leader-points", top.points.toFixed(2) + " pts"));
        card.appendChild(el("div", "muted", (key === "overall" ? top.pos + " · " : "") +
          top.games + " games · " + years(top.seasons)));
      }
      cards.appendChild(card);
    });
    container.appendChild(cards);

    // Full leaderboard, collapsible, with position tabs
    var fold = el("details", "leader-fold");
    fold.appendChild(el("summary", "", "Full leaderboard"));
    var tabs = el("div", "leader-tabs");
    var wrap = el("div", "table-wrap");
    var table = el("table");
    wrap.appendChild(table);

    function show(key) {
      tabs.querySelectorAll("button").forEach(function (b) { b.classList.toggle("active", b.dataset.key === key); });
      table.innerHTML = "";
      var head = el("tr");
      var cols = ["#", "Player", "Pos", "Points", "Games", "Seasons"];
      if (opts.teamsFor) cols.push("Teams");
      cols.forEach(function (c) { head.appendChild(el("th", "", c)); });
      table.appendChild(head);
      var rows = leaders[key] || [];
      if (!rows.length) {
        var tr0 = el("tr"); var td0 = el("td", "muted", "No one yet."); td0.colSpan = cols.length; tr0.appendChild(td0); table.appendChild(tr0);
      }
      rows.forEach(function (r, i) {
        var tr = el("tr");
        tr.appendChild(el("td", "", String(i + 1)));
        tr.appendChild(el("td", "", r.player));
        tr.appendChild(el("td", "", r.pos));
        tr.appendChild(el("td", "", r.points.toFixed(2)));
        tr.appendChild(el("td", "", String(r.games)));
        tr.appendChild(el("td", "", years(r.seasons)));
        if (opts.teamsFor) tr.appendChild(el("td", "", opts.teamsFor(r)));
        table.appendChild(tr);
      });
    }

    TABS.forEach(function (key) {
      var b = el("button", "", LABEL[key]);
      b.type = "button";
      b.dataset.key = key;
      b.onclick = function () { show(key); };
      tabs.appendChild(b);
    });
    fold.appendChild(tabs);
    fold.appendChild(wrap);
    container.appendChild(fold);
    show("overall");
  };
})();
