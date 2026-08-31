"""League-agnostic Elo ratings, driven from dated results.

One rating engine for every sport on the board: give it a list of finished
games and a per-league config and it plays the season forward. It deliberately
does not know anything sport-specific — starting pitcher, rest, travel,
injuries — which each sport's own module layers on top of the number this
produces.
"""
from __future__ import annotations

from dataclasses import astuple, dataclass


@dataclass(frozen=True)
class EloConfig:
    """Per-league Elo settings.

    Does not adapt K to margin of victory. A 10-run win and a 1-run win move
    the rating identically, which understates blowouts on purpose — margin is
    noisier than the result and this project has not yet measured whether
    weighting it helps.

    `regress` is configured but not yet applied. Nothing in this module reads
    it, because `run()` plays a single stream of games forward and has no
    concept of a season boundary to regress across. The per-league values are
    kept here rather than derived twice; they take effect when multi-season
    support arrives with the historical backtest.
    """
    k: float
    home_edge: float      # rating points, not probability
    start: float = 1500.0
    regress: float = 0.0  # fraction pulled back to start between seasons


# K is smaller where a season is short: a 17-game NFL season cannot support
# MLB's per-game movement without the ratings thrashing. Home edge is in
# rating points and reflects each sport's measured home-field advantage.
LEAGUE_CONFIG: dict[str, EloConfig] = {
    "mlb":   EloConfig(k=4.0,  home_edge=24.0,  regress=0.25),
    "nba":   EloConfig(k=20.0, home_edge=100.0, regress=0.25),
    "nfl":   EloConfig(k=20.0, home_edge=55.0,  regress=0.33),
    "ncaab": EloConfig(k=24.0, home_edge=100.0, regress=0.50),
}


def win_probability(rating_home: float, rating_away: float,
                    config: EloConfig) -> float:
    """Probability the home side wins, from the rating gap plus home edge.

    Does not account for rest, travel, injuries or the starting pitcher. Those
    are layered on by the sport's own module where the data exists.
    """
    gap = (rating_home + config.home_edge) - rating_away
    return 1.0 / (1.0 + 10.0 ** (-gap / 400.0))


def run(results: list[dict], config: EloConfig) -> dict[str, float]:
    """Play a season forward and return each team's final rating.

    Results are sorted by date before anything is applied, so a rating can
    never be influenced by a game that had not yet happened. Ties leave both
    teams untouched — there is no winner to move the ratings toward.
    """
    ratings: dict[str, float] = {}
    for g in sorted(results, key=lambda r: (r.get("date") or "", r.get("home") or "")):
        home, away = g["home"], g["away"]
        rh = ratings.setdefault(home, config.start)
        ra = ratings.setdefault(away, config.start)
        if g["home_score"] == g["away_score"]:
            continue
        expected = win_probability(rh, ra, config)
        actual = 1.0 if g["home_score"] > g["away_score"] else 0.0
        move = config.k * (actual - expected)
        ratings[home] = rh + move
        ratings[away] = ra - move
    return ratings


def _self_test() -> None:
    cfg = LEAGUE_CONFIG["mlb"]

    # A rating pair with no edge and no home advantage is a coin flip.
    flat = EloConfig(k=cfg.k, home_edge=0.0, start=1500.0, regress=0.0)
    assert abs(win_probability(1500, 1500, flat) - 0.5) < 1e-9

    # Home advantage moves the number the right way.
    assert win_probability(1500, 1500, cfg) > 0.5

    # A stronger team is favoured.
    assert win_probability(1600, 1400, flat) > 0.7

    # Elo is zero-sum: one game moves both ratings by the same amount.
    games = [{"date": "2026-04-01", "home": "A", "away": "B",
              "home_score": 5, "away_score": 3}]
    r = run(games, flat)
    assert abs((r["A"] - 1500) + (r["B"] - 1500)) < 1e-9, "not zero-sum"
    assert r["A"] > 1500 and r["B"] < 1500

    # A tie leaves both ratings untouched rather than guessing a winner.
    tied = run([{"date": "2026-04-01", "home": "A", "away": "B",
                 "home_score": 4, "away_score": 4}], flat)
    assert abs(tied["A"] - 1500) < 1e-9 and abs(tied["B"] - 1500) < 1e-9

    # No look-ahead: results are applied in date order regardless of input
    # order, so a later game can never influence an earlier rating.
    a = run([{"date": "2026-04-01", "home": "A", "away": "B",
              "home_score": 5, "away_score": 3},
             {"date": "2026-04-02", "home": "B", "away": "A",
              "home_score": 9, "away_score": 1}], flat)
    b = run([{"date": "2026-04-02", "home": "B", "away": "A",
              "home_score": 9, "away_score": 1},
             {"date": "2026-04-01", "home": "A", "away": "B",
              "home_score": 5, "away_score": 3}], flat)
    assert a == b, "result order changed the ratings"

    # An empty season produces no ratings rather than raising.
    assert run([], flat) == {}

    # Every league has a config, and no two leagues carry the SAME SETTINGS.
    # The hazard is a copy-paste: a league added by duplicating another's
    # line and never retuned would give two sports identical Elo behaviour
    # with nothing in the output looking wrong. Comparing id() could not
    # catch that — four separate EloConfig(...) calls always have four
    # distinct ids, so that assertion could never fail. Compare the values.
    #
    # Compared whole, via astuple, not field by field: nba and ncaab already
    # legitimately share home_edge=100.0 and are distinguished only by k, so
    # a per-field uniqueness check would be a false alarm.
    assert set(LEAGUE_CONFIG) == {"mlb", "nba", "nfl", "ncaab"}
    shapes = [astuple(c) for c in LEAGUE_CONFIG.values()]
    assert len(set(shapes)) == len(shapes), \
        "two leagues have identical Elo settings — copy-paste, or retune one"
    assert LEAGUE_CONFIG["nba"].home_edge == LEAGUE_CONFIG["ncaab"].home_edge, \
        "the shared home_edge above is deliberate; update the comment if it changes"
    assert LEAGUE_CONFIG["nfl"].k != LEAGUE_CONFIG["mlb"].k, \
        "NFL plays 17 games; it cannot use MLB's K"

    print("ratings self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
