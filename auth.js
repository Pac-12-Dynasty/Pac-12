// Adds league logins to every page.
// Loads Supabase, then shows "Log in" or the owner's name and "Log out" in the nav.
(function () {
  var SUPABASE_URL = "https://pbshfpmkmdxyewzmgluv.supabase.co";
  var SUPABASE_KEY = "sb_publishable_rpVEqpRnWux9GGx2kKfkNA_4A1xPygw";
  var LIB = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.2/dist/umd/supabase.js";

  window.pac12 = window.pac12 || {};

  function loadLib(done) {
    if (window.supabase && window.supabase.createClient) return done();
    var s = document.createElement("script");
    s.src = LIB;
    s.onload = done;
    s.onerror = function () { console.warn("Couldn't load the login library."); };
    document.head.appendChild(s);
  }

  loadLib(function () {
    var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
    window.pac12.sb = sb;
    window.dispatchEvent(new Event("pac12-auth-ready"));

    var nav = document.querySelector("nav");
    if (!nav) return;
    var slot = document.createElement("span");
    slot.className = "nav-auth";
    nav.appendChild(slot);

    function render(session) {
      slot.innerHTML = "";
      if (!session) {
        var login = document.createElement("a");
        login.href = "login.html";
        login.textContent = "Log in";
        slot.appendChild(login);
        return;
      }
      var who = document.createElement("a");
      who.href = "login.html";
      who.textContent = session.user.email;
      slot.appendChild(who);
      sb.from("profiles").select("display_name, is_admin").eq("id", session.user.id).maybeSingle()
        .then(function (res) {
          var p = res.data || {};
          who.textContent = (p.display_name || session.user.email) + (p.is_admin ? " (admin)" : "");
        });
      var out = document.createElement("button");
      out.type = "button";
      out.textContent = "Log out";
      out.onclick = function () { sb.auth.signOut(); };
      slot.appendChild(out);
    }

    sb.auth.getSession().then(function (res) { render(res.data.session); });
    sb.auth.onAuthStateChange(function (event, session) { render(session); });
  });
})();
