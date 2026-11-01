# Saves every completed trade in league history to data/trades.json, newest first.
# Each side lists the players, draft picks, and FAAB that team received.
import json
import os
import urllib.request
from datetime import datetime, timezone

BASE_LEAGUE_ID = "1315706586127171584"
API = "https://api.sleeper.app/v1"
MAX_ROUND = 18


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
    out, lid = [], latest_id
    while lid and lid != "0" and len(out) < 30:
        league = get(f"{API}/league/{lid}")
        out.append(league)
        lid = league.get("previous_league_id")
    return out


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

    owners = {}   # user_id -> latest team name and owner name
    trades = []

    for league in reversed(seasons):
        lid, yr = league["league_id"], int(league["season"])
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

                sides = {}
                def side(rid):
                    return sides.setdefault(rid, {"owner": roster_owner.get(rid), "players": [], "picks": [], "faab": 0})

                for rid in t.get("roster_ids") or []:
                    side(rid)
                for pid, rid in (t.get("adds") or {}).items():
                    info = every.get(pid) or roster_info.get(pid) or {}
                    now = roster_info.get(pid) or {}
                    side(rid)["players"].append({
                        "id": pid, "name": info.get("name") or pid, "pos": info.get("pos") or "",
                        "rank": now.get("rank"), "pos_rank": now.get("pos_rank"), "value": now.get("value"),
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
                    "week": t.get("leg") or rnd,
                    "date": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat(timespec="minutes") if created else None,
                    "sides": [s for s in sides.values() if s["owner"]],
                })

    trades.sort(key=lambda t: t["date"] or "", reverse=True)
    os.makedirs("data", exist_ok=True)
    with open("data/trades.json", "w") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                   "owners": owners, "trades": trades}, f, indent=1)
    print(f"Saved {len(trades)} trades across {len(seasons)} season(s)")


if __name__ == "__main__":
    main()
