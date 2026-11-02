# Builds data/analyzer.json for the Trade Analyzer page:
#   - every rostered player with dynasty value, age, this season's rank, and injury
#   - every team's draft picks for the next 3 drafts, with projected slot and value
#   - each team's profile: contender to rebuilder score
#   - each owner's trading tendencies from league trade history
import csv
import io
import json
import math
import os
import urllib.request
from datetime import datetime, timezone

BASE_LEAGUE_ID = "1315706586127171584"
API = "https://api.sleeper.app/v1"
DP = "https://raw.githubusercontent.com/dynastyprocess/data/master/files"
ROUNDS = 4

# Draft lottery for the 6 non-playoff teams. Seed = finish in the standings (12 = worst).
# Balls per seed; they draw for picks 1 through 6, and every round uses the same order.
LOTTERY_BALLS = {12: 35, 11: 27, 10: 20, 9: 10, 8: 6, 7: 3}

# League market: how much this league has paid for each kind of asset compared to
# market value, learned from past trades. SHRINK pulls small samples back toward
# market (higher = trust league history less), and the result is capped at LIMITS.
SHRINK = 4
LIMITS = (0.8, 1.25)
STUD_POWER = 1.25


def category(asset):
    if "round" in asset:
        return "1st" if asset["round"] == 1 else ("2nd" if asset["round"] == 2 else "3rd+")
    return asset.get("pos") or "?"


def league_market(history):
    """Learns, per asset type, whether this league pays above or below market value."""
    def combine(vals):
        return sum(max(v, 0) ** STUD_POWER for v in vals) ** (1 / STUD_POWER)

    sums = {}
    for tr in history:
        sides = tr.get("sides", [])
        if len(sides) != 2:
            continue
        assets = [sd.get("players", []) + sd.get("picks", []) for sd in sides]
        if any(not a for a in assets):
            continue
        if any(x.get("was_value") in (None, 0) for a in assets for x in a):
            continue   # only trades where every piece has a market value
        totals = [combine([x["was_value"] for x in a]) for a in assets]
        for me, other in ((0, 1), (1, 0)):
            # What this side paid relative to what it got; above 1 = paid over market
            lr = math.log(totals[other] / totals[me])
            got = sum(x["was_value"] for x in assets[me])
            for x in assets[me]:
                w = x["was_value"] / got
                c = sums.setdefault(category(x), {"lr": 0.0, "w": 0.0, "trades": set()})
                c["lr"] += w * lr
                c["w"] += w
                c["trades"].add(tr.get("id"))
    out = {}
    for cat, c in sums.items():
        avg = c["lr"] / c["w"] if c["w"] else 0
        factor = math.exp(avg * c["w"] / (c["w"] + SHRINK))
        out[cat] = {"factor": round(min(LIMITS[1], max(LIMITS[0], factor)), 3), "trades": len(c["trades"])}
    return out


def compact_trades(history):
    """Past trades with market values at the time, for showing comparable deals."""
    out = []
    for tr in history:
        sides = []
        for sd in tr.get("sides", []):
            items = [{"id": p.get("id"), "name": p.get("name"), "pos": p.get("pos"), "was_value": p.get("was_value")}
                     for p in sd.get("players", [])]
            items += [{"name": f"{pk['season']} Round {pk['round']}", "pos": "PICK", "round": pk["round"],
                       "was_value": pk.get("was_value")} for pk in sd.get("picks", [])]
            if sd.get("faab"):
                items.append({"name": f"${sd['faab']} FAAB", "pos": "FAAB", "was_value": None})
            sides.append({"owner": sd.get("owner"), "gets": items})
        out.append({"id": tr.get("id"), "date": tr.get("date"), "season": tr.get("season"), "sides": sides})
    return out


def lottery_odds(balls):
    """Exact chance of each seed landing each lottery pick, drawing balls without replacement."""
    from itertools import permutations
    seeds = list(balls)
    odds = {s: [0.0] * len(seeds) for s in seeds}
    for order in permutations(seeds):
        p, left = 1.0, sum(balls.values())
        for s in order:
            p *= balls[s] / left
            left -= balls[s]
        for slot, s in enumerate(order):
            odds[s][slot] += p
    return odds   # seed -> [chance of pick 1, pick 2, ...]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pac12-dynasty-site"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return res.read().decode("utf-8")


def get(url):
    return json.loads(fetch(url))


def current_league(base_id, state):
    target = int(state.get("league_season") or state.get("season"))
    league = get(f"{API}/league/{base_id}")
    season = int(league["season"])
    users = sorted(get(f"{API}/league/{base_id}/users"), key=lambda u: not u.get("is_owner"))[:4]
    league_id = base_id
    while season < target:
        nxt, found = season + 1, None
        for u in users:
            try:
                for l in get(f"{API}/user/{u['user_id']}/leagues/nfl/{nxt}") or []:
                    if l.get("previous_league_id") == league_id:
                        found = l
                        break
            except Exception:
                continue
            if found:
                break
        if not found:
            break
        league_id, season = found["league_id"], nxt
    return league_id


