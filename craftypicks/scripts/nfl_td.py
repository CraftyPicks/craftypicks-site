"""Each player's chance of scoring a touchdown, and whether he did.

Poisson rather than the odds ratio the baseball boards use, and for a
concrete reason: a batter has a countable number of plate appearances, so a
per-chance probability compounds over them. A running back has no fixed
number of opportunities to score. What he has is a rate per game, and the
question "did at least one happen" is what Poisson answers:

    lambda = touchdowns_per_game * (opponent_allowed / league_allowed)
    chance = 1 - exp(-lambda)

Passing touchdowns are deliberately excluded from the verdict. A
quarterback who throws three has not scored one, and the market this board
mirrors -- anytime touchdown scorer -- agrees.
"""
from __future__ import annotations

import math

import nfl_data
import nfl_yards
import projection

# Touchdown-scale buckets. Most anytime chances sit under 40%, so the
# home-run board's edges would drop nearly every row into one bucket and
# the calibration table would have nothing to say.
TD_EDGES = ((0.0, 0.10), (0.10, 0.20), (0.20, 0.30),
            (0.30, 0.45), (0.45, 1.01))

MIN_GAMES = 4
PER_TEAM = 4

# The two that count as scoring, and the one that does not.
SCORING = ("rushing_tds", "receiving_tds")


def td_chance(rate: float, opp_allowed: float, league: float) -> float:
    """Probability of at least one touchdown, Poisson.

    Returns the unadjusted chance when there is nothing to compare
    against. A defence with no record is not a perfect defence.
    """
    if rate <= 0:
        return 0.0
    lam = rate
    if league > 0 and opp_allowed > 0:
        lam = rate * (opp_allowed / league)
    return 1.0 - math.exp(-lam)


def grade(history: list[dict], weekly: list[dict]) -> int:
    """Whether each projected player scored. Passing touchdowns do not count.

    Gated on projection.game_over, not merely on a feed line existing: a
    partial or corrected weekly line can appear while a game is still in
    progress, and settling the verdict the instant any line shows up --
    rather than once the game is actually over -- is what let a still-live
    game grade. A row with no parseable commence_time never settles.
    """
    scored: dict = {}
    for r in weekly:
        values = [r.get(f) for f in SCORING]
        if all(v is None for v in values):
            continue
        total = sum(v for v in values if v is not None)
        scored[(r.get("player_id"), r.get("game_id"))] = total > 0
    graded = 0
    for row in history:
        if row.get("scored") is not None:
            continue
        if not projection.game_over(row):
            continue
        key = (row.get("player_id"), row.get("game_id"))
        if key not in scored:
            continue
        row["scored"] = bool(scored[key])
        graded += 1
    return graded


def summary(history: list[dict]) -> dict:
    """Calibration: what was promised against what happened."""
    return projection.calibration(history, verdict_key="scored",
                                  edges=TD_EDGES)


def _with_any_td(rows: list[dict]) -> list[dict]:
    """Rushing and receiving scores summed into one field per row.

    The market does not care which way a player got there, so the two are
    combined once, here, rather than at every later call site.
    """
    return [
        dict(r, any_td=sum(v for v in (r.get(f) for f in SCORING)
                           if v is not None))
        for r in rows
    ]


