# Saves game logs and career stats for every player on a league roster:
#   data/players/<player_id>.json
# Fantasy points are scored with the league's own Sleeper scoring settings.
import json
import os
import shutil
import urllib.request

BASE_LEAGUE_ID = "1315706586127171584"
API = "https://api.sleeper.app/v1"
CAREER_YEARS = 8   # how many past seasons of history to keep

KEEP = ["gp", "pass_att", "pass_cmp", "pass_yd", "pass_td", "pass_int", "rush_att", "rush_yd", "rush_td",
        "rec_tgt", "rec", "rec_yd", "rec_td", "fum_lost", "fgm", "fga", "xpm",
        "def_td", "sack", "int", "fum_rec", "pts_allow",
        "off_snp", "tm_off_snp"]   # snaps played and team snaps, for snap %


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pac12-dynasty-site"})
    with urllib.request.urlopen(req, timeout=120) as res:
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


def by_player(data):
    """Sleeper stats come back keyed by player ID (or occasionally as a list)."""
    if isinstance(data, dict):
        return data
    out = {}
    for row in data or []:
        if isinstance(row, dict) and row.get("player_id"):
            out[str(row["player_id"])] = row.get("stats") or row
    return out


def main():
    state = get(f"{API}/state/nfl")
    league = get(f"{API}/league/{current_league(BASE_LEAGUE_ID, state)}")
    scoring = league.get("scoring_settings") or {}
    season = int(league["season"])

    def score(stats):
        return round(sum(float(v) * float(scoring.get(k, 0)) for k, v in stats.items()
                         if isinstance(v, (int, float)) and k in scoring), 2)

    def trim(stats):
        return {k: stats[k] for k in KEEP if isinstance(stats.get(k), (int, float)) and stats.get(k)}

    with open("data/players.json") as f:
        roster_info = json.load(f)
    ids = set(roster_info.keys())
    try:
        with open("cache/all_players.json") as f:
            every = json.load(f)
    except Exception:
        every = {}

    def pos_of(pid):
        return (every.get(pid) or roster_info.get(pid) or {}).get("pos") or ("DEF" if pid.isalpha() and len(pid) <= 3 else "")

    SKILL = ("QB", "RB", "WR", "TE")

    def rank_all(table):
        """Scores every player in a stats table and returns pid -> (position rank, overall rank).
        Overall rank covers QB, RB, WR, and TE; kickers and defenses only get a position rank."""
        scored = []
        for pid, stats in table.items():
            if not isinstance(stats, dict):
                continue
            pid = pid[5:] if pid.startswith("TEAM_") else pid
            pos = pos_of(pid)
            if not pos:
                continue
            scored.append((pid, pos, score(stats)))
        scored.sort(key=lambda x: -x[2])
        ranks, pos_place, pos_last, ovr_place, ovr_last = {}, {}, {}, 0, None
        pos_count, ovr_count = {}, 0
        for pid, pos, pts in scored:
            pos_count[pos] = pos_count.get(pos, 0) + 1
            if pos_last.get(pos) != pts:
                pos_place[pos], pos_last[pos] = pos_count[pos], pts
            ovr = None
            if pos in SKILL:
                ovr_count += 1
                if ovr_last != pts:
                    ovr_place, ovr_last = ovr_count, pts
                ovr = ovr_place
            ranks[pid] = (pos + str(pos_place[pos]), ovr)
        return ranks

    # Weeks that are finished this season
    if league.get("status") == "complete" or str(state.get("season")) != str(season):
        last_week = 18
    else:
        last_week = max(0, int(state.get("week") or 1) - 1)

    logs = {pid: [] for pid in ids}
    for week in range(1, last_week + 1):
        try:
            weekly = by_player(get(f"{API}/stats/nfl/regular/{season}/{week}"))
        except Exception as err:
            print(f"Week {week} stats unavailable: {err}")
            continue
        week_ranks = rank_all(weekly)
        for pid in ids:
            stats = weekly.get(pid) or weekly.get("TEAM_" + pid)
            if stats and (stats.get("gp") or any(isinstance(v, (int, float)) and v for v in stats.values())):
                pos_rk, ovr_rk = week_ranks.get(pid, (None, None))
                logs[pid].append({"week": week, "pts": score(stats), "pos_rank": pos_rk, "ovr_rank": ovr_rk,
                                  "stats": trim(stats)})

    career = {pid: [] for pid in ids}
    for yr in range(season - CAREER_YEARS, season + 1):
        try:
            totals = by_player(get(f"{API}/stats/nfl/regular/{yr}"))
        except Exception as err:
            print(f"{yr} season stats unavailable: {err}")
            continue
        season_ranks = rank_all(totals)
        for pid in ids:
            stats = totals.get(pid) or totals.get("TEAM_" + pid)
            if stats and stats.get("gp"):
                pos_rk, ovr_rk = season_ranks.get(pid, (None, None))
                career[pid].append({"season": yr, "gp": stats.get("gp"), "pts": score(stats),
                                    "pos_rank": pos_rk, "ovr_rank": ovr_rk, "stats": trim(stats)})

    shutil.rmtree("data/players", ignore_errors=True)
    os.makedirs("data/players", exist_ok=True)
    for pid in ids:
        with open(f"data/players/{pid}.json", "w") as f:
            json.dump({"id": pid, "season": season, "log": logs[pid],
                       "career": sorted(career[pid], key=lambda c: -c["season"])}, f)

    print(f"Stats saved for {len(ids)} players through week {last_week} of {season}")


if __name__ == "__main__":
    main()
