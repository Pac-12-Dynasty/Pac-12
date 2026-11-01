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

    def pick(self, date_iso, season, rnd):
        try:
            snap = self._at(date_iso)
            if not snap:
                return None
            vals = snap[1].get((season, rnd)) or snap[1].get((None, rnd))
            return round(sum(vals) / len(vals)) if vals else None
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
    try:
        with open("data/trades.json") as f:
            for t in json.load(f).get("trades", []):
                for sd in t.get("sides", []):
                    for p in sd.get("players", []):
                        if p.get("was_basis"):
                            known[(t["id"], p["id"])] = (p.get("was_pos_rank"), p.get("was_rank"), p["was_basis"])
                        if p.get("was_value") is not None:
                            known_val[(t["id"], p["id"])] = p["was_value"]
                    for pk in sd.get("picks", []):
                        if pk.get("was_value") is not None:
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
    past = PastValues()

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
