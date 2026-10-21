// Lets visitors swap players between roster spots.
// Each player's position, NFL team, age, and rank move with them.
// The Slot column (QB, RB, BN, IR, TAXI) stays in place.
(function () {
  var eligible = {
    QB: ["QB"], RB: ["RB"], WR: ["WR"], TE: ["TE"],
    FLEX: ["RB", "WR", "TE"], DEF: ["DEF"], K: ["K"],
    BN: null, IR: null, TAXI: null   // null means any position
  };
  var rows = document.querySelectorAll("tr.player");
  var msg = document.getElementById("roster-msg");
  var selected = null;

  function slot(row) { return row.cells[0].textContent.trim().toUpperCase(); }
  function name(row) { return row.cells[1].textContent.trim(); }
  function pos(row) { return row.cells[2].textContent.trim().toUpperCase(); }
    function isEmpty(row) { var n = name(row); return n === "" || n === "Player Name" || n === "Empty"; }
  
  function fits(row, targetSlot) {
    if (isEmpty(row)) return true;
    var allowed = eligible[targetSlot];
    if (!allowed) return true;
    return allowed.indexOf(pos(row)) !== -1;
  }

  function say(text, bad) {
    if (!msg) return;
    msg.textContent = text;
    msg.className = bad ? "roster-msg bad" : "roster-msg";
  }

  function clear() {
    if (selected) selected.classList.remove("selected");
    selected = null;
  }

  rows.forEach(function (row) {
    row.addEventListener("click", function () {
      if (!selected) {
        selected = row;
        row.classList.add("selected");
        if (isEmpty(row)) {
          say("Selected an empty " + slot(row) + " spot. Now click the player to move here.");
        } else {
          say("Selected " + name(row) + ". Now click the spot to move him to.");
        }
        return;
      }
      if (selected === row) { clear(); say(""); return; }

      var a = selected, b = row;
      if (isEmpty(a) && isEmpty(b)) { clear(); say("Both spots are empty, so there's nothing to swap.", true); return; }
      if (!fits(a, slot(b))) { say(name(a) + " (" + pos(a) + ") can't play " + slot(b) + ".", true); return; }
      if (!fits(b, slot(a))) { say(name(b) + " (" + pos(b) + ") can't play " + slot(a) + ".", true); return; }

      for (var i = 1; i < a.cells.length; i++) {
        var temp = a.cells[i].innerHTML;
        a.cells[i].innerHTML = b.cells[i].innerHTML;
        b.cells[i].innerHTML = temp;
      }
      clear();
      say("Swapped.");
    });
  });
})();
