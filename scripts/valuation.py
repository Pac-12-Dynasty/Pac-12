# Shared trade valuation used by the daily scripts (the Trade Analyzer page mirrors this in JavaScript).
# A trade is judged by how much it improves each team: its best starting lineup now,
# its depth, and its long-term value, weighted by whether the team is contending or rebuilding.
from itertools import permutations

SETTINGS = {
    # Boost or cut to win-now value from this season's league-scored finish at his position
    "production": [(5, 0.10), (12, 0.05), (24, 0.0), (36, -0.05), (999, -0.10)],
    "injury": {"Out": -0.08, "IR": -0.08, "PUP": -0.08, "Sus": -0.05, "Doubtful": -0.04},
    # Value shifts from long term toward win now between "peak" and "cliff" ages
    "ages": {"QB": (26, 34), "RB": (23, 28), "WR": (24, 30), "TE": (25, 31)},
    # How each team window weighs (win-now value, long-term value). A rebuilder's lineup
    # getting better doesn't win it anything this year, so win-now counts at half.
    "window": {"Contender": (1.15, 0.75), "Middle": (1.0, 1.0), "Rebuilder": (0.5, 1.15)},
    # In the playoff race: within this many games of the last playoff spot
    "hunt_games": 1.5,
    # Bench players count this much of their win-now value (depth and injury insurance)
    "depth_weight": 0.25,
    # Each team's grade score mostly comes from how much better its own team got ("own"),
    # with a small share from how it did against the other team ("gap"). Both in value points.
    "blend": {"own": 0.75, "gap": 0.25},
    # Score of at least "big" = A (or F at -big); at least "small" = B (or D); in between = C
    "grade_gaps": {"big": 2000, "small": 1000},
}

LOTTERY_BALLS = {12: 35, 11: 27, 10: 20, 9: 10, 8: 6, 7: 3}
FLEX = {"FLEX": ("RB", "WR", "TE"), "WRRB_FLEX": ("RB", "WR"), "REC_FLEX": ("WR", "TE"),
        "SUPER_FLEX": ("QB", "RB", "WR", "TE")}


def lottery_odds(balls=LOTTERY_BALLS):
    seeds = list(balls)
    odds = {s: [0.0] * len(seeds) for s in seeds}
    for order in permutations(seeds):
        p, left = 1.0, sum(balls.values())
        for s in order:
            p *= balls[s] / left
            left -= balls[s]
        for slot, s in enumerate(order):
            odds[s][slot] += p
    return odds


def window_in_season(standing, games_back, playoff_teams=6):
    """Contender if in a playoff spot, Middle if within reach of one, Rebuilder if out of the race."""
    if standing <= playoff_teams:
        return "Contender"
    return "Middle" if games_back <= SETTINGS["hunt_games"] else "Rebuilder"


def window_from_final(standing, playoff_teams=6):
    """Before games are played, last season's finish sets the window."""
    if standing <= playoff_teams:
        return "Contender"
    return "Middle" if standing <= playoff_teams + 3 else "Rebuilder"


def prod_change(pos_rank):
    digits = "".join(ch for ch in str(pos_rank or "") if ch.isdigit())
    if not digits:
        return 0.0
    n = int(digits)
    for up_to, change in SETTINGS["production"]:
        if n <= up_to:
            return change
    return 0.0


def now_share(pos, age):
    a = SETTINGS["ages"].get(pos)
    if not a:
        return 0.9            # kickers and defenses are all about now
    if not age:
        return 0.5
    peak, cliff = a
    return max(0.15, min(0.9, 0.25 + 0.6 * (age - peak) / (cliff - peak)))


def split(value, pos, age, pos_rank=None, injury="", factor=1.0):
    """A player's value split into win-now and long-term parts."""
    base = (value or 0) * (1 + SETTINGS["injury"].get(injury or "", 0)) * factor
    share = now_share(pos, age)
    return base * share * (1 + prod_change(pos_rank)), base * (1 - share)


def best_lineup(players, slots):
    """players: list of {id, pos, now}. Returns ({player id: slot}, set of starter ids)."""
    pool = sorted(players, key=lambda p: -p["now"])
    used, placed = set(), {}
    for slot in [s for s in slots if s not in FLEX]:
        for p in pool:
            if p["id"] not in used and p["pos"] == slot:
                used.add(p["id"])
                placed[p["id"]] = slot
                break
    for slot in [s for s in slots if s in FLEX]:
        for p in pool:
            if p["id"] not in used and p["pos"] in FLEX[slot]:
                used.add(p["id"])
                placed[p["id"]] = slot
                break
    return placed, used


def team_score(players, pick_futures, slots, window):
    """How strong a team is: starters' win-now value, plus depth, plus long-term value."""
    placed, starters = best_lineup(players, slots)
    lineup_now = sum(p["now"] for p in players if p["id"] in starters)
    backups = {}
    for p in sorted(players, key=lambda p: -p["now"]):
        if p["id"] not in starters and p["pos"] in ("QB", "RB", "WR", "TE") and p["pos"] not in backups:
            backups[p["pos"]] = p["now"]
    depth = SETTINGS["depth_weight"] * sum(backups.values())
    future = sum(p["fut"] for p in players) + sum(pick_futures)
    w_now, w_fut = SETTINGS["window"].get(window, (1.0, 1.0))
    return w_now * (lineup_now + depth) + w_fut * future, placed


def team_grade(net_me, net_other):
    """A team's grade: mostly its own improvement, a little of how it did against the other side."""
    b = SETTINGS["blend"]
    score = b["own"] * net_me + b["gap"] * (net_me - net_other)
    big, small = SETTINGS["grade_gaps"]["big"], SETTINGS["grade_gaps"]["small"]
    if score >= big:
        return "A", round(score)
    if score >= small:
        return "B", round(score)
    if score > -small:
        return "C", round(score)
    if score > -big:
        return "D", round(score)
    return "F", round(score)


def pair_grades(net_a, net_b):
    """Grades for both teams in a trade."""
    return team_grade(net_a, net_b)[0], team_grade(net_b, net_a)[0]


def evaluate_side(roster, picks, gives, gets, slots, window):
    """roster: list of player assets {id, pos, now, fut, market}; picks: list of pick assets {id, fut, market}.
    gives/gets: lists of assets (players have "pos", picks don't). Returns this team's result."""
    give_ids = {a["id"] for a in gives}
    before, _ = team_score(roster, [p["fut"] for p in picks], slots, window)
    after_players = [p for p in roster if p["id"] not in give_ids] + [a for a in gets if a.get("pos")]
    after_picks = [p for p in picks if p["id"] not in give_ids] + [a for a in gets if not a.get("pos")]
    after, placed = team_score(after_players, [p["fut"] for p in after_picks], slots, window)
    net = after - before
    impact = []
    for a in gets:
        if a.get("pos"):
            slot = placed.get(a["id"])
            impact.append({"id": a["id"], "starts": bool(slot), "slot": slot})
    return {"net": round(net), "impact": impact,
            "market_given": round(sum(a["market"] for a in gives)), "market_got": round(sum(a["market"] for a in gets))}
