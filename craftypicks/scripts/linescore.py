#!/usr/bin/env python3
"""Runs scored in the first seven innings, per club, per game.

Why this file exists
--------------------
"Team total runs, 1st 7 innings" is a market, and nothing else on this site
can answer it. A full-game total cannot be scaled by seven ninths: the home
club does not bat in the ninth when it is ahead, so full-game numbers are
already asymmetric in a way F7 is not, and the last two innings are pitched
by a different set of arms than the first seven.

So the innings are read directly. StatsAPI's schedule hydrates a linescore
for every game in a date range, which makes a whole season a handful of free
requests rather than one per game.

What gets thrown away, and why
------------------------------
A game that did not reach seven innings has no F7. Counting it as the runs
it did have would report a rained-out four-inning afternoon as a shutout
through seven, and every club that plays in bad weather would read low. It
is dropped instead, and the count of drops is reported so a silent hole in
the data cannot look like a quiet month.

A seven-inning game -- the doubleheader rule, whenever it is in force -- is
dropped for the mirror-image reason: its seventh IS the ninth, so the home
club does not bat in it when ahead, and that is the exact asymmetry this
file exists to avoid. `scheduledInnings` is what tells them apart, and it is
read rather than assumed, because a season where the rule is off would drop
nothing and a season where it is on would otherwise poison every club's
home-park number.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import mlb_api  # noqa: E402

# The line everything here is about.
THROUGH = 7

# A full game. Anything else is a shortened game or a doubleheader half, and
# neither has a comparable seventh inning.
FULL_GAME_INNINGS = 9


def parse_counted(payload) -> tuple[list[dict], int]:
    """Every usable game in the payload, and how many were thrown away.

    The count is the point. A shape change at StatsAPI -- an inning key
    renamed, scheduledInnings no longer hydrated -- does not raise here, it
    quietly shrinks the sample, and a season that is silently half its real
    size still produces a confident-looking league baseline. The caller
    reports the drop rate so that cannot happen unnoticed.
    """
    out, dropped = [], 0
    for day in (payload or {}).get("dates", []) or []:
        for game in day.get("games", []) or []:
            row = _row(game, day.get("date") or "")
            if row:
                out.append(row)
            elif (game.get("status") or {}).get(
                    "abstractGameState") == "Final":
                # Only FINISHED games count as drops. A game that has not
                # been played yet is not a hole in the data.
                dropped += 1
    out.sort(key=lambda r: (r["date"], r["game_pk"]))
    return out, dropped


def parse(payload) -> list[dict]:
    """Every completed full-length game in the payload, as F7 rows.

    Pure: the fetch is next door. One row per GAME, carrying both clubs, so
    a caller can aggregate by club or by park without a second pass.
    """
    return parse_counted(payload)[0]


def _row(game: dict, date: str) -> dict | None:
    if (game.get("status") or {}).get("abstractGameState") != "Final":
        return None
    line = game.get("linescore") or {}
    # A game called early has fewer than seven innings on its line. A game
    # SCHEDULED for seven has a seventh the home club may never have batted
    # in. Both are out.
    if (line.get("scheduledInnings") or FULL_GAME_INNINGS) != FULL_GAME_INNINGS:
        return None
    innings = line.get("innings") or []
    played = {i.get("num") for i in innings if i.get("num")}
    if not set(range(1, THROUGH + 1)) <= played:
        return None

    teams = game.get("teams") or {}
    ids = {}
    for side in ("away", "home"):
        tid = ((teams.get(side) or {}).get("team") or {}).get("id")
        if tid is None:
            return None
        ids[side] = int(tid)

    runs = {"away": 0, "home": 0}
    for inning in innings:
        num = inning.get("num")
        if not num or num > THROUGH:
            continue
        for side in ("away", "home"):
            half = inning.get(side) or {}
            # A half-inning that was never played carries no "runs" key at
            # all. Inside the first seven of a nine-inning game that cannot
            # happen -- but reading it as 0 rather than raising keeps a
            # malformed payload from taking the whole season with it.
            runs[side] += int(half.get("runs") or 0)

    venue = (game.get("venue") or {}).get("id")
    return {
        "game_pk": int(game.get("gamePk") or 0),
        "date": (date or (game.get("gameDate") or "")[:10]),
        "away_id": ids["away"], "away_f7": runs["away"],
        "home_id": ids["home"], "home_f7": runs["home"],
        "venue_id": int(venue) if venue is not None else None,
    }


# Regular season, wild card, division series, league championship, world
# series. NOT spring training or the all-star game.
#
# "R" alone was wrong in a way that only shows up in October: the board
# projects whatever probable_starters lists, which includes the
# postseason, and grading fetched the regular season only -- so every
# playoff card ever published would have sat ungraded forever, during the
# month the site is read most.
GAME_TYPES = "R,F,D,L,W"


def fetch(start: str, end: str) -> tuple[list[dict], int]:
    """Every F7 row between two ISO dates, and the count of games dropped.

    One request per call.
    """
    return parse_counted(mlb_api._get(
        "/schedule", sportId=1, gameType=GAME_TYPES,
        startDate=start, endDate=end, hydrate="linescore"))


def season(year: int, through: str | None = None) -> tuple[list[dict], int]:
    """A whole season, in one request, with the drop count.

    The schedule endpoint answers a full year happily; it is the hydrate that
    makes the payload large, not the range. Split it only if that changes.
    """
    return fetch(f"{year}-01-01", through or f"{year}-12-31")


def team_rates(rows: list[dict]) -> dict[int, dict]:
    """Club id -> F7 runs scored and allowed, per game.

    Both halves in one pass, so the two can never be built off different
    game sets. `ra_pg` is carried for diagnostics only -- the board takes
    its defence from the rotation/bullpen split in mlb_api, which knows
    which arm pitches which inning, and this does not.
    """
    agg: dict[int, dict] = {}
    for r in rows:
        for side, other in (("away", "home"), ("home", "away")):
            t = agg.setdefault(r[f"{side}_id"],
                               {"g": 0, "rs": 0, "ra": 0,
                                "away_g": 0, "away_rs": 0})
            t["g"] += 1
            t["rs"] += r[f"{side}_f7"]
            t["ra"] += r[f"{other}_f7"]
            if side == "away":
                # Road games only. A club's all-games scoring rate is about
                # half its own park, so an offence index built from it
                # carries that park into every game the model projects --
                # including the ones played somewhere else entirely. The
                # road split is the cheapest estimate that is already on a
                # common footing, and it needs no park estimate to build.
                t["away_g"] += 1
                t["away_rs"] += r["away_f7"]
    for t in agg.values():
        t["rs_pg"] = t["rs"] / t["g"] if t["g"] else None
        t["ra_pg"] = t["ra"] / t["g"] if t["g"] else None
        t["away_rs_pg"] = (t["away_rs"] / t["away_g"]) if t["away_g"] else None
    return agg


def league_away_rate(rows: list[dict]) -> float | None:
    """Runs per road club per game, through seven.

    The denominator for the offence index. Pairing a road numerator with an
    all-games denominator would push every club's index down by the home
    advantage, uniformly -- harmless on its own, and exactly the kind of
    quiet constant that later gets mistaken for the model being calibrated.
    """
    if not rows:
        return None
    return sum(r["away_f7"] for r in rows) / len(rows)


def by_club(rows: list[dict]) -> dict:
    """{(game_pk, team_id): F7 runs}, for grading.

    Keyed on the GAME and not the date. A doubleheader is two games between
    the same two clubs on the same day with two different results, and a
    date key would settle both halves against one of them.
    """
    out = {}
    for r in rows:
        for side in ("away", "home"):
            out[(r["game_pk"], r[f"{side}_id"])] = r[f"{side}_f7"]
    return out


def league_rate(rows: list[dict]) -> float | None:
    """Runs per club per game through seven, across the whole set.

    The denominator is team-games, not games: every game contributes two.
    """
    if not rows:
        return None
    total = sum(r["away_f7"] + r["home_f7"] for r in rows)
    return total / (2 * len(rows))


def spread(rows: list[dict]) -> dict:
    """The shape of the F7 distribution, not just its middle.

    An over/under needs a probability, and a mean cannot give one. These two
    numbers are what the negative binomial in f7.py is fitted to: real F7
    scores are overdispersed against a Poisson of the same mean -- innings
    are not independent, because a rally is one inning -- and pricing them
    as Poisson would understate both tails.
    """
    vals = [r[f"{s}_f7"] for r in rows for s in ("away", "home")]
    n = len(vals)
    if n < 2:
        return {"n": n, "mean": None, "var": None, "counts": {}}
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    counts: dict[int, int] = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    return {"n": n, "mean": mean, "var": var,
            "counts": {k: counts[k] for k in sorted(counts)}}


def _self_test() -> None:
    def inning(num, a, h):
        return {"num": num, "away": {"runs": a}, "home": {"runs": h}}

    full = {
        "gamePk": 1, "status": {"abstractGameState": "Final"},
        "venue": {"id": 31},
        "teams": {"away": {"team": {"id": 112}},
                  "home": {"team": {"id": 158}}},
        "linescore": {"scheduledInnings": 9, "innings": [
            inning(1, 1, 0), inning(2, 0, 0), inning(3, 0, 2),
            inning(4, 0, 0), inning(5, 3, 0), inning(6, 0, 1),
            inning(7, 0, 0), inning(8, 2, 0),
            {"num": 9, "away": {"runs": 0}, "home": {}},
        ]},
    }
    rows = parse({"dates": [{"date": "2026-05-01", "games": [full]}]})
    assert len(rows) == 1, rows
    r = rows[0]
    # 1+0+0+0+3+0+0 = 4 away, 0+0+2+0+0+1+0 = 3 home. The eighth and ninth
    # are in the payload and must not be counted.
    assert (r["away_f7"], r["home_f7"]) == (4, 3), r
    assert r["venue_id"] == 31 and r["date"] == "2026-05-01"

    # A game called after five has no seventh inning. Dropped, not read as a
    # shutout through seven -- which is what would make every club that
    # plays in the rain look like it cannot score.
    rain = {**full, "gamePk": 2,
            "linescore": {"scheduledInnings": 9, "innings": [
                inning(1, 1, 0), inning(2, 0, 0), inning(3, 0, 0),
                inning(4, 0, 1), inning(5, 0, 0)]}}
    assert parse({"dates": [{"games": [rain]}]}) == []

    # A seven-inning doubleheader half is dropped even though it HAS seven
    # innings: its seventh is a ninth, and the home club does not bat in it
    # when ahead. scheduledInnings is the only thing that says so.
    twin = {**full, "gamePk": 3,
            "linescore": {"scheduledInnings": 7,
                          "innings": full["linescore"]["innings"][:7]}}
    assert parse({"dates": [{"games": [twin]}]}) == []

    # In progress, and a payload with nothing in it.
    live = {**full, "gamePk": 4, "status": {"abstractGameState": "Live"}}
    assert parse({"dates": [{"games": [live]}]}) == []
    assert parse(None) == [] and parse({}) == []

    # ---- aggregation. Every game counts for BOTH clubs, once each way.
    two = parse({"dates": [{"date": "2026-05-01", "games": [full]},
                           {"date": "2026-05-02", "games": [
                               {**full, "gamePk": 5,
                                "teams": {"away": {"team": {"id": 158}},
                                          "home": {"team": {"id": 112}}}}]}]})
    assert len(two) == 2
    rates = team_rates(two)
    assert rates[112]["g"] == 2 and rates[158]["g"] == 2
    # Club 112 was away in the first (4 scored, 3 allowed) and home in the
    # second (3 scored, 4 allowed).
    assert rates[112]["rs"] == 7 and rates[112]["ra"] == 7, rates[112]
    assert rates[112]["rs_pg"] == 3.5
    assert league_rate(two) == 3.5, league_rate(two)

    # ---- the spread. Variance above the mean is the whole reason the board
    # prices with a negative binomial rather than a Poisson.
    s = spread(two)
    assert s["n"] == 4 and s["counts"] == {3: 2, 4: 2}, s
    assert s["mean"] == 3.5
    assert spread([])["mean"] is None

    # ---- away-only rates. A club's own park is baked into its all-games
    # scoring rate, so an offence index built from it carries that park into
    # every road game the model projects. Measured: the correlation between
    # a club's road-game error and its OWN park factor was +0.53 before this
    # existed and -0.06 after.
    rates2 = team_rates(two)
    assert rates2[112]["away_g"] == 1 and rates2[112]["away_rs"] == 4, rates2[112]
    assert rates2[112]["away_rs_pg"] == 4.0
    # The second fixture game swaps the CLUBS, not the linescore, so the
    # away side scored 4 in both. Both clubs therefore read 4.0 on the road
    # while both read 3.5 across all games -- which is the whole point: the
    # two numbers are different, and the road one is the clean one.
    assert rates2[158]["away_rs_pg"] == 4.0, rates2[158]
    assert rates2[158]["rs_pg"] == 3.5, "all-games rate is unchanged"
    assert league_away_rate(two) == 4.0, league_away_rate(two)
    assert league_away_rate([]) is None

    # ---- the drop count. The docstring has always promised one.
    rain = {"gamePk": 9, "status": {"abstractGameState": "Final"},
            "teams": {"away": {"team": {"id": 1}}, "home": {"team": {"id": 2}}},
            "linescore": {"scheduledInnings": 9,
                          "innings": [inning(1, 1, 0), inning(2, 0, 0)]}}
    kept, dropped = parse_counted({"dates": [{"games": [full, rain]}]})
    assert len(kept) == 1 and dropped == 1, (kept, dropped)
    assert parse({"dates": [{"games": [full, rain]}]}) == kept, \
        "parse stays the plain list; the counted form is the one that reports"

    # ---- the grading key. Two halves of a doubleheader are two entries,
    # which a date key could not express.
    twin = [dict(two[0], game_pk=10), dict(two[0], game_pk=11, away_f7=0)]
    keyed = by_club(twin)
    assert keyed[(10, 112)] == 4 and keyed[(11, 112)] == 0, keyed
    assert len(keyed) == 4, keyed

    print("linescore self-test: seven innings, and only the games that had them")


if __name__ == "__main__":
    _self_test()
