# Saves every completed trade in league history to data/trades.json, newest first.
# Each side lists the players, draft picks, and FAAB that team received.
# Player ranks use Sleeper stats scored with the league's own settings, the same
# way the game logs do:
#   "Was" = his rank that season through the week before the trade
#           (for offseason trades, his finish the season before)
#   "Now" = his rank this season so far
import json
import os
import urllib.request
from datetime import datetime, timezone

BASE_LEAGUE_ID = "1315706586127171584"
API = "https://api.sleeper.app/v1"
MAX_ROUND = 18
SKILL = ("QB", "RB", "WR", "TE")


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


def all_seasons(latest_id):
    out, lid = [], latest_id
    while lid and lid != "0" and len(out) < 30:
        league = get(f"{API}/league/{lid}")
        out.append(league)
        lid = league.get("previous_league_id")
    return out


def by_player(data):
    if isinstance(data, dict):
        return data
    out = {}
    for row in data or []:
        if isinstance(row, dict) and row.get("player_id"):
            out[str(row["player_id"])] = row.get("stats") or row
    return out


class SleeperRanks:
    """Ranks every NFL player by fantasy points under the league's scoring."""

    def __init__(self, positions):
        self.positions = positions
        self.week_points = {}    # (season, week) -> {pid: points}
        self.ranked = {}         # cache key -> {pid: (pos_rank, ovr_rank)}

    def pos_of(self, pid):
        return self.positions.get(pid) or ("DEF" if pid.isalpha() and len(pid) <= 3 else "")

    @staticmethod
    def score(stats, scoring):
        return sum(float(v) * float(scoring.get(k, 0)) for k, v in stats.items()
                   if isinstance(v, (int, float)) and k in scoring)

    def rank(self, points):
        scored = sorted(((pid, self.pos_of(pid), pts) for pid, pts in points.items() if self.pos_of(pid)),
                        key=lambda x: -x[2])
        out, pos_count, pos_place, pos_last = {}, {}, {}, {}
        ovr_count, ovr_place, ovr_last = 0, 0, None
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
            out[pid] = (pos + str(pos_place[pos]), ovr)
        return out

    def _points_from(self, table, scoring):
        out = {}
        for pid, stats in by_player(table).items():
            if isinstance(stats, dict):
                pid = pid[5:] if pid.startswith("TEAM_") else pid
                out[pid] = self.score(stats, scoring)
        return out

    def season_total(self, season, scoring):
        key = ("season", season)
        if key not in self.ranked:
            try:
                self.ranked[key] = self.rank(self._points_from(get(f"{API}/stats/nfl/regular/{season}"), scoring))
            except Exception as err:
                print(f"{season} season stats unavailable: {err}")
                self.ranked[key] = {}
        return self.ranked[key]

    def through_week(self, season, last_week, scoring):
        """Ranks on points from week 1 through last_week of a season."""
        key = ("through", season, last_week)
        if key not in self.ranked:
            totals = {}
            for wk in range(1, last_week + 1):
                if (season, wk) not in self.week_points:
                    try:
                        self.week_points[(season, wk)] = self._points_from(
                            get(f"{API}/stats/nfl/regular/{season}/{wk}"), scoring)
                    except Exception as err:
                        print(f"{season} week {wk} stats unavailable: {err}")
                        self.week_points[(season, wk)] = {}
                for pid, pts in self.week_points[(season, wk)].items():
                    totals[pid] = totals.get(pid, 0) + pts
            self.ranked[key] = self.rank(totals)
        return self.ranked[key]


