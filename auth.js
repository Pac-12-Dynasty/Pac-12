// Adds league logins to every page.
// Loads Supabase, shows "Log in" or the owner's name and "Log out" in the nav,
// and only shows parts marked data-members-only to approved league members.
(function () {
  var SUPABASE_URL = "https://pbshfpmkmdxyewzmgluv.supabase.co";
  var SUPABASE_KEY = "sb_publishable_rpVEqpRnWux9GGx2kKfkNA_4A1xPygw";
  var LIB = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.2/dist/umd/supabase.js";

  window.pac12 = window.pac12 || {};

  // ---- Current Sleeper league ----
  // Sleeper gives a dynasty league a new ID every season. Starting from the
  // original league, this follows each season's renewal to the newest one.
  var BASE_LEAGUE_ID = "1315706586127171584";
  var SLEEPER = "https://api.sleeper.app/v1";
  var leaguePromise = null;

  function sleeperJSON(url) {
    return fetch(url).then(function (res) {
      if (!res.ok) throw new Error("Sleeper returned " + res.status);
      return res.json();
    });
  }

  function findCurrentLeague() {
    return Promise.all([
      sleeperJSON(SLEEPER + "/state/nfl"),
      sleeperJSON(SLEEPER + "/league/" + BASE_LEAGUE_ID),
      sleeperJSON(SLEEPER + "/league/" + BASE_LEAGUE_ID + "/users")
    ]).then(function (r) {
      var target = Number(r[0].league_season || r[0].season);
      var id = BASE_LEAGUE_ID;
      var season = Number(r[1].season);
      var userIds = r[2].slice().sort(function (a, b) { return (b.is_owner ? 1 : 0) - (a.is_owner ? 1 : 0); })
        .map(function (u) { return u.user_id; }).slice(0, 4);

      function step() {
        if (season >= target) return id;
        var next = season + 1;
        function tryUser(i) {
          if (i >= userIds.length) return id; // league hasn't renewed yet
          return sleeperJSON(SLEEPER + "/user/" + userIds[i] + "/leagues/nfl/" + next).then(function (leagues) {
            var found = (leagues || []).filter(function (l) { return l.previous_league_id === id; })[0];
            if (!found) return tryUser(i + 1);
            id = found.league_id;
            season = next;
            return step();
          }, function () { return tryUser(i + 1); });
        }
        return tryUser(0);
      }
      return step();
    });
  }

  // Use window.pac12.leagueId().then(function (id) { ... }) anywhere on the site
  window.pac12.leagueId = function () {
    if (leaguePromise) return leaguePromise;
    try {
      var cached = JSON.parse(localStorage.getItem("pac12-league") || "null");
      if (cached && cached.base === BASE_LEAGUE_ID && Date.now() - cached.at < 6 * 3600 * 1000) {
        leaguePromise = Promise.resolve(cached.id);
        return leaguePromise;
      }
    } catch (e) {}
    leaguePromise = findCurrentLeague().then(function (id) {
      try { localStorage.setItem("pac12-league", JSON.stringify({ base: BASE_LEAGUE_ID, id: id, at: Date.now() })); } catch (e) {}
      return id;
    }, function () { return BASE_LEAGUE_ID; });
    return leaguePromise;
  };

  function loadLib(done) {
    if (window.supabase && window.supabase.createClient) return done();
    var s = document.createElement("script");
    s.src = LIB;
    s.onload = done;
    s.onerror = function () { console.warn("Couldn't load the login library."); };
    document.head.appendChild(s);
  }

  // Show or hide members-only sections, with a note for everyone else
  function applyAccess(profile, session) {
    var member = !!(profile && (profile.is_member || profile.is_admin));
    document.body.classList.toggle("pac12-member", member);
    document.querySelectorAll("[data-members-only]").forEach(function (el) {
      var note = el.previousElementSibling;
      if (!note || !note.classList.contains("members-notice")) {
        note = document.createElement("p");
        note.className = "members-notice";
        el.parentNode.insertBefore(note, el);
      }
      note.innerHTML = "";
      if (member) return;
      if (!session) {
        note.appendChild(document.createTextNode("This section is for league members. "));
        var a = document.createElement("a");
        a.href = "login.html";
        a.textContent = "Log in";
        note.appendChild(a);
        note.appendChild(document.createTextNode(" to see it."));
      } else {
        note.textContent = "This section is for league members. Your account is waiting for commissioner approval.";
      }
    });
    window.pac12.profile = profile;
    window.pac12.isMember = member;
    window.dispatchEvent(new CustomEvent("pac12-profile", { detail: { profile: profile, member: member } }));
  }

  loadLib(function () {
    var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
    window.pac12.sb = sb;
    window.dispatchEvent(new Event("pac12-auth-ready"));

    var nav = document.querySelector("nav");
    var slot = document.createElement("span");
    slot.className = "nav-auth";
    if (nav) {
      nav.appendChild(slot);
      if (!nav.querySelector('a[href="news.html"]')) {
        var news = document.createElement("a");
        news.href = "news.html";
        news.textContent = "News";
        nav.insertBefore(news, slot);
      }
    }

    var renderCount = 0;

    function render(session) {
      var thisRender = ++renderCount;
      slot.innerHTML = "";
      if (!session) {
        var login = document.createElement("a");
        login.href = "login.html";
        login.textContent = "Log in";
        slot.appendChild(login);
        applyAccess(null, null);
        return;
      }
      var who = document.createElement("a");
      who.href = "login.html";
      who.textContent = session.user.email;
      slot.appendChild(who);
      var out = document.createElement("button");
      out.type = "button";
      out.textContent = "Log out";
      out.onclick = function () { sb.auth.signOut(); };
      slot.appendChild(out);

      sb.from("profiles").select("id, display_name, is_admin, is_member, can_post").eq("id", session.user.id).maybeSingle()
        .then(function (res) {
          if (thisRender !== renderCount) return; // a newer login state already redrew the nav
          var p = res.data || {};
          who.textContent = (p.display_name || session.user.email) + (p.is_admin ? " (admin)" : "");
          if (p.is_admin) {
            var admin = document.createElement("a");
            admin.href = "admin.html";
            admin.textContent = "Admin";
            slot.insertBefore(admin, who);
          }
          applyAccess(res.data, session);
        });
    }

    sb.auth.getSession().then(function (res) { render(res.data.session); });
    sb.auth.onAuthStateChange(function (event, session) { render(session); });
  });
})();
