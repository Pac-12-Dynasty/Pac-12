// Builds a team page live from Sleeper.
// Every team page uses this same file. It figures out which team to show
// from the page's filename, e.g. olaves-medical-team.html -> "Olave's Medical Team".
(function () {
  var BASE_LEAGUE_ID = "1315706586127171584";
  var API = "https://api.sleeper.app/v1";

  var NFL = {
    ARI: "Cardinals", ATL: "Falcons", BAL: "Ravens", BUF: "Bills", CAR: "Panthers",
    CHI: "Bears", CIN: "Bengals", CLE: "Browns", DAL: "Cowboys", DEN: "Broncos",
    DET: "Lions", GB: "Packers", HOU: "Texans", IND: "Colts", JAX: "Jaguars",
    KC: "Chiefs", LV: "Raiders", LAC: "Chargers", LAR: "Rams", MIA: "Dolphins",
    MIN: "Vikings", NE: "Patriots", NO: "Saints", NYG: "Giants", NYJ: "Jets",
    PHI: "Eagles", PIT: "Steelers", SF: "49ers", SEA: "Seahawks", TB: "Buccaneers",
    TEN: "Titans", WAS: "Commanders"
  };
  var POS_ORDER = { QB: 1, RB: 2, WR: 3, TE: 4, K: 5, DEF: 6 };

  var statusEl = document.getElementById("status");

  function slug(name) {
    return name.toLowerCase()
      .replace(/['’]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function pageSlug() {
    var file = decodeURIComponent(location.pathname.split("/").pop() || "");
    return file.replace(/\.html$/i, "").toLowerCase();
  }

  function getJSON(url) {
    return fetch(url, { cache: "no-cache" }).then(function (res) {
      if (!res.ok) throw new Error(url + " returned " + res.status);
      return res.json();
    });
  }

  function points(whole, decimal) {
    return (whole || 0) + (decimal || 0) / 100;
  }

  function teamName(user, roster) {
    return (user && user.metadata && user.metadata.team_name) ||
           (user && user.display_name) || ("Team " + roster.roster_id);
  }

  function age(p) {
    if (p.birth_date) {
      var years = (Date.now() - new Date(p.birth_date).getTime()) / (365.25 * 24 * 3600 * 1000);
      return years.toFixed(1);
    }
    return p.age ? String(p.age) : "";
  }

  function rankText(p) {
    if (!p.rank) return "";
    return "#" + p.rank + (p.pos_rank ? " (" + p.pos_rank + ")" : "");
  }

  var INJ = { Questionable: "Q", Doubtful: "D", Out: "OUT", IR: "IR", PUP: "PUP", Sus: "SUS", NA: "NA", DNR: "DNR", COV: "COV" };

  function injuryBadge(p) {
    if (!p.injury) return null;
    var level = { Questionable: "low", Doubtful: "mid", NA: "info" }[p.injury] || "high";
    var span = document.createElement("span");
    span.className = "inj " + level;
    span.textContent = INJ[p.injury] || p.injury;
    span.title = p.injury + (p.injury_part ? " (" + p.injury_part + ")" : "");
    return span;
  }

  function ordinal(n) {
    var s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  // Works out which future picks a roster owns, including ones gained or traded away
  function picksFor(rosterId, league, rosters, traded) {
    var rounds = 4;   // rookie draft rounds per season
    var season = Number(league.season);
    var first = league.status === "pre_draft" || league.status === "drafting" ? season : season + 1;
    var seasons = [first, first + 1, first + 2];

    var current = {};
    (traded || []).forEach(function (t) {
      current[t.season + "-" + t.round + "-" + t.roster_id] = t.owner_id;
    });

    var owned = [], away = [];
    seasons.forEach(function (yr) {
      for (var rd = 1; rd <= rounds; rd++) {
        rosters.forEach(function (r) {
          var key = yr + "-" + rd + "-" + r.roster_id;
          var owner = current.hasOwnProperty(key) ? current[key] : r.roster_id;
          if (owner === rosterId) owned.push({ season: yr, round: rd, from: r.roster_id });
          else if (r.roster_id === rosterId) away.push({ season: yr, round: rd, to: owner });
        });
      }
    });
    return { owned: owned, away: away };
  }

  function cell(text) {
    var td = document.createElement("td");
    td.textContent = text;
    return td;
  }

  function addRow(tbody, slotLabel, pid, players) {
    var tr = document.createElement("tr");
    tr.className = "player";
    tr.appendChild(cell(slotLabel));
    var p = pid && pid !== "0" ? players[pid] : null;
    if (!pid || pid === "0") {
      tr.appendChild(cell("Empty"));
      tr.appendChild(cell(""));
      tr.appendChild(cell(""));
      tr.appendChild(cell(""));
      tr.appendChild(cell(""));
    } else if (!p) {
      tr.appendChild(cell("Player " + pid));
      tr.appendChild(cell(""));
      tr.appendChild(cell(""));
      tr.appendChild(cell(""));
      tr.appendChild(cell(""));
    } else {
      tr.dataset.pid = pid;
      tr.title = "See game log and career stats";
      var nameCell = cell(p.name);
      var badge = injuryBadge(p);
      if (badge) nameCell.appendChild(badge);
      tr.appendChild(nameCell);
      tr.appendChild(cell(p.pos));
      tr.appendChild(cell(NFL[p.team] || p.team || "FA"));
      tr.appendChild(cell(age(p)));
      tr.appendChild(cell(rankText(p)));
    }
    tbody.appendChild(tr);
  }

  // ---------- Player card: game log and career stats ----------
  var COLS = {
    QB: [["Cmp/Att", function (s) { return (s.pass_cmp || 0) + "/" + (s.pass_att || 0); }], ["Pass Yd", "pass_yd"], ["Pass TD", "pass_td"], ["INT", "pass_int"], ["Rush Yd", "rush_yd"], ["Rush TD", "rush_td"]],
    RB: [["Att", "rush_att"], ["Rush Yd", "rush_yd"], ["Rush TD", "rush_td"], ["Rec", "rec"], ["Rec Yd", "rec_yd"], ["Rec TD", "rec_td"]],
    WR: [["Tgt", "rec_tgt"], ["Rec", "rec"], ["Rec Yd", "rec_yd"], ["Rec TD", "rec_td"], ["Rush Yd", "rush_yd"]],
    TE: [["Tgt", "rec_tgt"], ["Rec", "rec"], ["Rec Yd", "rec_yd"], ["Rec TD", "rec_td"]],
    K: [["FG", function (s) { return (s.fgm || 0) + "/" + (s.fga || 0); }], ["XP", "xpm"]],
    DEF: [["Sacks", "sack"], ["INT", "int"], ["Fum Rec", "fum_rec"], ["TD", "def_td"], ["Pts Allowed", "pts_allow"]]
  };

  // Offensive snap share: snaps played / team snaps
  function snapPct(s) {
    s = s || {};
    return s.off_snp && s.tm_off_snp ? Math.round(s.off_snp / s.tm_off_snp * 100) + "%" : "-";
  }
  ["QB", "RB", "WR", "TE"].forEach(function (pos) { COLS[pos].unshift(["Snap %", snapPct]); });

  function statValue(col, s) {
    var v = typeof col[1] === "function" ? col[1](s || {}) : (s || {})[col[1]];
    if (typeof v === "string") return v;
    return v == null || v === "" ? "0" : String(Math.round(v * 10) / 10);
  }

  function statTable(firstCols, rows, pos) {
    var cols = COLS[pos] || COLS.WR;
    var wrap = document.createElement("div");
    wrap.className = "table-wrap";
    var t = document.createElement("table");
    var head = document.createElement("tr");
    firstCols.map(function (c) { return c[0]; }).concat(cols.map(function (c) { return c[0]; })).forEach(function (h) {
      var th = document.createElement("th");
      th.textContent = h;
      head.appendChild(th);
    });
    t.appendChild(head);
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      firstCols.forEach(function (c) { tr.appendChild(cell(c[1](r))); });
      cols.forEach(function (c) { tr.appendChild(cell(statValue(c, r.stats))); });
      t.appendChild(tr);
    });
    wrap.appendChild(t);
    return wrap;
  }

  function openPlayer(pid, p) {
    var old = document.getElementById("player-modal");
    if (old) old.remove();
    var overlay = document.createElement("div");
    overlay.id = "player-modal";
    overlay.className = "modal-overlay";
    var box = document.createElement("div");
    box.className = "modal";
    overlay.appendChild(box);

    var close = document.createElement("button");
    close.type = "button";
    close.className = "modal-close";
    close.setAttribute("aria-label", "Close");
    close.textContent = "×";
    box.appendChild(close);

    var h = document.createElement("h2");
    h.textContent = p.name || "Player";
    box.appendChild(h);
    var meta = document.createElement("p");
    meta.className = "status";
    meta.textContent = [p.pos, NFL[p.team] || p.team || "FA", p.birth_date || p.age ? "Age " + age(p) : "", rankText(p),
      p.injury ? p.injury + (p.injury_part ? " (" + p.injury_part + ")" : "") : ""].filter(Boolean).join(" · ");
    box.appendChild(meta);

    var body = document.createElement("div");
    body.textContent = "Loading stats...";
    box.appendChild(body);

    function shut() { overlay.remove(); document.removeEventListener("keydown", onKey); }
    function onKey(e) { if (e.key === "Escape") shut(); }
    close.onclick = shut;
    overlay.addEventListener("click", function (e) { if (e.target === overlay) shut(); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(overlay);

    getJSON("data/players/" + encodeURIComponent(pid) + ".json").then(function (data) {
      body.innerHTML = "";
      var pos = p.pos || "WR";
      var rankCols = [
        ["Pos Rk", function (r) { return r.pos_rank || "-"; }],
        ["Ovr Rk", function (r) { return r.ovr_rank ? "#" + r.ovr_rank : "-"; }]
      ];

      // Tabs: Game Log and Season Stats
      var tabs = document.createElement("div");
      tabs.className = "modal-tabs";
      var panes = {};
      function show(name) {
        Object.keys(panes).forEach(function (k) { panes[k].hidden = k !== name; });
        tabs.querySelectorAll("button").forEach(function (b) { b.classList.toggle("active", b.dataset.tab === name); });
      }
      [["log", data.season + " Game Log"], ["seasons", "Season Stats"]].forEach(function (tab) {
        var b = document.createElement("button");
        b.type = "button";
        b.dataset.tab = tab[0];
        b.textContent = tab[1];
        b.onclick = function () { show(tab[0]); };
        tabs.appendChild(b);
        panes[tab[0]] = document.createElement("div");
      });
      body.appendChild(tabs);
      body.appendChild(panes.log);
      body.appendChild(panes.seasons);

      // Game log
      if (!data.log.length) {
        var none = document.createElement("p");
        none.className = "status";
        none.textContent = "No games played yet this season.";
        panes.log.appendChild(none);
      } else {
        var total = data.log.reduce(function (sum, g) { return sum + g.pts; }, 0);
        var sumLine = document.createElement("p");
        sumLine.className = "status";
        sumLine.textContent = total.toFixed(2) + " pts in " + data.log.length + " games (" + (total / data.log.length).toFixed(2) + " per game). Weeks he didn't play are left out.";
        panes.log.appendChild(sumLine);
        panes.log.appendChild(statTable([["Wk", function (g) { return String(g.week); }], ["Pts", function (g) { return g.pts.toFixed(2); }]]
          .concat(rankCols), data.log.slice().reverse(), pos));
      }

      // Season stats
      if (!data.career.length) {
        var none2 = document.createElement("p");
        none2.className = "status";
        none2.textContent = "No NFL stats on record yet.";
        panes.seasons.appendChild(none2);
      } else {
        panes.seasons.appendChild(statTable([
          ["Season", function (c) { return String(c.season); }],
          ["GP", function (c) { return String(c.gp); }],
          ["Pts", function (c) { return c.pts.toFixed(2); }],
          ["Pts/G", function (c) { return c.gp ? (c.pts / c.gp).toFixed(2) : "0"; }],
          ["Finish", function (c) { return c.pos_rank || "-"; }],
          ["Ovr", function (c) { return c.ovr_rank ? "#" + c.ovr_rank : "-"; }]
        ], data.career, pos));
      }

      var note = document.createElement("p");
      note.className = "status";
      note.textContent = "Fantasy points and ranks use this league's scoring settings. Pos Rk is where he finished at his position; Ovr Rk ranks QBs, RBs, WRs, and TEs together. Regular season only. Updated daily.";
      body.appendChild(note);
      show("log");
    }).catch(function () {
      body.textContent = "Stats for this player aren't available yet. They update once a day.";
    });
  }

  function byPosition(players) {
    return function (a, b) {
      var pa = players[a] || {}, pb = players[b] || {};
      return ((POS_ORDER[pa.pos] || 9) - (POS_ORDER[pb.pos] || 9)) ||
             String(pa.name || a).localeCompare(String(pb.name || b));
    };
  }

  var findLeague = window.pac12 && window.pac12.leagueId ? window.pac12.leagueId() : Promise.resolve(BASE_LEAGUE_ID);

  findLeague.then(function (LEAGUE_ID) {
    return Promise.all([
    getJSON(API + "/league/" + LEAGUE_ID),
    getJSON(API + "/league/" + LEAGUE_ID + "/rosters"),
    getJSON(API + "/league/" + LEAGUE_ID + "/users"),
    getJSON("data/players.json").catch(function () { return {}; }),
    getJSON(API + "/league/" + LEAGUE_ID + "/traded_picks").catch(function () { return []; }),
    getJSON("data/legacy.json").catch(function () { return null; })
    ]);
  }).then(function (results) {
    var league = results[0], rosters = results[1], users = results[2], players = results[3], traded = results[4], legacy = results[5];

    var userById = {};
    users.forEach(function (u) { userById[u.user_id] = u; });

    // Standings order: best record (ties count as half a win), then most points for
    function pct(st) {
      var g = (st.wins || 0) + (st.losses || 0) + (st.ties || 0);
      return g ? ((st.wins || 0) + (st.ties || 0) / 2) / g : 0;
    }
    var ranked = rosters.slice().sort(function (a, b) {
      var sa = a.settings || {}, sb = b.settings || {};
      return (pct(sb) - pct(sa)) ||
             (points(sb.fpts, sb.fpts_decimal) - points(sa.fpts, sa.fpts_decimal));
    });

    var target = pageSlug(), roster = null, user = null;
    rosters.forEach(function (r) {
      var u = userById[r.owner_id];
      if (slug(teamName(u, r)) === target) { roster = r; user = u; }
    });

    if (!roster) {
      statusEl.textContent = "Couldn't match this page to a Sleeper team. The filename must match the team name in Sleeper (for example, " +
        rosters.map(function (r) { return slug(teamName(userById[r.owner_id], r)) + ".html"; }).slice(0, 3).join(", ") + ").";
      return;
    }

    var name = teamName(user, roster);
    document.title = name + " | Pac 12 Dynasty";
    document.getElementById("team-name").textContent = name;
    document.getElementById("team-owner").textContent = "Owner: " + ((user && user.display_name) || "Unknown");

    // Season stats
    var s = roster.settings || {};
    var record = (s.wins || 0) + "-" + (s.losses || 0) + (s.ties ? "-" + s.ties : "");
    var statsRow = document.getElementById("stats-row");
    statsRow.innerHTML = "";
    statsRow.appendChild(cell(String(ranked.indexOf(roster) + 1)));
    statsRow.appendChild(cell(record));
    statsRow.appendChild(cell(points(s.fpts, s.fpts_decimal).toFixed(2)));
    statsRow.appendChild(cell(points(s.fpts_against, s.fpts_against_decimal).toFixed(2)));

    // Legacy card: all-time record, titles, and top 2 rivals (follows the owner)
    var hist = legacy && legacy.owners && roster.owner_id ? legacy.owners[roster.owner_id] : null;
    if (hist) {
      var lc = document.createElement("div");
      lc.className = "card";
      var lh = document.createElement("h2");
      lh.textContent = "Legacy";
      lc.appendChild(lh);
      var games = hist.w + hist.l + hist.t;
      var winPct = games ? ((hist.w + hist.t / 2) / games * 100).toFixed(1) + "%" : "-";
      var summary = document.createElement("p");
      summary.textContent = "All-time: " + hist.w + "-" + hist.l + (hist.t ? "-" + hist.t : "") + " (" + winPct + ") over " +
        hist.seasons.length + " season" + (hist.seasons.length === 1 ? "" : "s") + ".";
      lc.appendChild(summary);
      var honors = document.createElement("p");
      honors.textContent = "Championships: " + hist.titles + " · Runner-ups: " + hist.runner_up +
        " · 3rd place: " + (hist.third || 0) +
        " · #1 overall picks: " + (hist.first_overall || []).length + " · Playoff trips: " + hist.playoffs;
      lc.appendChild(honors);
      var rv = (legacy.rivals || {})[roster.owner_id] || [];
      rv.forEach(function (r, i) {
        var opp = legacy.owners[r.opponent] || {};
        var line = document.createElement("p");
        var strong = document.createElement("strong");
        strong.textContent = "Rival " + (i + 1) + ": ";
        line.appendChild(strong);
        var link = document.createElement("a");
        link.href = slug(opp.team || "") + ".html";
        link.textContent = opp.team || "Unknown";
        line.appendChild(link);
        line.appendChild(document.createTextNode(" (" + r.wins + "-" + r.losses + (r.ties ? "-" + r.ties : "") + ", score " + r.score.toFixed(2) + ")"));
        lc.appendChild(line);
      });
      var more = document.createElement("p");
      var ml = document.createElement("a");
      ml.href = "team-legacy.html?owner=" + encodeURIComponent(roster.owner_id);
      ml.textContent = "View " + name + "'s full legacy →";
      more.appendChild(ml);
      lc.appendChild(more);
      var firstCard = document.querySelector("main .card");
      firstCard.parentNode.insertBefore(lc, firstCard.nextSibling);
    }

    // Add a Rank column to every roster table
    document.querySelectorAll("thead tr").forEach(function (tr) {
      var th = document.createElement("th");
      th.textContent = "Rank";
      tr.appendChild(th);
    });

    // Starters, in the league's lineup order
    var slots = (league.roster_positions || []).filter(function (p) {
      return ["BN", "IR", "TAXI"].indexOf(p) === -1;
    });
    var starters = roster.starters || [];
    var startersBody = document.getElementById("starters");
    slots.forEach(function (slot, i) {
      var label = slot === "SUPER_FLEX" ? "SFLEX" : slot;
      addRow(startersBody, label, starters[i], players);
    });

    // IR, taxi, and bench
    var reserve = roster.reserve || [];
    var taxi = roster.taxi || [];
    var used = {};
    starters.concat(reserve, taxi).forEach(function (id) { used[id] = true; });
    var bench = (roster.players || []).filter(function (id) { return !used[id]; }).sort(byPosition(players));

    var settings = league.settings || {};
    var benchSlots = (league.roster_positions || []).filter(function (p) { return p === "BN"; }).length;
    var irSlots = settings.reserve_slots != null ? settings.reserve_slots : 1;
    var taxiSlots = settings.taxi_slots != null ? settings.taxi_slots : 3;

    function fill(id, label, list, size) {
      var tbody = document.getElementById(id);
      list.forEach(function (pid) { addRow(tbody, label, pid, players); });
      for (var i = list.length; i < size; i++) addRow(tbody, label, null, players);
    }
    fill("bench", "BN", bench, benchSlots);
    fill("ir", "IR", reserve.slice().sort(byPosition(players)), irSlots);
    fill("taxi", "TAXI", taxi.slice().sort(byPosition(players)), taxiSlots);

    // Draft picks, from Sleeper's traded pick records
    var nameByRoster = {};
    rosters.forEach(function (r) { nameByRoster[r.roster_id] = teamName(userById[r.owner_id], r); });
    var picks = picksFor(roster.roster_id, league, rosters, traded);

    var pickCard = document.createElement("div");
    pickCard.className = "card";
    var pickTitle = document.createElement("h2");
    pickTitle.textContent = "Draft Picks";
    pickCard.appendChild(pickTitle);

    var list = document.createElement("ul");
    list.className = "pick-list";
    picks.owned.forEach(function (p) {
      var li = document.createElement("li");
      li.textContent = p.season + " " + ordinal(p.round) + " Round Pick" +
        (p.from === roster.roster_id ? "" : " (" + nameByRoster[p.from] + ")");
      list.appendChild(li);
    });
    if (!picks.owned.length) {
      var none = document.createElement("li");
      none.textContent = "No picks in the next three drafts.";
      list.appendChild(none);
    }
    pickCard.appendChild(list);

    if (picks.away.length) {
      var awayNote = document.createElement("p");
      awayNote.className = "status";
      awayNote.textContent = "Traded away: " + picks.away.map(function (p) {
        return p.season + " " + ordinal(p.round) + " Round Pick (to " + nameByRoster[p.to] + ")";
      }).join(", ") + ".";
      pickCard.appendChild(awayNote);
    }

    var cards = document.querySelectorAll("main .card");
    var notesCard = cards[cards.length - 1];
    notesCard.parentNode.insertBefore(pickCard, notesCard);

    // Ranking source disclaimer
    var note = document.createElement("p");
    note.className = "status";
    note.innerHTML = 'Player ranks are 1QB dynasty rankings from <a href="https://github.com/dynastyprocess/data" target="_blank" rel="noopener">DynastyProcess</a>, based on FantasyPros dynasty expert consensus and updated weekly. Kickers and defenses are not ranked. Ranks are for reference only and are not official league values.';
    document.querySelector("main").appendChild(note);

    statusEl.textContent = "Live from Sleeper. Last loaded " + new Date().toLocaleString() + ".";

    // Click a player to see his game log and career stats
    document.querySelectorAll("p").forEach(function (para) {
      if (/swap them/.test(para.textContent)) para.textContent = "Click a player to see his game log and career stats.";
    });
    var oldMsg = document.getElementById("roster-msg");
    if (oldMsg) oldMsg.remove();
    document.querySelectorAll("tr.player").forEach(function (row) {
      if (!row.dataset.pid) { row.style.cursor = "default"; return; }
      row.addEventListener("click", function () { openPlayer(row.dataset.pid, players[row.dataset.pid] || {}); });
    });
  }).catch(function (err) {
    statusEl.textContent = "Couldn't load this team from Sleeper right now. Try refreshing in a minute. (" + err.message + ")";
  });
})();