def build(season: int, week: int | None = None) -> list[dict]:
    """One rated row per likely scorer in the coming week's games."""
    games = nfl_yards.schedule(season)
    if not games:
        return []
    if week is None:
        week = nfl_yards._next_week(games)
        if week is None:
            return []
    games = [g for g in games if g["week"] == week]
    if not games:
        return []

    prior_weekly = nfl_yards.season_weekly(season - 1)
    cur_weekly = nfl_yards.season_weekly(season)
    if not prior_weekly and not cur_weekly:
        return []

    cur_rows = _with_any_td(cur_weekly)
    old_rows = _with_any_td(prior_weekly)
    rates = nfl_data.blend(nfl_data.player_rates(cur_rows, "any_td"),
                           nfl_data.player_rates(old_rows, "any_td"))
    # Blended, not "current if any current exists else prior": one game of
    # a new season is not a defence's true rate -- the offence side already
    # gets this same shading. See nfl_data.blend_defence.
    allowed = nfl_data.blend_defence(cur_rows, old_rows, "any_td")
    league = ((sum(v["per_game"] for v in allowed.values()) / len(allowed))
              if allowed else 0.0)

    by_team: dict[str, list] = {}
    for pid, row in rates.items():
        if (row["games"] + row["prior_games"]) < MIN_GAMES:
            continue
        by_team.setdefault(row["team"], []).append((pid, row))

    rows = []
    for game in games:
        for side, opp in (("home", "away"), ("away", "home")):
            team = game[f"{side}_team"]
            other = game[f"{opp}_team"]
            opp_allowed = allowed.get(other, {}).get("per_game", 0.0)
            picked = sorted(by_team.get(team, []),
                            key=lambda kv: kv[1]["per_game"],
                            reverse=True)[:PER_TEAM]
            for pid, row in picked:
                rows.append({
                    "player_id": pid,
                    "name": row["name"],
                    "team": team,
                    "opponent": other,
                    "position": row["position"],
                    "per_game": round(row["per_game"], 3),
                    "chance": td_chance(row["per_game"], opp_allowed, league),
                    "weight": row["weight"],
                    "opp_allowed": round(opp_allowed, 2),
                    "league_allowed": round(league, 2),
                    "week": game["week"],
                    "game_id": game["game_id"],
                    "commence_time": game["commence_time"],
                    "scored": None,
                })
    rows.sort(key=lambda r: (r["commence_time"], -r["chance"]))
    return rows