def age_from(birth):
    try:
        b = datetime.strptime(birth, "%Y-%m-%d")
        return round((datetime.now() - b).days / 365.25, 1)
    except Exception:
        return None


def pct_rank(values, v, higher_is_better=True):
    """0 = worst in the league, 1 = best."""
    if len(values) < 2:
        return 0.5
    below = sum(1 for x in values if (x < v if higher_is_better else x > v))
    return below / (len(values) - 1)


def main():
    state = get(f"{API}/state/nfl")
    lid = current_league(BASE_LEAGUE_ID, state)
    league = get(f"{API}/league/{lid}")
    rosters = get(f"{API}/league/{lid}/rosters")
    users = {u["user_id"]: u for u in get(f"{API}/league/{lid}/users")}
    traded = get(f"{API}/league/{lid}/traded_picks") or []
    season = int(league["season"])
    pre_draft = league.get("status") in ("pre_draft", "drafting")
    next_draft = season if pre_draft else season + 1

    with open("data/players.json") as f:
        pinfo = json.load(f)

    # ---------- Value curve: DynastyProcess rank -> value ----------
    curve = []
    for r in csv.DictReader(io.StringIO(fetch(f"{DP}/values-players.csv"))):
        try:
            curve.append((float(r["ecr_1qb"]), float(r["value_1qb"])))
        except (TypeError, ValueError):
            pass
    curve.sort()

    def value_at(ecr):
        if not curve:
            return 0
        if ecr <= curve[0][0]:
            return curve[0][1]
        for (e1, v1), (e2, v2) in zip(curve, curve[1:]):
            if e1 <= ecr <= e2:
                return v1 + (v2 - v1) * ((ecr - e1) / (e2 - e1) if e2 > e1 else 0)
        return curve[-1][1]

    # ---------- Pick values ----------
    # DynastyProcess lists: exact slots for the next draft, early/mid/late for the
    # one after, and a single value per round for the third year.
    slotted, tiered, generic = {}, {}, {}
    for r in csv.DictReader(io.StringIO(fetch(f"{DP}/values-picks.csv"))):
        name = r["player"]
        try:
            v = round(value_at(float(r["ecr_1qb"])))
        except (TypeError, ValueError):
            continue
        parts = name.split()
        if "Pick" in name and "." in parts[-1]:          # "2026 Pick 1.04"
            rd, slot = parts[-1].split(".")
            slotted[(int(rd), int(slot))] = v
        elif parts[1] in ("Early", "Mid", "Late"):       # "2027 Early 1st"
            tiered.setdefault(int(parts[0]), {})[(parts[1], int(parts[2][0]))] = v
        else:                                            # "2028 1st"
            generic.setdefault(int(parts[0]), {})[int(parts[1][0])] = v
    tier_year = min(tiered) if tiered else None
    generic_years = sorted(generic)

    # ---------- Team standings and profiles ----------
    def pts(w, d):
        return (w or 0) + (d or 0) / 100

    teams = {}
    for r in rosters:
        uid = r.get("owner_id")
        if not uid:
            continue
        s = r.get("settings") or {}
        g = (s.get("wins") or 0) + (s.get("losses") or 0) + (s.get("ties") or 0)
        u = users.get(uid, {})
        starters = [p for p in (r.get("starters") or []) if p and p != "0"]
        ages = [age_from(pinfo.get(p, {}).get("birth_date")) for p in starters]
        ages = [a for a in ages if a]
        teams[uid] = {
            "roster_id": r["roster_id"],
            "team": (u.get("metadata") or {}).get("team_name") or u.get("display_name") or "Unknown",
            "owner": u.get("display_name") or "Unknown",
            "record": f"{s.get('wins') or 0}-{s.get('losses') or 0}" + (f"-{s['ties']}" if s.get("ties") else ""),
            "win_pct": ((s.get("wins") or 0) + (s.get("ties") or 0) / 2) / g if g else 0.5,
            "pf": round(pts(s.get("fpts"), s.get("fpts_decimal")), 2),
            "starter_age": round(sum(ages) / len(ages), 1) if ages else None,
            "players": r.get("players") or [],
        }

    # Standings order (record, then points), used to project draft slots
    order = sorted(teams, key=lambda u: (-teams[u]["win_pct"], -teams[u]["pf"]))
    n = len(order)
    wins = [t["win_pct"] for t in teams.values()]
    pfs = [t["pf"] for t in teams.values()]
    ages_all = [t["starter_age"] for t in teams.values() if t["starter_age"]]
    for i, uid in enumerate(order):
        t = teams[uid]
        t["standing"] = i + 1
        t["projected_slot"] = n - i      # worst team picks first
        age_score = 1 - pct_rank(ages_all, t["starter_age"]) if t["starter_age"] and ages_all else 0.5
        # Older starting lineups lean contender, so younger lowers the score
        score = 0.45 * pct_rank(wins, t["win_pct"]) + 0.35 * pct_rank(pfs, t["pf"]) + 0.20 * (1 - age_score)
        t["contender_score"] = round(score, 2)
        t["window"] = "Contender" if score >= 0.62 else ("Rebuilder" if score <= 0.38 else "Middle")

    roster_owner = {t["roster_id"]: uid for uid, t in teams.items()}

    # ---------- Every team's picks ----------
    current = {}
    for t in traded:
        current[(int(t["season"]), int(t["round"]), t["roster_id"])] = t["owner_id"]
    odds = lottery_odds(LOTTERY_BALLS)
    picks = []
    for yr in (next_draft, next_draft + 1, next_draft + 2):
        for rd in range(1, ROUNDS + 1):
            for uid in order:
                orig_rid = teams[uid]["roster_id"]
                owner_rid = current.get((yr, rd, orig_rid), orig_rid)
                slot = teams[uid]["projected_slot"]
                note = ""
                if yr == next_draft and teams[uid]["standing"] in odds:
                    # Lottery team: value is the average over every pick it could land
                    chances = odds[teams[uid]["standing"]]
                    v = sum(c * (slotted.get((rd, k + 1)) or 0) for k, c in enumerate(chances))
                    best = max(range(len(chances)), key=lambda k: chances[k])
                    label = f"{yr} Round {rd} (lottery)"
                    note = f"{chances[0] * 100:.1f}% at {rd}.01, most likely {rd}.{best + 1:02d}"
                elif yr == next_draft:
                    v = slotted.get((rd, slot))
                    label = f"{yr} {rd}.{slot:02d} (projected)"
                elif yr == next_draft + 1 and tier_year:
                    tier = "Early" if slot <= n / 3 else ("Late" if slot > 2 * n / 3 else "Mid")
                    v = tiered[tier_year].get((tier, rd))
                    label = f"{yr} {tier} Round {rd}"
                else:
                    gy = generic_years[-1] if generic_years else None
                    v = generic.get(gy, {}).get(rd) if gy else None
                    label = f"{yr} Round {rd}"
                picks.append({
                    "id": f"{yr}-{rd}-{orig_rid}", "season": yr, "round": rd,
                    "owner": roster_owner.get(owner_rid), "original_owner": uid,
                    "label": label, "value": round(v or 0), "note": note,
                })

    # ---------- Players ----------
    players = {}
    for uid, t in teams.items():
        for pid in t["players"]:
            p = pinfo.get(pid, {})
            pos_rank = None
            try:
                with open(f"data/players/{pid}.json") as f:
                    car = json.load(f).get("career") or []
                this = [c for c in car if c.get("season") == season]
                pos_rank = this[0].get("pos_rank") if this else None
            except Exception:
                pass
            players[pid] = {
                "name": p.get("name") or pid, "pos": p.get("pos") or "", "nfl": p.get("team") or "",
                "owner": uid, "age": age_from(p.get("birth_date")) or p.get("age"),
                "value": p.get("value") or 0, "dp_pos_rank": p.get("pos_rank") or "",
                "season_pos_rank": pos_rank, "injury": p.get("injury") or "",
            }
        del t["players"]

    # ---------- Owner tendencies from trade history ----------
    tendencies = {uid: {"trades": 0, "picks_in": 0, "picks_out": 0, "players_in": 0, "players_out": 0,
                        "pos_in": {}, "pos_out": {}} for uid in teams}
    try:
        with open("data/trades.json") as f:
            history = json.load(f).get("trades", [])
    except Exception:
        history = []
    for tr in history:
        sides = tr.get("sides", [])
        for sd in sides:
            me = sd.get("owner")
            if me not in tendencies:
                continue
            tt = tendencies[me]
            tt["trades"] += 1
            tt["picks_in"] += len(sd.get("picks", []))
            tt["players_in"] += len(sd.get("players", []))
            for p in sd.get("players", []):
                tt["pos_in"][p.get("pos") or "?"] = tt["pos_in"].get(p.get("pos") or "?", 0) + 1
            for other in sides:
                if other is sd:
                    continue
                tt["picks_out"] += len(other.get("picks", []))
                tt["players_out"] += len(other.get("players", []))
                for p in other.get("players", []):
                    tt["pos_out"][p.get("pos") or "?"] = tt["pos_out"].get(p.get("pos") or "?", 0) + 1

    os.makedirs("data", exist_ok=True)
    with open("data/analyzer.json", "w") as f:
        json.dump({
            "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "season": season, "next_draft": next_draft,
            "teams": teams, "players": players, "picks": picks, "tendencies": tendencies,
            "league_market": league_market(history), "history": compact_trades(history),
        }, f)
    print(f"Analyzer data: {len(teams)} teams, {len(players)} players, {len(picks)} picks")


if __name__ == "__main__":
    main()
