# Builds the league's own player and pick values by blending three sources:
#   1. DynastyProcess   expert consensus (FantasyPros dynasty rankings)
#   2. FantasyCalc      values from real trades across thousands of leagues
#   3. League trades    how this league has actually priced each position and pick round
# Every source is first put on the same scale: each player's rank is converted to the
# value FantasyCalc gives that rank, so a steep curve in one source doesn't distort the blend.
# Saves data/values.json and rewrites the value and rank fields in data/players.json.
import csv
import io
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

# ---- Settings: how much each source counts ----
WEIGHTS = {"dynastyprocess": 0.4, "fantasycalc": 0.4, "league": 0.2}
FC_URL = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=1&numTeams=12&ppr=1"
DP = "https://raw.githubusercontent.com/dynastyprocess/data/master/files"
POSITIONS = ("QB", "RB", "WR", "TE")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pac12-dynasty-site"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return res.read().decode("utf-8")


def curve_at(curve, rank):
    """Value at a (possibly fractional) rank on the shared curve; past the end it keeps tapering."""
    if not curve:
        return 0.0
    if rank <= 1:
        return curve[0]
    i = int(rank) - 1
    if i + 1 < len(curve):
        frac = rank - int(rank)
        return curve[i] + (curve[i + 1] - curve[i]) * frac
    return max(0.0, curve[-1] * (len(curve) / rank) ** 2)


def parse_pick(name):
    """Turns a pick name into a lookup key. Handles '2027 Pick 1.04', '2027 1.04',
    '2027 Early 1st', '2027 1st', and '2027 Round 1'."""
    yr = re.search(r"(20\d\d)", name)
    slot = re.search(r"\b(\d)\.(\d\d)\b", name)
    if slot:
        return ("slot", int(slot.group(1)), int(slot.group(2)))
    rnd = re.search(r"(\d)(?:st|nd|rd|th)\b|Round (\d)", name)
    if not yr or not rnd:
        return None
    r = int(rnd.group(1) or rnd.group(2))
    tier = re.search(r"(Early|Mid|Late)", name)
    if tier:
        return ("tier", int(yr.group(1)), tier.group(1), r)
    return ("generic", int(yr.group(1)), r)


def category(key_or_pos):
    if isinstance(key_or_pos, tuple):
        r = key_or_pos[-1] if key_or_pos[0] != "slot" else key_or_pos[1]
        return "1st" if r == 1 else ("2nd" if r == 2 else "3rd+")
    return key_or_pos


