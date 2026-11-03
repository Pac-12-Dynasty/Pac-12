# Saves every completed trade in league history to data/trades.json, newest first.
# Each side lists the players, draft picks, and FAAB that team received.
# Player ranks use Sleeper stats scored with the league's own settings, the same
# way the game logs do:
#   "Was" = his rank that season through the week before the trade
#           (for offseason trades, his finish the season before)
#   "Now" = his rank this season so far
import csv
import io
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

import valuation

BASE_LEAGUE_ID = "1315706586127171584"
API = "https://api.sleeper.app/v1"
MAX_ROUND = 18
SKILL = ("QB", "RB", "WR", "TE")


def fetch(url, headers=None):
    h = {"User-Agent": "pac12-dynasty-site"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=120) as res:
        return res.read().decode("utf-8")


def get(url):
    return json.loads(fetch(url))


# ---------- Market value at the time of a trade ----------
# DynastyProcess updates its value files weekly on GitHub, and GitHub keeps every
# past version, so we can look up what any player or pick was worth on a past date.
DP_REPO = "dynastyprocess/data"


class PastValues:
    def __init__(self):
        self.commits = None
        self.snapshots = {}
        self.id_map = {}
        token = os.environ.get("GITHUB_TOKEN")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            text = fetch(f"https://raw.githubusercontent.com/{DP_REPO}/master/files/db_playerids.csv")
            self.id_map = {r["fantasypros_id"]: r["sleeper_id"] for r in csv.DictReader(io.StringIO(text))
                           if r.get("fantasypros_id") and r.get("sleeper_id") not in (None, "", "NA")}
        except Exception as err:
            print(f"Player ID map unavailable: {err}")

    def _load_commits(self):
        out, page = [], 1
        while page <= 10:
            rows = json.loads(fetch(f"https://api.github.com/repos/{DP_REPO}/commits?path=files/values-players.csv"
                                    f"&since=2022-06-01T00:00:00Z&per_page=100&page={page}", self.headers))
            if not rows:
                break
            out += [(r["commit"]["committer"]["date"], r["sha"]) for r in rows]
            page += 1
        self.commits = sorted(out)

    def _snapshot(self, sha):
        if sha in self.snapshots:
            return self.snapshots[sha]
        players, curve = {}, []
        for r in csv.DictReader(io.StringIO(fetch(f"https://raw.githubusercontent.com/{DP_REPO}/{sha}/files/values-players.csv"))):
            try:
                v = float(r.get("value_1qb") or 0)
            except ValueError:
                continue
            sid = self.id_map.get(r.get("fp_id"))
            if sid:
                players[sid] = v
            try:
                curve.append((float(r["ecr_1qb"]), v))
            except (KeyError, TypeError, ValueError):
                pass
        curve.sort()

        def value_at(ecr):
            if not curve:
                return 0
            for (e1, v1), (e2, v2) in zip(curve, curve[1:]):
                if e1 <= ecr <= e2:
                    return v1 + (v2 - v1) * ((ecr - e1) / (e2 - e1) if e2 > e1 else 0)
            return curve[0][1] if ecr < curve[0][0] else curve[-1][1]

        picks = {}   # (season or None, round) -> list of values
        try:
            text = fetch(f"https://raw.githubusercontent.com/{DP_REPO}/{sha}/files/values-picks.csv")
            for r in csv.DictReader(io.StringIO(text)):
                name = r.get("player", "")
                yr = re.match(r"(\d{4})", name)
                rd = re.search(r"(\d)\.\d\d|(\d)(?:st|nd|rd|th)", name)
                if not yr or not rd:
                    continue
                try:
                    v = value_at(float(r["ecr_1qb"]))
                except (KeyError, TypeError, ValueError):
                    continue
                rnd = int(rd.group(1) or rd.group(2))
                picks.setdefault((int(yr.group(1)), rnd), []).append(v)
                picks.setdefault((None, rnd), []).append(v)
                slot = re.search(r"\d\.(\d\d)", name)
                if slot:                                   # exact slot in the next draft
                    picks[("slot", rnd, int(slot.group(1)))] = [v]
                tier = re.search(r"(Early|Mid|Late)", name)
                if tier:
                    picks[("tier", int(yr.group(1)), tier.group(1), rnd)] = [v]
        except Exception:
            pass
        self.snapshots[sha] = (players, picks)
        return self.snapshots[sha]

    def _at(self, date_iso):
        if self.commits is None:
            try:
                self._load_commits()
            except Exception as err:
                print(f"Value history unavailable: {err}")
                self.commits = []
        before = [sha for d, sha in self.commits if d <= date_iso]
        return self._snapshot(before[-1]) if before else None

    def player(self, date_iso, pid):
        try:
            snap = self._at(date_iso)
            return round(snap[0].get(pid)) if snap and snap[0].get(pid) else None
        except Exception:
            return None

    def players_at(self, date_iso):
        try:
            snap = self._at(date_iso)
            return snap[0] if snap else {}
        except Exception:
            return {}

    def pick(self, date_iso, season, rnd, standing=None, teams=12, next_draft=None):
        """A pick's value on a past date. For the next draft, uses the original team's standing then,
        including lottery odds; later drafts use that class's own early/mid/late or round value."""
        try:
            snap = self._at(date_iso)
            if not snap:
                return None
            vals = snap[1]
            if standing and season == next_draft and vals.get(("slot", rnd, 1)):
                odds = valuation.lottery_odds()
                if standing in odds:
                    return round(sum(c * (vals.get(("slot", rnd, k + 1)) or [0])[0] for k, c in enumerate(odds[standing])))
                slot = teams - standing + 1
                if vals.get(("slot", rnd, slot)):
                    return round(vals[("slot", rnd, slot)][0])
            if standing:
                tier = "Early" if standing > teams * 2 / 3 else ("Late" if standing <= teams / 3 else "Mid")
                if vals.get(("tier", season, tier, rnd)):
                    return round(vals[("tier", season, tier, rnd)][0])
            v = vals.get((season, rnd)) or vals.get((None, rnd))
            return round(sum(v) / len(v)) if v else None
        except Exception:
            return None


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


