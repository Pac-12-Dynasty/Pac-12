# Downloads Sleeper's player database once a day and saves only the
# players on Pac 12 Dynasty rosters to data/players.json.
import json
import os
import urllib.request

LEAGUE_ID = "1315706586127171584"
API = "https://api.sleeper.app/v1"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pac12-dynasty-site"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.load(res)


rosters = get(f"{API}/league/{LEAGUE_ID}/rosters")
ids = set()
for r in rosters:
    for key in ("players", "starters", "reserve", "taxi"):
        ids.update(p for p in (r.get(key) or []) if p and p != "0")

all_players = get(f"{API}/players/nfl")

out = {}
for pid in sorted(ids):
    p = all_players.get(pid)
    if not p:
        continue
    name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    out[pid] = {
        "name": name,
        "pos": p.get("position") or "",
        "team": p.get("team") or "",
        "birth_date": p.get("birth_date") or "",
        "age": p.get("age"),
    }

os.makedirs("data", exist_ok=True)
with open("data/players.json", "w") as f:
    json.dump(out, f, indent=1, sort_keys=True)

print(f"Saved {len(out)} players")