def main():
    # ---------- FantasyCalc ----------
    fc_players, fc_picks = {}, {}
    try:
        for e in json.loads(fetch(FC_URL)):
            p = e.get("player") or {}
            v = float(e.get("value") or 0)
            if (p.get("position") or "").upper() == "PICK" or "pick" in (p.get("name") or "").lower() and not p.get("sleeperId"):
                key = parse_pick(p.get("name") or "")
                if key:
                    fc_picks[key] = v
            elif p.get("sleeperId"):
                fc_players[str(p["sleeperId"])] = {"value": v, "pos": p.get("position") or "", "name": p.get("name")}
        print(f"FantasyCalc: {len(fc_players)} players, {len(fc_picks)} picks")
    except Exception as err:
        print(f"FantasyCalc unavailable, blending without it: {err}")

    # Shared scale: FantasyCalc's values by rank (players only)
    curve = sorted((p["value"] for p in fc_players.values()), reverse=True)

    # ---------- DynastyProcess ----------
    dp_players, dp_picks = {}, {}
    try:
        ids = {r["fantasypros_id"]: r["sleeper_id"] for r in csv.DictReader(io.StringIO(fetch(f"{DP}/db_playerids.csv")))
               if r.get("fantasypros_id") and r.get("sleeper_id") not in (None, "", "NA")}
        rows = list(csv.DictReader(io.StringIO(fetch(f"{DP}/values-players.csv"))))
        rows.sort(key=lambda r: -float(r.get("value_1qb") or 0))
        if not curve:   # no FantasyCalc today: fall back to DynastyProcess's own scale
            curve = [float(r.get("value_1qb") or 0) for r in rows]
        for rank, r in enumerate(rows, start=1):
            sid = ids.get(r.get("fp_id"))
            if sid:
                dp_players[sid] = {"value": curve_at(curve, rank), "raw": float(r.get("value_1qb") or 0), "pos": r.get("pos")}
        for r in csv.DictReader(io.StringIO(fetch(f"{DP}/values-picks.csv"))):
            key = parse_pick(r.get("player") or "")
            try:
                ecr = float(r["ecr_1qb"])
            except (KeyError, TypeError, ValueError):
                continue
            if key:
                dp_picks[key] = curve_at(curve, ecr)   # a pick's ECR is the player rank it's worth
        print(f"DynastyProcess: {len(dp_players)} players, {len(dp_picks)} picks")
    except Exception as err:
        print(f"DynastyProcess unavailable: {err}")

    # ---------- League trades: what this league pays vs. market, by position and pick round ----------
    try:
        with open("data/analyzer.json") as f:
            league = json.load(f).get("league_market") or {}
    except Exception:
        league = {}

    w_dp, w_fc, w_lg = WEIGHTS["dynastyprocess"], WEIGHTS["fantasycalc"], WEIGHTS["league"]

    def blend(dp, fc, cat):
        parts = [(w_dp, dp), (w_fc, fc)]
        parts = [(w, v) for w, v in parts if v is not None]
        if not parts:
            return None
        base = sum(w * v for w, v in parts) / sum(w for w, _ in parts)
        factor = (league.get(cat) or {}).get("factor", 1.0)
        share = w_lg / (w_lg + sum(w for w, _ in parts))
        return base * (1 - share + share * factor)

    players = {}
    for sid in set(dp_players) | set(fc_players):
        dp, fc = dp_players.get(sid), fc_players.get(sid)
        pos = (fc or dp).get("pos") or ""
        v = blend(dp["value"] if dp else None, fc["value"] if fc else None, pos)
        players[sid] = {"value": round(v), "dp": round(dp["value"]) if dp else None,
                        "fc": round(fc["value"]) if fc else None, "pos": pos}

    picks = {}
    for key in set(dp_picks) | set(fc_picks):
        v = blend(dp_picks.get(key), fc_picks.get(key), category(key))
        picks[key] = round(v)

    # ---------- Ranks from the blended values ----------
    order = sorted(players.items(), key=lambda kv: -kv[1]["value"])
    pos_count = {}
    for overall, (sid, p) in enumerate(order, start=1):
        pos_count[p["pos"]] = pos_count.get(p["pos"], 0) + 1
        p["rank"], p["pos_rank"] = overall, f"{p['pos']}{pos_count[p['pos']]}"

    os.makedirs("data", exist_ok=True)
    with open("data/values.json", "w") as f:
        json.dump({
            "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "weights": WEIGHTS, "curve": [round(v) for v in curve[:800]],
            "players": players,
            "picks": [list(k) + [v] for k, v in picks.items()],
        }, f)

    # ---------- Rostered players get the blended values ----------
    try:
        with open("data/players.json") as f:
            roster = json.load(f)
        for sid, info in roster.items():
            p = players.get(sid)
            info["value"] = p["value"] if p else None
            info["rank"] = p["rank"] if p else None
            info["pos_rank"] = p["pos_rank"] if p else ""
            info["dp_value"] = p["dp"] if p else None
            info["fc_value"] = p["fc"] if p else None
        with open("data/players.json", "w") as f:
            json.dump(roster, f, indent=1, sort_keys=True)
    except Exception as err:
        print(f"Couldn't update players.json: {err}")

    print(f"Blended values: {len(players)} players, {len(picks)} picks")


if __name__ == "__main__":
    main()
