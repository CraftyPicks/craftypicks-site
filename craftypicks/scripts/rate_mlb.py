"""A win probability for every MLB game on the board.

Deliberately simple, for a reason. Two inputs carry almost all the signal in
baseball — how good the teams are, and who's starting — so that's all this
uses. Head-to-head history and recent form are displayed on the site because
readers want them, and are given zero weight in the number, because at the
sample sizes involved they're noise wearing a suit.

Team strength is an Elo computed from actual results, walking games in date
order. It needs no training and no fitted coefficients: it calibrates itself
against what happened.

The starter adjustment is NOT fitted — it's a prior taken from the rough
run-to-win conversion in baseball (about a run of prevention is worth ~8-9
points of win probability, and a starter covers a bit over half a game). It
is the weakest part of this model and the calibration table exists to catch
it. If games we call 60% keep landing at 53%, this coefficient is why.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

import screen_mlb

# Elo settings. K is deliberately low — baseball is high-variance and a
# single game should barely move a rating.
K_FACTOR = 4.0
HOME_FIELD_ELO = 24.0          # ~54% for evenly matched teams, matching history
CARRYOVER = 0.70               # how much rating survives the offseason

# Win-probability points per 1.00 of season ERA difference between starters.
# A prior, not a fit. Capped so one blowup start can't swing a game rating.
STARTER_WEIGHT = 0.045
STARTER_ERA_CAP = 2.00
MIN_STARTER_INNINGS = 20.0

PROB_FLOOR, PROB_CEIL = 0.15, 0.85

# A disagreement with the market bigger than this is treated as a warning
# about our own model, not a signal. Fifteen books pricing a baseball game
# are not wrong by twelve points; we are. Flagged rather than hidden, and
# never eligible to become a play.
SUSPECT_DISAGREEMENT = 12.0


def season_results(season: int, through: date | None = None) -> list[dict]:
    """Every completed regular-season game this season, oldest first."""
    out = []
    for month in range(3, 11):
        start = date(season, month, 1)
        nxt = (start.replace(day=28) + timedelta(days=8)).replace(day=1)
        end = nxt - timedelta(days=1)
        if through and start > through:
            break
        data = screen_mlb._get("/schedule", sportId=1,
                               startDate=start.isoformat(),
                               endDate=min(end, through).isoformat() if through else end.isoformat(),
                               gameType="R") or {}
        for day in data.get("dates", []):
            for g in day.get("games", []):
                if g.get("status", {}).get("abstractGameState") != "Final":
                    continue
                home, away = g["teams"]["home"], g["teams"]["away"]
                if "score" not in home or "score" not in away:
                    continue
                out.append({
                    "date": g["gameDate"][:10],
                    "home_id": home["team"]["id"], "away_id": away["team"]["id"],
                    "home_score": home["score"], "away_score": away["score"],
                })
    out.sort(key=lambda r: r["date"])
    return out


def build_elo(results: list[dict], seed: dict | None = None) -> dict:
    """Ratings after every game given. Only past games ever inform a rating."""
    elo: dict[int, float] = defaultdict(lambda: 1500.0)
    if seed:
        elo.update(seed)
    for g in results:
        h, a = g["home_id"], g["away_id"]
        diff = (elo[h] + HOME_FIELD_ELO) - elo[a]
        expected = 1 / (1 + 10 ** (-diff / 400))
        actual = 1.0 if g["home_score"] > g["away_score"] else 0.0
        shift = K_FACTOR * (actual - expected)
        elo[h] += shift
        elo[a] -= shift
    return dict(elo)


def starter_adjustment(home_era: float | None, away_era: float | None,
                       home_ip: float = 0.0, away_ip: float = 0.0) -> float:
    """Win-probability points from the pitching matchup. Positive favours home."""
    if (home_era is None or away_era is None
            or home_ip < MIN_STARTER_INNINGS or away_ip < MIN_STARTER_INNINGS):
        return 0.0
    gap = max(-STARTER_ERA_CAP, min(STARTER_ERA_CAP, away_era - home_era))
    return gap * STARTER_WEIGHT


def rate_game(elo: dict, home_id: int, away_id: int,
              home_sp: dict | None = None, away_sp: dict | None = None) -> dict:
    """Our number for one game, with the pieces that produced it."""
    eh = elo.get(home_id, 1500.0)
    ea = elo.get(away_id, 1500.0)
    diff = (eh + HOME_FIELD_ELO) - ea
    p_elo = 1 / (1 + 10 ** (-diff / 400))

    home_sp = home_sp or {}
    away_sp = away_sp or {}
    adj = starter_adjustment(home_sp.get("era"), away_sp.get("era"),
                             home_sp.get("innings", 0.0), away_sp.get("innings", 0.0))
    p = max(PROB_FLOOR, min(PROB_CEIL, p_elo + adj))
    return {
        "home_elo": round(eh, 1), "away_elo": round(ea, 1),
        "elo_prob": round(p_elo, 4),
        "starter_adj": round(adj, 4),
        "home_win_prob": round(p, 4),
        "away_win_prob": round(1 - p, 4),
    }


def era_from_stats(stats: dict) -> dict:
    """Turn screen_mlb.pitcher_season output into what rate_game wants."""
    innings = stats.get("innings", 0.0) or 0.0
    k9 = stats.get("k_per_9")
    era = stats.get("era")
    if era is None and stats.get("k_pct") is not None:
        era = None
    return {"era": era, "innings": innings, "k_per_9": k9}


# ------------------------------------------------------------- calibration
BUCKETS = [(0.35, 0.45), (0.45, 0.50), (0.50, 0.55),
           (0.55, 0.60), (0.60, 0.65), (0.65, 1.01)]


def calibration(rated: list[dict]) -> list[dict]:
    """Did games we called X% actually happen X% of the time?

    This is the only claim on the site that can be checked in weeks rather
    than years, because every rated game counts — not just the ones we bet.
    """
    rows = []
    for lo, hi in BUCKETS:
        games = [r for r in rated
                 if r.get("result") in ("home", "away")
                 and lo <= r.get("home_win_prob", 0) < hi]
        if not games:
            rows.append({"lo": lo, "hi": hi, "n": 0, "predicted": 0.0,
                         "actual": 0.0, "gap": 0.0})
            continue
        predicted = sum(g["home_win_prob"] for g in games) / len(games)
        actual = sum(1 for g in games if g["result"] == "home") / len(games)
        rows.append({
            "lo": lo, "hi": hi, "n": len(games),
            "predicted": round(predicted * 100, 1),
            "actual": round(actual * 100, 1),
            "gap": round((actual - predicted) * 100, 1),
        })
    return rows


def brier(rated: list[dict]) -> float | None:
    """Mean squared error of the probabilities. Lower is better.

    Reference points: always guessing 50% scores 0.250. A good MLB model
    lands near 0.235. Anything above 0.250 is worse than a coin.
    """
    games = [r for r in rated if r.get("result") in ("home", "away")]
    if not games:
        return None
    total = sum((g["home_win_prob"] - (1.0 if g["result"] == "home" else 0.0)) ** 2
                for g in games)
    return round(total / len(games), 4)


def records(results: list[dict]) -> dict:
    """Win-loss for every team, overall and split by venue.

    Free: season_results() is already pulled to build the Elo, so this is
    arithmetic on data we hold rather than another request.
    """
    rec: dict = {}

    def slot(team_id):
        return rec.setdefault(team_id, {"w": 0, "l": 0, "hw": 0, "hl": 0,
                                        "aw": 0, "al": 0})

    for g in results:
        home, away = slot(g["home_id"]), slot(g["away_id"])
        if g["home_score"] == g["away_score"]:
            continue
        home_won = g["home_score"] > g["away_score"]
        if home_won:
            home["w"] += 1; home["hw"] += 1
            away["l"] += 1; away["al"] += 1
        else:
            home["l"] += 1; home["hl"] += 1
            away["w"] += 1; away["aw"] += 1
    return rec