GRADE_VERSION = 4


class TradeContext:
    """Looks up what each team looked like when a trade happened: rosters, standings, and draft timing."""

    def __init__(self, seasons):
        self.by_season = {int(l["season"]): l for l in seasons}
        self.cache = {}

    def _get(self, key, url, default):
        if key not in self.cache:
            try:
                self.cache[key] = get(url)
            except Exception:
                self.cache[key] = default
        return self.cache[key]

    def matchups(self, lid, week):
        return self._get(("m", lid, week), f"{API}/league/{lid}/matchups/{week}", []) or []

    def final_standings(self, yr):
        """roster_id -> standing (1 = best) at the end of a season, from Sleeper's records."""
        league = self.by_season.get(yr)
        if not league:
            return {}
        rosters = self._get(("r", league["league_id"]), f"{API}/league/{league['league_id']}/rosters", []) or []
        def key(r):
            st = r.get("settings") or {}
            g = (st.get("wins") or 0) + (st.get("losses") or 0) + (st.get("ties") or 0)
            pct = ((st.get("wins") or 0) + (st.get("ties") or 0) / 2) / g if g else 0
            return (-pct, -((st.get("fpts") or 0) + (st.get("fpts_decimal") or 0) / 100))
        return {r["roster_id"]: i + 1 for i, r in enumerate(sorted(rosters, key=key))}

    def standings_through(self, lid, last_week):
        """roster_id -> (standing, win pct, points for) through a given week."""
        rec = {}
        for wk in range(1, last_week + 1):
            games = {}
            for m in self.matchups(lid, wk):
                if m.get("matchup_id") is not None:
                    games.setdefault(m["matchup_id"], []).append(m)
            for pair in games.values():
                if len(pair) != 2:
                    continue
                for me, them in (pair, pair[::-1]):
                    r = rec.setdefault(me["roster_id"], [0, 0, 0.0])
                    a, b = me.get("points") or 0, them.get("points") or 0
                    if a > b: r[0] += 1
                    elif a < b: r[1] += 1
                    r[2] += a
        order = sorted(rec, key=lambda k: (-(rec[k][0] / max(rec[k][0] + rec[k][1], 1)), -rec[k][2]))
        # (standing, win pct, points for, wins, games played)
        return {rid: (i + 1, rec[rid][0] / max(rec[rid][0] + rec[rid][1], 1), rec[rid][2], rec[rid][0], rec[rid][0] + rec[rid][1])
                for i, rid in enumerate(order)}

    def draft_start(self, lid):
        drafts = self._get(("d", lid), f"{API}/league/{lid}/drafts", []) or []
        times = [d.get("start_time") for d in drafts if d.get("start_time")]
        return min(times) if times else None