def _self_test() -> None:
    # Poisson, because a player has no fixed number of chances to score.
    # A rate of 0.5 against an average defence: 1 - e^-0.5.
    assert abs(td_chance(0.5, 100.0, 100.0) - (1 - math.exp(-0.5))) < 1e-12

    # A defence allowing double the league doubles the rate, not the chance.
    doubled = td_chance(0.5, 200.0, 100.0)
    assert abs(doubled - (1 - math.exp(-1.0))) < 1e-12
    assert doubled < 2 * td_chance(0.5, 100.0, 100.0), \
        "a probability must not scale linearly"

    # Never certain, never negative, monotone in the rate.
    assert 0.0 < td_chance(0.01, 100.0, 100.0) < td_chance(2.0, 100.0, 100.0) < 1.0

    # Nothing to compare against leaves the rate alone.
    assert abs(td_chance(0.5, 100.0, 0.0) - (1 - math.exp(-0.5))) < 1e-12
    assert abs(td_chance(0.5, 0.0, 100.0) - (1 - math.exp(-0.5))) < 1e-12

    # A player who has never scored gets zero, not a floor invented for him.
    assert td_chance(0.0, 100.0, 100.0) == 0.0

    # Buckets are touchdown-scale. Most anytime chances sit under 40%, so
    # the home-run board's edges would put nearly every row in one bucket
    # and the calibration table would say nothing.
    assert TD_EDGES[0][0] == 0.0
    assert TD_EDGES[-1][1] > 1.0, "the top bucket must include a chance of 1"
    for (lo1, hi1), (lo2, hi2) in zip(TD_EDGES, TD_EDGES[1:]):
        assert hi1 == lo2, "buckets must be contiguous"

    # Grading: rushing and receiving touchdowns both count, and passing
    # ones do not -- a quarterback who throws three has not scored. Every
    # row's game is long finished, so game_over does not stand in the way.
    import datetime as _dt
    long_past = (_dt.datetime.now(_dt.timezone.utc)
                - _dt.timedelta(hours=10)).isoformat()
    hist = [{"player_id": "p1", "game_id": "g1", "scored": None,
             "chance": 0.4, "commence_time": long_past},
            {"player_id": "p2", "game_id": "g1", "scored": None,
             "chance": 0.3, "commence_time": long_past},
            {"player_id": "p3", "game_id": "g1", "scored": None,
             "chance": 0.2, "commence_time": long_past}]
    weekly = [
        {"player_id": "p1", "game_id": "g1", "rushing_tds": 1.0,
         "receiving_tds": 0.0, "passing_tds": 0.0},
        {"player_id": "p2", "game_id": "g1", "rushing_tds": 0.0,
         "receiving_tds": 0.0, "passing_tds": 3.0},
    ]
    assert grade(hist, weekly) == 2
    assert hist[0]["scored"] is True
    assert hist[1]["scored"] is False, "throwing three is not scoring"
    assert hist[2]["scored"] is None, "no line, no verdict"
    assert grade(hist, weekly) == 0

    # Finding 3: a feed line existing is not enough -- the game must be
    # over. A future game must never settle, no matter how many times
    # grade() runs against it, and missing/blank/garbage commence_time
    # must never read as "settle it now".
    soon = (_dt.datetime.now(_dt.timezone.utc)
           + _dt.timedelta(hours=2)).isoformat()
    future_row = {"player_id": "fp", "game_id": "gf", "scored": None,
                  "chance": 0.3, "commence_time": soon}
    future_weekly = [{"player_id": "fp", "game_id": "gf",
                      "rushing_tds": 1.0, "receiving_tds": 0.0,
                      "passing_tds": 0.0}]
    assert grade([future_row], future_weekly) == 0, \
        "a future game must not be graded just because a line exists"
    assert future_row["scored"] is None
    assert grade([future_row], future_weekly) == 0
    assert future_row["scored"] is None

    future_row["commence_time"] = long_past
    assert grade([future_row], future_weekly) == 1
    assert future_row["scored"] is True

    for bad_time in (None, "", "garbage"):
        row = {"player_id": "bp", "game_id": "gb", "scored": None,
              "chance": 0.1, "commence_time": bad_time}
        bad_weekly = [{"player_id": "bp", "game_id": "gb",
                      "rushing_tds": 1.0, "receiving_tds": 0.0,
                      "passing_tds": 0.0}]
        assert grade([row], bad_weekly) == 0, bad_time
        assert row["scored"] is None, bad_time

    s = summary(hist)
    assert s["graded"] == 2

    # build(), with the downloads stubbed.
    real_weekly, real_sched = nfl_yards.season_weekly, nfl_yards.schedule
    try:
        nfl_yards.season_weekly = lambda yr: ([] if yr == 2026 else [
            {"player_id": "rb1", "name": "A Runner", "team": "SEA",
             "position": "RB", "opponent_team": "NE", "season": 2025,
             "week": w, "game_id": f"a{w}", "rushing_tds": 1.0,
             "receiving_tds": 0.0, "carries": 18.0, "targets": 2.0}
            for w in range(1, 9)])
        nfl_yards.schedule = lambda yr: [{
            "game_id": "2026_01_NE_SEA", "week": 1, "gameday": "2026-09-09",
            "commence_time": "2026-09-09T20:15:00+00:00",
            "away_team": "NE", "home_team": "SEA",
            "home_qb_id": "", "home_qb_name": "", "away_qb_id": "",
            "away_qb_name": "", "roof": "outdoors", "stadium": "Lumen Field"}]
        rows = build(2026, week=1)
    finally:
        nfl_yards.season_weekly = real_weekly
        nfl_yards.schedule = real_sched

    assert len(rows) == 1, rows
    r = rows[0]
    assert r["player_id"] == "rb1" and r["team"] == "SEA"
    assert r["opponent"] == "NE"
    assert r["scored"] is None
    assert r["weight"] == 0.0, "no 2026 file yet"
    assert 0.0 < r["chance"] < 1.0
    assert r["commence_time"] == "2026-09-09T20:15:00+00:00"

    print("nfl_td self-test: the model holds and grades itself")


if __name__ == "__main__":
    _self_test()
