// Adds league logins to every page.
// Loads Supabase, shows "Log in" or the owner's name and "Log out" in the nav,
// and only shows parts marked data-members-only to approved league members.
(function () {
  // If a page loads this file twice, only run it once (otherwise the login area shows up twice)
  if (window.__pac12AuthLoaded) return;
  window.__pac12AuthLoaded = true;

  var SUPABASE_URL = "https://pbshfpmkmdxyewzmgluv.supabase.co";
  var SUPABASE_KEY = "sb_publishable_rpVEqpRnWux9GGx2kKfkNA_4A1xPygw";
  var LIB = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.2/dist/umd/supabase.js";

  window.pac12 = window.pac12 || {};

  // ---- Visitor counts (GoatCounter) ----
  // Change GOATCOUNTER_CODE to the code you picked when signing up at goatcounter.com
  var GOATCOUNTER_CODE = "pac12fantasy";
  (function () {
    if (!GOATCOUNTER_CODE || location.hostname === "localhost") return;
    var gc = document.createElement("script");
    gc.async = true;
    gc.src = "https://gc.zgo.at/count.js";
    gc.setAttribute("data-goatcounter", "https://" + GOATCOUNTER_CODE + ".goatcounter.com/count");
    document.head.appendChild(gc);
  })();

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

  // ---- Site header ----
  // Every page gets the same header from here, so it only has to be changed in one place.
  // It is built right away so it doesn't wait for logins to load.
  var HEADER_CSS = [
    ':root{--p12-black:#050505;--p12-paper:#ECE6DC;--p12-pink:#E65BC4;}',
    'nav.site-nav{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-start;gap:.2rem;margin:0;background:var(--p12-black);padding:.4rem max(1rem,calc((100% - 1160px)/2 + 1rem));border-bottom:3px solid var(--p12-pink);font-family:"Barlow",system-ui,sans-serif;font-size:17px;line-height:1.55;}',
    'nav.site-nav a{color:var(--p12-paper);text-decoration:none;font-weight:600;padding:.5rem .75rem;border-radius:6px;}',
    'nav.site-nav a:hover{background:var(--p12-pink);color:var(--p12-black);}',
    'nav.site-nav a[aria-current="page"]{box-shadow:inset 0 -3px 0 var(--p12-pink);border-radius:0;}',
    'nav.site-nav a.brand{font-family:"Big Shoulders Display","Arial Narrow",sans-serif;font-weight:900;font-size:1.35rem;color:var(--p12-pink);margin-right:auto;padding-left:0;box-shadow:none;}',
    'nav.site-nav a.brand:hover{background:none;color:var(--p12-paper);}',
    'nav.site-nav .home-link,nav.site-nav .menu-toggle{display:none;}',
    'nav.site-nav .nav-auth{display:inline-flex;align-items:center;gap:.15rem;margin-left:.6rem;padding-left:.6rem;border-left:1px solid rgba(236,230,220,.25);color:var(--p12-paper);}',
    'nav.site-nav .nav-auth a{padding:.5rem .6rem;}',
    'nav.site-nav .nav-auth button{background:none;border:1px solid rgba(236,230,220,.4);color:var(--p12-paper);font:inherit;font-weight:600;padding:.3rem .7rem;border-radius:6px;cursor:pointer;margin-left:.3rem;}',
    'nav.site-nav .nav-auth button:hover{background:var(--p12-pink);color:var(--p12-black);border-color:var(--p12-pink);}',
    'nav.site-nav :focus-visible{outline:3px solid var(--p12-pink);outline-offset:2px;}',
    '@media (max-width:700px){',
    'nav.site-nav{padding:.35rem 1rem;gap:0;}',
    'nav.site-nav a.brand{display:none;}',
    'nav.site-nav .menu-toggle{display:flex;width:100%;align-items:center;justify-content:space-between;background:none;border:0;color:var(--p12-pink);font-family:"Big Shoulders Display","Arial Narrow",sans-serif;font-weight:900;font-size:1.45rem;padding:.35rem 0;cursor:pointer;}',
    'nav.site-nav .menu-toggle span{font-size:1rem;transition:transform .2s;}',
    'nav.site-nav.open .menu-toggle span{transform:rotate(180deg);}',
    'nav.site-nav>a,nav.site-nav .nav-auth{display:none;}',
    'nav.site-nav.open>a:not(.brand),nav.site-nav.open .nav-auth{display:block;width:100%;padding:.7rem .1rem;border-top:1px solid rgba(236,230,220,.14);border-left:0;border-radius:0;margin:0;box-shadow:none;}',
    'nav.site-nav.open>a:not(.brand):hover{background:none;color:var(--p12-pink);}',
    'nav.site-nav.open>a[aria-current="page"]{color:var(--p12-pink);}',
    'nav.site-nav.open .nav-auth{display:flex;}',
    '}',
    /* Older pages still have a title band in a <header> tag: match the black band on the new pages */
    'body>header{background:var(--p12-black);color:var(--p12-paper);text-align:left;padding:2rem max(1rem,calc((100% - 1160px)/2 + 1rem)) 2.2rem;}',
    'body>header h1{font-family:"Big Shoulders Display","Arial Narrow",sans-serif;font-weight:900;font-size:clamp(2.4rem,7vw,4.4rem);line-height:.95;margin:0;color:var(--p12-paper);}',
    'body>header p{color:#cfc7bb;margin:.6rem 0 0;font-family:"Barlow",system-ui,sans-serif;font-weight:600;}',
    'body>header a{color:var(--p12-paper);}'
  ].join("\n");

  var TABS = [
    ["teams.html", "Teams"], ["standings.html", "Standings"], ["news.html", "News"],
    ["transactions.html", "Transactions"], ["analyzer.html", "Analyzer"], ["legacy.html", "Legacy"]
  ];

  // Which tab to underline for the page you're on
  function currentTab() {
    var file = (location.pathname.split("/").pop() || "index.html").toLowerCase();
    if (file === "trades.html") return "transactions.html";
    if (file === "team-legacy.html") return "legacy.html";
    if (file === "team.html" || file === "teams.html") return "teams.html";
    for (var i = 0; i < TABS.length; i++) if (TABS[i][0] === file) return file;
    // The old one-file-per-team pages (olaves-medical-team.html and so on)
    if (document.getElementById("team-name")) return "teams.html";
    return "";
  }

  (function buildHeader() {
    if (!document.getElementById("pac12-fonts")) {
      var f = document.createElement("link");
      f.id = "pac12-fonts";
      f.rel = "stylesheet";
      f.href = "https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;800;900&family=Barlow:wght@400;500;600;700&display=swap";
      document.head.appendChild(f);
    }
    if (!document.getElementById("pac12-header-css")) {
      var st = document.createElement("style");
      st.id = "pac12-header-css";
      st.textContent = HEADER_CSS;
      document.head.appendChild(st);
    }

    var navs = document.querySelectorAll("nav");
    if (!navs.length) return;
    // If old code got left at the bottom of a file, there will be a second header. Remove it.
    for (var i = 1; i < navs.length; i++) {
      console.warn("Pac 12: this page has more than one header. The file probably still has old code pasted under the new code.");
      navs[i].remove();
    }

    var nav = navs[0];
    // Older pages put the title above the nav. The header always goes at the very top.
    if (nav.parentNode === document.body && document.body.firstElementChild !== nav) {
      document.body.insertBefore(nav, document.body.firstChild);
    }
    nav.id = "site-nav";
    nav.className = "site-nav";
    nav.innerHTML = "";
    var cur = currentTab();

    var brand = document.createElement("a");
    brand.href = "index.html";
    brand.className = "brand";
    brand.textContent = "Pac 12 Dynasty";
    nav.appendChild(brand);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "menu-toggle";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "site-nav");
    btn.innerHTML = 'Pac 12 Dynasty <span aria-hidden="true">&#9662;</span>';
    nav.appendChild(btn);

    var home = document.createElement("a");
    home.href = "index.html";
    home.className = "home-link";
    home.textContent = "Home";
    nav.appendChild(home);

    TABS.forEach(function (t) {
      var a = document.createElement("a");
      a.href = t[0];
      a.textContent = t[1];
      if (t[0] === cur) a.setAttribute("aria-current", "page");
      nav.appendChild(a);
    });

    // Phone menu: tap the pink name to open or close
    function set(open) { nav.classList.toggle("open", open); btn.setAttribute("aria-expanded", open ? "true" : "false"); }
    btn.addEventListener("click", function () { set(!nav.classList.contains("open")); });
    nav.addEventListener("click", function (e) { if (e.target.tagName === "A") set(false); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") set(false); });
  })();

  loadLib(function () {
    var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
    window.pac12.sb = sb;
    window.dispatchEvent(new Event("pac12-auth-ready"));

    var nav = document.querySelector("nav");
    var slot = (nav && nav.querySelector(".nav-auth")) || document.createElement("span");
    slot.className = "nav-auth";
    if (nav && !slot.parentNode) nav.appendChild(slot);

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
          var full = p.display_name || session.user.email.split("@")[0];
          who.textContent = full.split(" ")[0];
          who.title = (p.display_name || session.user.email) + (p.is_admin ? " (admin)" : "");
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