def main():
    state = get(f"{API}/state/nfl")
    seasons = all_seasons(current_league(BASE_LEAGUE_ID, state))

    try:
        with open("cache/all_players.json") as f:
            every = json.load(f)
    except Exception:
        every = {}
    try:
        with open("data/players.json") as f:
            roster_info = json.load(f)
    except Exception:
        roster_info = {}
    positions = {pid: (p.get("pos") or "") for pid, p in every.items()}
    positions.update({pid: (p.get("pos") or "") for pid, p in roster_info.items() if p.get("pos")})
    ranks = SleeperRanks(positions)

    # "Was" ranks never change, so reuse any already saved
    known = {}
    try:
        with open("data/trades.json") as f:
            for t in json.load(f).get("trades", []):
                for sd in t.get("sides", []):
                    for p in sd.get("players", []):
                        if p.get("was_basis"):
                            known[(t["id"], p["id"])] = (p.get("was_pos_rank"), p.get("was_rank"), p["was_basis"])
    except Exception:
        pass

    # "Now" = this season so far, or last season's finish before any games are played
    latest = seasons[0]
    now_scoring = latest.get("scoring_settings") or {}
    now_season = int(latest["season"])
    games_played = str(state.get("season")) == str(now_season) and int(state.get("week") or 0) > 1
    if latest.get("status") == "complete" or games_played:
        now_ranks, now_basis = ranks.season_total(now_season, now_scoring), f"{now_season} so far"
    else:
        now_ranks, now_basis = ranks.season_total(now_season - 1, now_scoring), f"{now_season - 1} finish"

    owners = {}
    trades = []

    for league in reversed(seasons):
        lid, yr = league["league_id"], int(league["season"])
        scoring = league.get("scoring_settings") or now_scoring
        users = {u["user_id"]: u for u in get(f"{API}/league/{lid}/users")}
        roster_owner = {r["roster_id"]: r.get("owner_id") for r in get(f"{API}/league/{lid}/rosters")}
        for uid in roster_owner.values():
            if not uid:
                continue
            u = users.get(uid, {})
            owners[uid] = {"name": u.get("display_name") or "Unknown",
                           "team": (u.get("metadata") or {}).get("team_name") or u.get("display_name") or "Unknown"}

        seen = set()
        for rnd in range(0, MAX_ROUND + 1):
            try:
                rows = get(f"{API}/league/{lid}/transactions/{rnd}") or []
            except Exception:
                continue
            for t in rows:
                if t.get("type") != "trade" or t.get("status") != "complete":
                    continue
                if t.get("transaction_id") in seen:
                    continue
                seen.add(t.get("transaction_id"))
                week = t.get("leg") or rnd

                # Ranks at the time of the trade
                def was_for(pid):
                    saved = known.get((t.get("transaction_id"), pid))
                    if saved:
                        return saved
                    if week and week > 1:
                        r = ranks.through_week(yr, week - 1, scoring).get(pid, (None, None))
                        return r[0], r[1], f"{yr} Wk 1-{week - 1}"
                    r = ranks.season_total(yr - 1, scoring).get(pid, (None, None))
                    return r[0], r[1], f"{yr - 1} finish"

                sides = {}
                def side(rid):
                    return sides.setdefault(rid, {"owner": roster_owner.get(rid), "players": [], "picks": [], "faab": 0})

                for rid in t.get("roster_ids") or []:
                    side(rid)
                for pid, rid in (t.get("adds") or {}).items():
                    info = every.get(pid) or roster_info.get(pid) or {}
                    was_pos, was_ovr, basis = was_for(pid)
                    now_pos, now_ovr = now_ranks.get(pid, (None, None))
                    side(rid)["players"].append({
                        "id": pid, "name": info.get("name") or pid, "pos": info.get("pos") or "",
                        "was_pos_rank": was_pos, "was_rank": was_ovr, "was_basis": basis,
                        "now_pos_rank": now_pos, "now_rank": now_ovr, "now_basis": now_basis,
                    })
                for pk in t.get("draft_picks") or []:
                    side(pk["owner_id"])["picks"].append({
                        "season": int(pk.get("season")), "round": pk.get("round"),
                        "original_owner": roster_owner.get(pk.get("roster_id")),
                    })
                for w in t.get("waiver_budget") or []:
                    side(w["receiver"])["faab"] += w.get("amount") or 0

                created = t.get("status_updated") or t.get("created") or 0
                trades.append({
                    "id": t.get("transaction_id"),
                    "season": yr,
                    "week": week,
                    "date": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat(timespec="minutes") if created else None,
                    "sides": [s for s in sides.values() if s["owner"]],
                })

    trades.sort(key=lambda t: t["date"] or "", reverse=True)
    os.makedirs("data", exist_ok=True)
    with open("data/trades.json", "w") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                   "now_basis": now_basis, "owners": owners, "trades": trades}, f, indent=1)
    print(f"Saved {len(trades)} trades across {len(seasons)} season(s)")


if __name__ == "__main__":
    main()