def grade_trade(t, league, yr, week, created, roster_owner, ctx, past, ranks, every, scoring):
    """Grades a trade for each team by how much it changed that team's lineup, depth, and future."""
    lid = league["league_id"]
    slots = [p for p in (league.get("roster_positions") or []) if p not in ("BN", "IR", "TAXI")]
    date_iso = datetime.fromtimestamp(created / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    values = past.players_at(date_iso)
    if not values:
        return None

    # Draft timing: before this season's rookie draft, the next draft is this season's
    start = ctx.draft_start(lid)
    next_draft = yr if (start and created < start) else yr + 1
    # Standings that decide pick order and each team's window at the time
    if next_draft == yr or not week or week <= 1:
        pick_order = ctx.final_standings(yr - 1) if next_draft == yr else {}
        live = ctx.standings_through(lid, max(0, (week or 1) - 1))
    else:
        live = ctx.standings_through(lid, week - 1)
        pick_order = {rid: v[0] for rid, v in live.items()}
    teams_n = max(len(roster_owner), 1)

    # Rosters right before the trade
    roster_week = max(1, (week or 1) - 1)
    rosters = {m["roster_id"]: set(m.get("players") or []) for m in ctx.matchups(lid, roster_week)}
    if not rosters:
        rosters = {m["roster_id"]: set(m.get("players") or []) for m in ctx.matchups(lid, 1)}
    adds, drops = t.get("adds") or {}, t.get("drops") or {}
    for pid, rid in drops.items():
        rosters.setdefault(rid, set()).add(pid)
    for pid, rid in adds.items():
        rosters.setdefault(rid, set()).discard(pid)

    # Production ranks at the time
    if week and week > 1:
        rank_table = ranks.through_week(yr, week - 1, scoring)
    else:
        rank_table = ranks.season_total(yr - 1, scoring)

    when = datetime.fromtimestamp(created / 1000)

    def asset(pid):
        info = every.get(pid) or {}
        age = None
        try:
            age = (when - datetime.strptime(info.get("birth_date"), "%Y-%m-%d")).days / 365.25
        except Exception:
            pass
        v = values.get(pid) or 0
        now, fut = valuation.split(v, info.get("pos") or "", age, (rank_table.get(pid) or (None,))[0])
        return {"id": pid, "pos": info.get("pos") or "", "now": now, "fut": fut, "market": v, "name": info.get("name") or pid}

    playoff_teams = (league.get("settings") or {}).get("playoff_teams") or 6
    last_final = ctx.final_standings(yr - 1)

    def window(rid):
        """Where the team stood in the playoff race when the trade happened."""
        me = live.get(rid)
        if me and me[4] >= 3:
            cutoff = sorted(live.values(), key=lambda v: v[0])[min(playoff_teams, len(live)) - 1]
            return valuation.window_in_season(me[0], cutoff[3] - me[3], playoff_teams)
        if rid in last_final:
            return valuation.window_from_final(last_final[rid], playoff_teams)
        return "Middle"

    pick_assets = {}
    pick_values = {}
    for pk in t.get("draft_picks") or []:
        season = int(pk.get("season"))
        # Valued by the ORIGINAL owner's standing (roster_id is the team the pick started with)
        v = past.pick(date_iso, season, pk.get("round"), pick_order.get(pk.get("roster_id")), teams_n, next_draft) or 0
        pick_values[f"{season}-{pk.get('round')}-{roster_owner.get(pk.get('roster_id'))}"] = round(v) if v else None
        pick_assets.setdefault(pk["previous_owner_id"], []).append(
            ({"id": f"{season}-{pk.get('round')}-{pk.get('roster_id')}", "now": 0, "fut": v, "market": v}, pk["owner_id"]))

    results = {}
    for rid in t.get("roster_ids") or []:
        roster = [asset(pid) for pid in rosters.get(rid, set())]
        gives = [asset(pid) for pid, to in adds.items() if drops.get(pid) == rid]
        gets = [asset(pid) for pid, to in adds.items() if to == rid]
        gives += [a for a, to in pick_assets.get(rid, [])]
        gets += [a for frm, lst in pick_assets.items() for a, to in lst if to == rid]
        if not gives and not gets:
            continue
        w = window(rid)
        res = valuation.evaluate_side(roster, [a for a in gives if not a.get("pos")], gives, gets, slots, w)
        names = {a["id"]: a.get("name") for a in gets}
        res["impact"] = [{"name": names.get(i["id"]), "starts": i["starts"], "slot": i["slot"]} for i in res["impact"]]
        res["window"] = w
        res["unvalued"] = [a.get("name") for a in gives + gets if a.get("pos") and not a["market"]]
        results[roster_owner.get(rid)] = res
    if len(results) == 2:
        (ua, ra), (ub, rb) = results.items()
        ra["grade"], rb["grade"] = valuation.pair_grades(ra["net"], rb["net"])
        ra["gap"], rb["gap"] = ra["net"] - rb["net"], rb["net"] - ra["net"]
    return {"version": GRADE_VERSION, "teams": results, "pick_values": pick_values}


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
    known_val = {}
    known_grade = {}
    try:
        with open("data/trades.json") as f:
            for t in json.load(f).get("trades", []):
                if (t.get("grades") or {}).get("version") == GRADE_VERSION:
                    known_grade[t["id"]] = t["grades"]
                for sd in t.get("sides", []):
                    for p in sd.get("players", []):
                        if p.get("was_basis"):
                            known[(t["id"], p["id"])] = (p.get("was_pos_rank"), p.get("was_rank"), p["was_basis"])
                        if p.get("was_value") is not None:
                            known_val[(t["id"], p["id"])] = p["was_value"]
                    for pk in sd.get("picks", []):
                        if pk.get("was_value") is not None and pk.get("value_basis") == "original_owner":
                            known_val[(t["id"], f"{pk['season']}-{pk['round']}-{pk.get('original_owner')}")] = pk["was_value"]
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
    moves = []      # every other transaction: waivers, free agents, commissioner moves
    past = PastValues()
    ctx = TradeContext(seasons)

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
                if t.get("status") != "complete":
                    continue
                if t.get("type") != "trade":
                    if t.get("transaction_id") in seen:
                        continue
                    seen.add(t.get("transaction_id"))
                    created = t.get("status_updated") or t.get("created") or 0
                    def named(pid):
                        info = every.get(pid) or roster_info.get(pid) or {}
                        return {"id": pid, "name": info.get("name") or pid, "pos": info.get("pos") or ""}
                    rid = (t.get("roster_ids") or [None])[0]
                    moves.append({
                        "id": t.get("transaction_id"),
                        "type": t.get("type"),            # waiver, free_agent, or commissioner
                        "season": yr,
                        "week": t.get("leg") or rnd,
                        "date": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat(timespec="minutes") if created else None,
                        "owner": roster_owner.get(rid),
                        "adds": [named(pid) for pid in (t.get("adds") or {})],
                        "drops": [named(pid) for pid in (t.get("drops") or {})],
                        "bid": (t.get("settings") or {}).get("waiver_bid"),
                    })
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

                created = t.get("status_updated") or t.get("created") or 0
                date_iso = datetime.fromtimestamp(created / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if created else ""
                tid = t.get("transaction_id")

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
                        "was_value": known_val[(tid, pid)] if (tid, pid) in known_val else (past.player(date_iso, pid) if date_iso else None),
                    })
                for pk in t.get("draft_picks") or []:
                    orig = roster_owner.get(pk.get("roster_id"))
                    key = (tid, f"{int(pk.get('season'))}-{pk.get('round')}-{orig}")
                    side(pk["owner_id"])["picks"].append({
                        "season": int(pk.get("season")), "round": pk.get("round"), "original_owner": orig,
                        "was_value": known_val[key] if key in known_val else (past.pick(date_iso, int(pk.get("season")), pk.get("round")) if date_iso else None),
                    })
                for w in t.get("waiver_budget") or []:
                    side(w["receiver"])["faab"] += w.get("amount") or 0

                grades = known_grade.get(tid)
                if grades is None and created:
                    try:
                        grades = grade_trade(t, league, yr, week, created, roster_owner, ctx, past, ranks, every, scoring)
                    except Exception as err:
                        print(f"Couldn't grade trade {tid}: {err}")
                        grades = None
                pv = (grades or {}).get("pick_values") or {}
                for sd in sides.values():
                    for pk in sd["picks"]:
                        k = f"{pk['season']}-{pk['round']}-{pk['original_owner']}"
                        if k in pv:
                            pk["was_value"], pk["value_basis"] = pv[k], "original_owner"
                trades.append({
                    "grades": grades,
                    "id": t.get("transaction_id"),
                    "season": yr,
                    "week": week,
                    "date": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat(timespec="minutes") if created else None,
                    "sides": [s for s in sides.values() if s["owner"]],
                })

    trades.sort(key=lambda t: t["date"] or "", reverse=True)

    # Biggest dynasty value risers and fallers among rostered players, last 4 weeks
    movers = {"days": 28, "risers": [], "fallers": []}
    try:
        then = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=28)).strftime("%Y-%m-%dT%H:%M:%SZ")
        changes = []
        for pid, info in roster_info.items():
            now_v = info.get("value")
            old_v = past.player(then, pid)
            if now_v and old_v:
                changes.append({"id": pid, "name": info.get("name") or pid, "pos": info.get("pos") or "",
                                "value": now_v, "change": now_v - old_v})
        changes.sort(key=lambda c: -c["change"])
        movers["risers"] = [c for c in changes if c["change"] > 0][:8]
        movers["fallers"] = sorted([c for c in changes if c["change"] < 0], key=lambda c: c["change"])[:8]
    except Exception as err:
        print(f"Value movers unavailable: {err}")
    os.makedirs("data", exist_ok=True)
    with open("data/trades.json", "w") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                   "now_basis": now_basis, "owners": owners, "trades": trades, "movers": movers}, f, indent=1)
    moves.sort(key=lambda m: m["date"] or "", reverse=True)
    with open("data/transactions.json", "w") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                   "owners": owners, "moves": moves}, f)
    print(f"Saved {len(trades)} trades and {len(moves)} other transactions across {len(seasons)} season(s)")


if __name__ == "__main__":
    main()
