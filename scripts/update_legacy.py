# Builds the league's all-time history from Sleeper and saves:
#   data/legacy.json     - everything the Legacy page and team pages show
#   data/rivalries.csv   - the full rivalry spreadsheet for every owner
# Stats follow the owner (Sleeper user), not the team name.
import csv
import json
import os
import urllib.request
from datetime import datetime, timezone

BASE_LEAGUE_ID = "1315706586127171584"
API = "https://api.sleeper.app/v1"
MAX_WEEKS = 18


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pac12-dynasty-site"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


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


def all_seasons(latest_id):
    """Newest league first, following previous_league_id back to the start."""
    out, lid = [], latest_id
    while lid and lid != "0" and len(out) < 30:
        league = get(f"{API}/league/{lid}")
        out.append(league)
        lid = league.get("previous_league_id")
    return out


def points(x):
    return round(float(x or 0), 2)


def build():
    state = get(f"{API}/state/nfl")
    seasons = all_seasons(current_league(BASE_LEAGUE_ID, state))

    try:
        with open("data/players.json") as f:
            player_info = json.load(f)
    except Exception:
        player_info = {}
    try:
        with open("cache/all_players.json") as f:
            every_player = json.load(f)
    except Exception:
        every_player = {}

    # Points leaders: fantasy points scored in a team's starting lineup
    franchise_pts = {}   # owner -> player -> {"points", "games", "seasons"}
    league_pts = {}      # player -> {"points", "games", "seasons", "owners"}

    owners = {}          # user_id -> name info and totals
    pair = {}            # (a, b) with a < b -> head-to-head numbers
    champions, drafts, games_log = [], [], []
    season_playoffs = {}

    def owner(uid):
        return owners.setdefault(uid, {
            "id": uid, "name": None, "team": None, "seasons": [],
            "w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0,
            "pw": 0, "pl": 0, "playoffs": 0, "titles": 0, "runner_up": 0, "third": 0,
            "first_overall": [], "by_season": [],
        })

    for league in reversed(seasons):  # oldest first
        lid, yr = league["league_id"], int(league["season"])
        settings = league.get("settings") or {}
        playoff_start = settings.get("playoff_week_start") or 15
        rosters = get(f"{API}/league/{lid}/rosters")
        users = {u["user_id"]: u for u in get(f"{API}/league/{lid}/users")}
        roster_owner = {r["roster_id"]: r.get("owner_id") for r in rosters if r.get("owner_id")}

        for uid in roster_owner.values():
            o = owner(uid)
            u = users.get(uid, {})
            o["name"] = u.get("display_name") or o["name"] or "Unknown"
            o["team"] = (u.get("metadata") or {}).get("team_name") or o["name"]
            if yr not in o["seasons"]:
                o["seasons"].append(yr)

        # Playoff bracket: which games were playoff games, and in which round
        try:
            bracket = get(f"{API}/league/{lid}/winners_bracket") or []
        except Exception:
            bracket = []
        playoff_round = {}
        third_pairs = set()
        in_playoffs = set()
        title_game, third_game = None, None
        for g in bracket:
            t1, t2, place = g.get("t1"), g.get("t2"), g.get("p")
            if isinstance(t1, int) and isinstance(t2, int):
                in_playoffs.update([t1, t2])
                # Only games on the path to the title get playoff weight;
                # 3rd and 5th place games count like regular games
                if place in (None, 1):
                    playoff_round[frozenset((t1, t2))] = g.get("r") or 1
            if place == 1 and g.get("w") and g.get("l"):
                title_game = g
            if place == 3 and g.get("w"):
                third_game = g
            if place == 3 and isinstance(t1, int) and isinstance(t2, int):
                third_pairs.add(frozenset((t1, t2)))
        if title_game:
            champions.append({
                "season": yr,
                "champion": roster_owner.get(title_game["w"]),
                "runner_up": roster_owner.get(title_game["l"]),
                "third": roster_owner.get(third_game["w"]) if third_game else None,
            })
        playoff_owners = set()
        for rid in in_playoffs:
            if rid in roster_owner:
                owner(roster_owner[rid])["playoffs"] += 1
                playoff_owners.add(roster_owner[rid])
        season_playoffs[yr] = playoff_owners

        # Only finished weeks count
        last_week = MAX_WEEKS
        if str(yr) == str(state.get("season")) and league.get("status") != "complete":
            last_week = max(0, int(state.get("week") or 1) - 1)

        for week in range(1, last_week + 1):
            try:
                rows = get(f"{API}/league/{lid}/matchups/{week}") or []
            except Exception:
                continue
            games = {}
            for m in rows:
                if m.get("matchup_id") is not None:
                    games.setdefault(m["matchup_id"], []).append(m)
            # Starters' points count toward franchise and league leaders
            for m in rows:
                uid = roster_owner.get(m.get("roster_id"))
                starters = m.get("starters") or []
                spts = m.get("starters_points") or []
                if not uid or m.get("matchup_id") is None or not float(m.get("points") or 0):
                    continue
                for pid, pts in zip(starters, spts):
                    if not pid or pid == "0" or pts is None:
                        continue
                    fp = franchise_pts.setdefault(uid, {}).setdefault(pid, {"points": 0.0, "games": 0, "seasons": set()})
                    lp = league_pts.setdefault(pid, {"points": 0.0, "games": 0, "seasons": set(), "owners": set()})
                    for rec in (fp, lp):
                        rec["points"] += float(pts)
                        rec["games"] += 1
                        rec["seasons"].add(yr)
                    lp["owners"].add(uid)

            for teams in games.values():
                if len(teams) != 2:
                    continue
                a, b = teams
                ua, ub = roster_owner.get(a["roster_id"]), roster_owner.get(b["roster_id"])
                pa_, pb_ = points(a.get("points")), points(b.get("points"))
                if not ua or not ub or (pa_ == 0 and pb_ == 0):
                    continue
                playoff = week >= playoff_start
                rnd = playoff_round.get(frozenset((a["roster_id"], b["roster_id"]))) if playoff else None
                weight = 1 + rnd if rnd else 1  # round 1 = 2, round 2 = 3, title game = 4
                result = 1 if pa_ > pb_ else (-1 if pa_ < pb_ else 0)

                games_log.append({"season": yr, "week": week, "a": ua, "b": ub, "pa": pa_, "pb": pb_,
                                  "playoff": bool(rnd), "postseason": playoff, "round": rnd})

                # Playoff record: round 1, round 2, the title game, and the 3rd place game
                counts_for_playoff_record = bool(rnd) or (playoff and frozenset((a["roster_id"], b["roster_id"])) in third_pairs)
                for me, them, mine, theirs, res in ((ua, ub, pa_, pb_, result), (ub, ua, pb_, pa_, -result)):
                    o = owner(me)
                    if counts_for_playoff_record:
                        o["pw" if res > 0 else "pl"] += 1 if res != 0 else 0
                    elif not playoff:
                        o["w" if res > 0 else ("l" if res < 0 else "t")] += 1
                        o["pf"] += mine
                        o["pa"] += theirs

                key = tuple(sorted((ua, ub)))
                h = pair.setdefault(key, {"games": 0, "wins": {key[0]: 0, key[1]: 0}, "ties": 0,
                                          "playoff_meetings": 0, "wgames": 0.0, "wwins": {key[0]: 0.0, key[1]: 0.0}})
                h["games"] += 1
                h["wgames"] += weight
                if rnd:
                    h["playoff_meetings"] += 1
                if result == 0:
                    h["ties"] += 1
                    h["wwins"][ua] += weight / 2
                    h["wwins"][ub] += weight / 2
                else:
                    winner = ua if result > 0 else ub
                    h["wins"][winner] += 1
                    h["wwins"][winner] += weight

        # Drafts
        try:
            league_drafts = get(f"{API}/league/{lid}/drafts") or []
        except Exception:
            league_drafts = []
        for d in league_drafts:
            try:
                picks = get(f"{API}/draft/{d['draft_id']}/picks") or []
            except Exception:
                continue
            rounds = (d.get("settings") or {}).get("rounds") or 0
            kind = "Startup" if rounds > 8 else "Rookie"
            firsts = []
            for p in picks:
                if p.get("pick_no") == 1 and p.get("picked_by"):
                    meta = p.get("metadata") or {}
                    owner(p["picked_by"])["first_overall"].append({
                        "season": int(d.get("season") or yr), "type": kind,
                        "player": (meta.get("first_name", "") + " " + meta.get("last_name", "")).strip(),
                    })
            for p in sorted(picks, key=lambda x: x.get("pick_no") or 0):
                if p.get("round") != 1:
                    continue
                meta = p.get("metadata") or {}
                info = player_info.get(str(p.get("player_id")), {})
                firsts.append({
                    "pick": p.get("pick_no"),
                    "owner": p.get("picked_by"),
                    "player": (meta.get("first_name", "") + " " + meta.get("last_name", "")).strip() or info.get("name"),
                    "pos": meta.get("position") or info.get("pos"),
                    "rank": info.get("rank"),
                    "pos_rank": info.get("pos_rank"),
                })
            if firsts:
                drafts.append({"season": int(d.get("season") or yr), "type": kind, "picks": firsts})

    # ---------- Rivalries ----------
    rows = []
    for (x, y), h in pair.items():
        wg = h["wgames"]
        for me, them in ((x, y), (y, x)):
            ww, wl = h["wwins"][me], h["wwins"][them]
            balance = 1 - abs(ww - wl) / wg if wg else 0
            score = wg * (0.5 + 0.5 * balance)
            rows.append({
                "owner": me, "opponent": them, "games": h["games"],
                "wins": h["wins"][me], "losses": h["wins"][them], "ties": h["ties"],
                "playoff_meetings": h["playoff_meetings"], "weighted_games": round(wg, 2),
                "weighted_wins": round(ww, 2), "weighted_losses": round(wl, 2),
                "balance": round(balance, 3), "score": round(score, 2),
            })
    rivals = {}
    for uid in owners:
        mine = sorted([r for r in rows if r["owner"] == uid], key=lambda r: (-r["score"], -r["games"]))
        for i, r in enumerate(mine, start=1):
            r["rank"] = i
        rivals[uid] = [{"opponent": r["opponent"], "score": r["score"], "wins": r["wins"],
                        "losses": r["losses"], "ties": r["ties"]} for r in mine[:2]]

    # ---------- Records ----------
    records = {}
    reg = [g for g in games_log if not g["postseason"]]
    every = [(g["a"], g["pa"], g) for g in games_log] + [(g["b"], g["pb"], g) for g in games_log]
    if every:
        uid, pts, g = max(every, key=lambda x: x[1])
        records["high_score"] = {"owner": uid, "points": pts, "season": g["season"], "week": g["week"]}
    if games_log:
        g = max(games_log, key=lambda g: abs(g["pa"] - g["pb"]))
        win, lose = (g["a"], g["b"]) if g["pa"] >= g["pb"] else (g["b"], g["a"])
        records["blowout"] = {"winner": win, "loser": lose, "margin": round(abs(g["pa"] - g["pb"]), 2),
                              "season": g["season"], "week": g["week"]}
    streak_best, streaks = None, {}
    for g in sorted(reg, key=lambda g: (g["season"], g["week"])):
        for me, mine, theirs in ((g["a"], g["pa"], g["pb"]), (g["b"], g["pb"], g["pa"])):
            streaks[me] = streaks.get(me, 0) + 1 if mine > theirs else 0
            if streaks[me] and (not streak_best or streaks[me] > streak_best["games"]):
                streak_best = {"owner": me, "games": streaks[me], "through": f"{g['season']} Week {g['week']}"}
    if streak_best:
        records["win_streak"] = streak_best
    season_rows = {}
    for g in reg:
        for me, mine, theirs in ((g["a"], g["pa"], g["pb"]), (g["b"], g["pb"], g["pa"])):
            s = season_rows.setdefault((me, g["season"]), {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0})
            s["w" if mine > theirs else ("l" if mine < theirs else "t")] += 1
            s["pf"] += mine
            s["pa"] += theirs
    champ_of = {c["season"]: c for c in champions}
    for (uid, yr), s in sorted(season_rows.items(), key=lambda kv: kv[0][1]):
        c = champ_of.get(yr, {})
        finish = ("Champion" if c.get("champion") == uid else
                  "Runner-up" if c.get("runner_up") == uid else
                  "3rd place" if c.get("third") == uid else
                  "Playoffs" if uid in season_playoffs.get(yr, set()) else "")
        owner(uid)["by_season"].append({"season": yr, "w": s["w"], "l": s["l"], "t": s["t"],
                                        "pf": round(s["pf"], 2), "pa": round(s.get("pa", 0), 2), "finish": finish})
    if season_rows:
        def pct(s):
            n = s["w"] + s["l"] + s["t"]
            return (s["w"] + s["t"] / 2) / n if n else 0
        (uid, yr), s = max(season_rows.items(), key=lambda kv: (pct(kv[1]), kv[1]["pf"]))
        records["best_season"] = {"owner": uid, "season": yr, "record": f"{s['w']}-{s['l']}" + (f"-{s['t']}" if s["t"] else ""),
                                  "pf": round(s["pf"], 2)}

    for uid, o in owners.items():
        o["pf"], o["pa"] = round(o["pf"], 2), round(o["pa"], 2)
    for c in champions:
        if c["champion"] in owners:
            owners[c["champion"]]["titles"] += 1
        if c["runner_up"] in owners:
            owners[c["runner_up"]]["runner_up"] += 1
        if c.get("third") in owners:
            owners[c["third"]]["third"] += 1

    # ---------- Points leaders ----------
    POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

    def player_name(pid):
        info = every_player.get(pid) or player_info.get(pid) or {}
        return info.get("name") or pid, info.get("pos") or ""

    def leaderboard(table, overall_n, pos_n, with_owners=False):
        rows_ = []
        for pid, rec in table.items():
            nm, pos = player_name(pid)
            row = {"player": nm, "pos": pos, "points": round(rec["points"], 2), "games": rec["games"],
                   "seasons": sorted(rec["seasons"])}
            if with_owners:
                row["owners"] = sorted(rec["owners"])
            rows_.append(row)
        rows_.sort(key=lambda r: -r["points"])
        out = {"overall": rows_[:overall_n]}
        for pos in POSITIONS:
            out[pos] = [r for r in rows_ if r["pos"] == pos][:pos_n]
        return out

    franchise_leaders = {uid: leaderboard(tbl, 10, 5) for uid, tbl in franchise_pts.items()}
    league_leaders = leaderboard(league_pts, 25, 10, with_owners=True)

    os.makedirs("data", exist_ok=True)
    with open("data/legacy.json", "w") as f:
        json.dump({
            "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "seasons": sorted(int(l["season"]) for l in seasons),
            "owners": owners,
            "champions": sorted(champions, key=lambda c: -c["season"]),
            "rivals": rivals,
            "rivalries": rows,
            "drafts": sorted(drafts, key=lambda d: (-d["season"], d["type"])),
            "records": records,
            "franchise_leaders": franchise_leaders,
            "league_leaders": league_leaders,
        }, f, indent=1)

    name = lambda uid: owners.get(uid, {}).get("name") or uid
    with open("data/rivalries.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Team", "Opponent", "Rivalry score", "Games", "Record (W-L-T)", "Playoff meetings",
                    "Weighted games", "Weighted wins", "Weighted losses", "Balance",
                    "Team's rival rank", "Opponent's rival rank"])
        rank_of = {(r["owner"], r["opponent"]): r["rank"] for r in rows}
        team = lambda uid: owners.get(uid, {}).get("team") or name(uid)
        unique = [r for r in rows if team(r["owner"]).lower() <= team(r["opponent"]).lower()]
        for r in sorted(unique, key=lambda r: -r["score"]):
            w.writerow([team(r["owner"]), team(r["opponent"]), r["score"], r["games"],
                        f"{r['wins']}-{r['losses']}-{r['ties']}", r["playoff_meetings"], r["weighted_games"],
                        r["weighted_wins"], r["weighted_losses"], r["balance"],
                        r["rank"], rank_of.get((r["opponent"], r["owner"]), "")])

    print(f"Legacy: {len(seasons)} season(s), {len(owners)} owners, {len(games_log)} games, {len(champions)} champion(s)")


if __name__ == "__main__":
    build()
