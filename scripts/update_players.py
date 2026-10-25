# Runs once a day. Saves every player on Pac 12 Dynasty rosters to
# data/players.json with info from Sleeper and dynasty ranks from DynastyProcess.
import csv
import io
import json
import os
import urllib.request

LEAGUE_ID = "1315706586127171584"
API = "https://api.sleeper.app/v1"
DP = "https://raw.githubusercontent.com/dynastyprocess/data/master/files"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pac12-dynasty-site"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return res.read().decode("utf-8")


def get(url):
    return json.loads(fetch(url))


def get_csv(url):
    return list(csv.DictReader(io.StringIO(fetch(url))))


# Dynasty ranks: values from DynastyProcess (FantasyPros dynasty expert consensus),
# matched to Sleeper IDs, ranked overall and by position (1QB values).
ranks = {}
try:
    values = get_csv(f"{DP}/values-players.csv")
    id_map = {}
    for r in get_csv(f"{DP}/db_playerids.csv"):
        if r.get("fantasypros_id") and r.get("sleeper_id") not in (None, "", "NA"):
            id_map[r["fantasypros_id"]] = r["sleeper_id"]
    values.sort(key=lambda r: -float(r.get("value_1qb") or 0))
    pos_count = {}
    for overall, r in enumerate(values, start=1):
        pos_count[r["pos"]] = pos_count.get(r["pos"], 0) + 1
        sid = id_map.get(r.get("fp_id"))
        if sid:
            ranks[sid] = {
                "rank": overall,
                "pos_rank": f"{r['pos']}{pos_count[r['pos']]}",
                "value": int(float(r.get("value_1qb") or 0)),
            }
except Exception as err:
    print(f"Dynasty ranks unavailable: {err}")

# Sleeper gives the league a new ID each season; follow renewals to the newest one
def current_league(base_id):
    state = get(f"{API}/state/nfl")
    target = int(state.get("league_season") or state.get("season"))
    league = get(f"{API}/league/{base_id}")
    season = int(league["season"])
    users = sorted(get(f"{API}/league/{base_id}/users"), key=lambda u: not u.get("is_owner"))[:4]
    league_id = base_id
    while season < target:
        nxt = season + 1
        found = None
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


try:
    LEAGUE_ID = current_league(LEAGUE_ID)
except Exception as err:
    print(f"Couldn't check for a newer league, using the original: {err}")
print(f"Using league {LEAGUE_ID}")

rosters = get(f"{API}/league/{LEAGUE_ID}/rosters")
ids = set()
for r in rosters:
    for key in ("players", "starters", "reserve", "taxi"):
        ids.update(p for p in (r.get(key) or []) if p and p != "0")

all_players = get(f"{API}/players/nfl")

# Name and position for every player, so league history can name players who left the league.
# Saved outside data/ so it isn't committed; the legacy script reads it in the same run.
os.makedirs("cache", exist_ok=True)
with open("cache/all_players.json", "w") as f:
    json.dump({pid: {"name": p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                     "pos": p.get("position") or ""} for pid, p in all_players.items()}, f)

out = {}
for pid in sorted(ids):
    p = all_players.get(pid)
    if not p:
        continue
    name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    rk = ranks.get(pid, {})
    out[pid] = {
        "name": name,
        "pos": p.get("position") or "",
        "team": p.get("team") or "",
        "birth_date": p.get("birth_date") or "",
        "age": p.get("age"),
        "rank": rk.get("rank"),
        "pos_rank": rk.get("pos_rank", ""),
        "value": rk.get("value"),
        "injury": p.get("injury_status") or "",
        "injury_part": p.get("injury_body_part") or "",
    }

os.makedirs("data", exist_ok=True)
with open("data/players.json", "w") as f:
    json.dump(out, f, indent=1, sort_keys=True)

print(f"Saved {len(out)} players, {sum(1 for v in out.values() if v['rank'])} with dynasty ranks")
