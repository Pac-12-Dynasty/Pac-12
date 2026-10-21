// Builds a team page live from Sleeper.
// Every team page uses this same file. It figures out which team to show
// from the page's filename, e.g. olaves-medical-team.html -> "Olave's Medical Team".
(function () {
  var LEAGUE_ID = "1315706586127171584";
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
    } else if (!p) {
      tr.appendChild(cell("Player " + pid));
      tr.appendChild(cell(""));
      tr.appendChild(cell(""));
      tr.appendChild(cell(""));
    } else {
      tr.appendChild(cell(p.name));
      tr.appendChild(cell(p.pos));
      tr.appendChild(cell(NFL[p.team] || p.team || "FA"));
      tr.appendChild(cell(age(p)));
    }
    tbody.appendChild(tr);
  }

  function byPosition(players) {
    return function (a, b) {
      var pa = players[a] || {}, pb = players[b] || {};
      return ((POS_ORDER[pa.pos] || 9) - (POS_ORDER[pb.pos] || 9)) ||
             String(pa.name || a).localeCompare(String(pb.name || b));
    };
  }

  Promise.all([
    getJSON(API + "/league/" + LEAGUE_ID),
    getJSON(API + "/league/" + LEAGUE_ID + "/rosters"),
    getJSON(API + "/league/" + LEAGUE_ID + "/users"),
    getJSON("data/players.json").catch(function () { return {}; })
  ]).then(function (results) {
    var league = results[0], rosters = results[1], users = results[2], players = results[3];

    var userById = {};
    users.forEach(function (u) { userById[u.user_id] = u; });

    // Standings order: most wins, then most points for
    var ranked = rosters.slice().sort(function (a, b) {
      var sa = a.settings || {}, sb = b.settings || {};
      return ((sb.wins || 0) - (sa.wins || 0)) ||
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

    statusEl.textContent = "Live from Sleeper. Last loaded " + new Date().toLocaleString() + ".";

    // Turn on lineup swapping now that the rows exist
    var swap = document.createElement("script");
    swap.src = "roster.js";
    document.body.appendChild(swap);
  }).catch(function (err) {
    statusEl.textContent = "Couldn't load this team from Sleeper right now. Try refreshing in a minute. (" + err.message + ")";
  });
})();
