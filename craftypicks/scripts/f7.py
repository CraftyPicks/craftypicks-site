#!/usr/bin/env python3
"""Team total runs through seven innings, projected and priced.

The market is "TEAM: Team Total Runs - 1st 7 Innings, over/under N". To have
an opinion on it you need two things, and only the first is obvious:

  1. how many runs this lineup should score off these arms in this park
  2. how often a lineup that averages that many clears the line

The second is where a projection becomes a price. A club projected at 3.9
runs is not "over 3.5" at any particular number until you know the shape of
the distribution around 3.9 -- and at +114 the bet needs 46.7% to break
even, which a mean cannot tell you.

The model
---------
Multiplicative, against a league baseline, which is the standard way to
combine independent rate effects and is the same log5 combination
batters.py already uses for home runs:

    projection = league F7 baseline
               x this lineup's offence
               x the arms it faces, weighted by who pitches which inning
               x the park

The third factor is the one this file exists for. Seven innings is about
five of starter and two of bullpen, so the opposing STARTER is not the
opposing pitching. A club with a good rotation and a poor bullpen and a club
with the reverse can carry identical team ERAs and give up their runs at
completely different times -- which is invisible in a full-game total and
decisive in a first-seven one.

Every index is regressed toward 1.0 by its own sample size. The constants
below are priors, not measurements: they are the honest starting point for a
model with no graded history, and the calibration this file publishes is
what will eventually say whether they are right. They are named and grouped
so that tuning them is a one-line change against a backtest rather than an
archaeology expedition.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import linescore  # noqa: E402
import mlb_api    # noqa: E402

# Innings the market covers.
THROUGH = linescore.THROUGH

# How much evidence each index needs before it is believed in full. An index
# built on n units is pulled toward 1.0 by k / (n + k), so at n == k it is
# taken half-strength.
#
# PRIORS, not findings. Team scoring settles faster than any individual
# rate, a starter's runs-allowed rate is famously noisy, and a bullpen is a
# rotating cast so its number describes a group that keeps changing.
OFF_SHRINK_GAMES = 30
SP_SHRINK_INNINGS = 60
PEN_SHRINK_INNINGS = 120

# A starter with no record goes this deep. The league average start has sat
# near five and a bit for years; it is written here rather than computed
# because a pitcher with no starts has no ip_per_start to compute from.
DEFAULT_START_LENGTH = 5.2

# Below this the projection is published without a probability. A line needs
# a distribution and a distribution needs a shape, and a shape fitted to a
# handful of games is a decoration.
MIN_SPREAD_SAMPLE = 200


def shrink(value: float | None, n: float | None, k: float,
           toward: float = 1.0) -> float:
    """An index pulled toward `toward` by how little is behind it."""
    if value is None or n is None or n <= 0:
        return toward
    w = n / (n + k)
    return toward + (value - toward) * w


def dispersion(spread: dict) -> float | None:
    """The negative binomial shape r, from the observed mean and variance.

    Runs in seven innings are overdispersed against a Poisson of the same
    mean, and not by a little: innings are not independent trials, because a
    rally is one inning. Pricing them as Poisson understates both tails,
    which is exactly the part of the distribution an over/under is about.

    Returns None when the sample is too thin, or when the variance comes out
    at or below the mean -- which means the data is not overdispersed and
    this model does not apply, rather than meaning r is enormous.
    """
    n, mean, var = spread.get("n") or 0, spread.get("mean"), spread.get("var")
    if n < MIN_SPREAD_SAMPLE or not mean or var is None or var <= mean:
        return None
    return (mean * mean) / (var - mean)


def _log_nb_pmf(x: int, mean: float, r: float) -> float:
    p = r / (r + mean)
    return (math.lgamma(x + r) - math.lgamma(r) - math.lgamma(x + 1)
            + r * math.log(p) + x * math.log1p(-p))


def p_at_least(k: int, mean: float, r: float | None) -> float | None:
    """P(runs >= k) for a club projected at `mean`.

    Summed from below and subtracted, rather than summed from k upwards: the
    tail has no end and the head has exactly k terms.
    """
    if mean is None or mean <= 0 or r is None or r <= 0 or k <= 0:
        return None
    below = sum(math.exp(_log_nb_pmf(x, mean, r)) for x in range(k))
    return max(0.0, min(1.0, 1.0 - below))


def p_over(line: float, mean: float, r: float | None) -> float | None:
    """P(runs beats `line`). A half-point line cannot push, which is why
    every posted first-seven team total carries one."""
    if line is None:
        return None
    return p_at_least(math.floor(line) + 1, mean, r)


def project(*, league_f7: float, team_rs_pg: float | None, team_games: int,
            sp: dict | None, pen_rpi: float | None, pen_ip: float | None,
            league_rpi: float, park: float = 1.0) -> dict | None:
    """One club's expected runs through seven, and the parts it came from.

    Returns the working, not just the answer. Every number the card prints
    is in here, because a projection a reader cannot take apart is a number
    they have to take on trust, and this site does not ask for that.
    """
    if not league_f7 or not league_rpi:
        return None

    offence = shrink((team_rs_pg / league_f7) if team_rs_pg else None,
                     team_games, OFF_SHRINK_GAMES)

    sp = sp or {}
    sp_index = shrink(
        (sp.get("r_per_inning") / league_rpi) if sp.get("r_per_inning") else None,
        sp.get("innings"), SP_SHRINK_INNINGS)
    pen_index = shrink((pen_rpi / league_rpi) if pen_rpi else None,
                       pen_ip, PEN_SHRINK_INNINGS)

    # How much of the seven is his. Regressed like everything else: a man
    # with three starts has not shown you how deep he goes.
    length = shrink(sp.get("ip_per_start"), sp.get("starts"), 6,
                    toward=DEFAULT_START_LENGTH)
    sp_innings = max(0.0, min(float(THROUGH), length))
    pen_innings = THROUGH - sp_innings

    # The innings-weighted blend of the two staffs. This is the whole point
    # of the file: a starter who goes seven IS the defence, and one who goes
    # four hands two thirds of the market to his bullpen.
    defence = (sp_innings * sp_index + pen_innings * pen_index) / THROUGH

    mean = league_f7 * offence * defence * park
    return {
        "projection": round(mean, 2),
        "league_f7": round(league_f7, 3),
        "offence": round(offence, 3),
        "sp_index": round(sp_index, 3),
        "pen_index": round(pen_index, 3),
        "defence": round(defence, 3),
        "park": round(park, 3),
        "sp_innings": round(sp_innings, 2),
    }


# The ladder the board publishes. Not the book's line -- reading that costs
# a credit per event, and this board is free. A reader looks up whichever
# number their book is offering and reads our probability off the rung.
#
# Three rungs because these are the ones that get posted: the market for a
# first-seven team total sits at 2.5, 3.5 or 4.5 almost without exception,
# and a half point everywhere means no rung can push.
LINES = (2.5, 3.5, 4.5)


def price(row: dict, r: float | None, lines=LINES) -> dict:
    """Add the probability of clearing each rung of the ladder."""
    out = dict(row)
    probs = {}
    for line in lines:
        pr = p_over(line, row["projection"], r)
        if pr is not None:
            probs[f"{line:g}"] = round(pr, 4)
    out["probs"] = probs
    return out


# ------------------------------------------------------------------ grading
def grade(history: list[dict], f7_by_game: dict) -> int:
    """Settle published projections against what the club actually scored.

    `f7_by_game` is {(game_pk, team_id): runs}. Keyed on the game and not the
    date: a doubleheader is two games between the same two clubs on the same
    day, and a date key would grade both halves against one of them.

    A graded row is never re-graded and never edited. That is the whole
    value of the store.
    """
    done = 0
    for row in history:
        if row.get("actual") is not None:
            continue
        key = (row.get("game_pk"), row.get("team_id"))
        if key not in f7_by_game:
            continue
        row["actual"] = int(f7_by_game[key])
        row["miss"] = round(row["actual"] - row["projection"], 2)
        done += 1
    return done


def merge(history: list[dict], fresh: list[dict]) -> int:
    """Store today's projections, never overwriting one already published."""
    seen = {(r.get("game_pk"), r.get("team_id")) for r in history}
    added = 0
    for row in fresh:
        key = (row.get("game_pk"), row.get("team_id"))
        if key in seen or key[0] is None:
            continue
        history.append(dict(row))
        seen.add(key)
        added += 1
    return added


# The calibration bands. A projection is only useful if a club projected at
# 4.5 really does score more than a club projected at 3.0, and these bands
# are what shows whether that holds.
BANDS = ((0.0, 3.0), (3.0, 3.75), (3.75, 4.5), (4.5, 99.0))


def summary(history: list[dict]) -> dict:
    """Mean absolute error, and what each band actually scored.

    MAE against a naive baseline is the only test that matters here: the
    baseline is the league's own F7 average applied to everybody, and a
    model that cannot beat it has learned nothing about pitching or parks.
    """
    graded = [r for r in history if r.get("actual") is not None]
    out = {"published": len(history), "graded": len(graded),
           "mae": None, "baseline_mae": None, "bands": [], "over_rate": None}
    if not graded:
        return out
    out["mae"] = round(
        sum(abs(r["actual"] - r["projection"]) for r in graded) / len(graded), 3)
    flat = sum(r["actual"] for r in graded) / len(graded)
    out["baseline_mae"] = round(
        sum(abs(r["actual"] - flat) for r in graded) / len(graded), 3)
    out["baseline"] = round(flat, 2)

    for lo, hi in BANDS:
        rows = [r for r in graded if lo <= r["projection"] < hi]
        if not rows:
            continue
        out["bands"].append({
            "lo": lo, "hi": hi, "n": len(rows),
            "projected": round(sum(r["projection"] for r in rows) / len(rows), 2),
            "actual": round(sum(r["actual"] for r in rows) / len(rows), 2),
        })

    # One row per rung: what the board said would happen, against what did.
    # A probability nobody scores is a decoration, and this is the table
    # that stops it being one.
    rungs = []
    for line in LINES:
        key = f"{line:g}"
        rows = [r for r in graded if (r.get("probs") or {}).get(key) is not None]
        if not rows:
            continue
        rungs.append({
            "line": line, "n": len(rows),
            "said": round(sum(r["probs"][key] for r in rows) / len(rows), 3),
            "were": round(sum(1 for r in rows if r["actual"] > line)
                          / len(rows), 3),
        })
    out["over_rate"] = rungs
    return out


# --------------------------------------------------------------- the board
def inputs(season: int, through: str | None = None) -> dict:
    """Everything the projection needs, in four free requests.

    One schedule call with linescores hydrated, one player-stats call for
    the rotation/bullpen split, and two team-splits calls for the park --
    and the park pair is already in _get's cache because the home-run board
    asked for the same two payloads this morning.
    """
    rows = linescore.season(season, through)
    staff = mlb_api.staff_split(season)
    import batters as batters_mod                            # noqa: PLC0415
    try:
        park = batters_mod.park_factors(season, stat="runs")
    except Exception as e:                                   # noqa: BLE001
        print(f"   !! f7 park factors unavailable ({type(e).__name__}: {e})",
              file=sys.stderr)
        park = {}
    return {
        # Kept, not just counted: grading settles against these same rows,
        # and re-fetching them would be a second request for a payload we
        # are already holding.
        "rows": rows,
        "games": len(rows),
        "league_f7": linescore.league_rate(rows),
        "teams": linescore.team_rates(rows),
        "spread": linescore.spread(rows),
        "staff": staff,
        "league_rpi": mlb_api.league_runs_per_inning(staff),
        "park": park,
    }


def build(starters: list[dict], season: int, verbose: bool = True,
          data: dict | None = None) -> list[dict]:
    """One row per club per game: the runs it should score through seven.

    Driven off the STARTERS list, because each starter row already names
    both clubs and says which dugout he is in. The row a starter produces
    is the OTHER club's projection -- he is the defence on it.
    """
    if not starters:
        return []
    d = data or inputs(season)
    league_f7, league_rpi = d.get("league_f7"), d.get("league_rpi")
    if not league_f7 or not league_rpi:
        if verbose:
            print("   f7: no league baseline yet; nothing to project")
        return []
    r = dispersion(d.get("spread") or {})
    if verbose and r is None:
        print(f"   f7: {(d.get('spread') or {}).get('n', 0)} club-games is "
              f"too few to fit a shape; projections only, no probabilities")

    out = []
    for sp in starters:
        pitcher_team, batting_team = sp.get("team_id"), sp.get("opponent_id")
        if not pitcher_team or not batting_team:
            continue
        # The park belongs to whichever club is at home, which the starter
        # row already knows about itself.
        home_id = pitcher_team if sp.get("is_home") else batting_team
        park = ((d["park"].get(home_id) or {}).get("factor")) or 1.0

        bats = (d["teams"].get(batting_team) or {})
        arms = (d["staff"].get(pitcher_team) or {})
        try:
            season_line = mlb_api.pitcher_season(sp["pitcher_id"], season)
        except Exception:                                    # noqa: BLE001
            season_line = {}

        row = project(league_f7=league_f7,
                      team_rs_pg=bats.get("rs_pg"), team_games=bats.get("g") or 0,
                      sp=season_line, pen_rpi=arms.get("rp_rpi"),
                      pen_ip=arms.get("rp_ip"), league_rpi=league_rpi,
                      park=park)
        if not row:
            continue
        row = price(row, r)
        row.update({
            "game_pk": sp.get("game_pk"),
            "team_id": batting_team,
            "team": sp.get("opponent"),
            "opponent": sp.get("team"),
            "is_home": not sp.get("is_home"),
            "pitcher": sp.get("name"),
            "pitcher_hand": sp.get("hand", ""),
            "pitcher_era": season_line.get("era"),
            "venue": sp.get("venue", ""),
            "commence_time": sp.get("game_time", ""),
            "actual": None,
        })
        out.append(row)

    out.sort(key=lambda x: (x.get("commence_time") or "", x.get("team") or ""))
    if verbose:
        print(f"   f7: {len(out)} club-game(s) projected from "
              f"{d['games']} game(s) of linescores")
    return out


def _self_test() -> None:
    # ---- shrinkage pulls toward neutral in proportion to the evidence.
    assert shrink(1.4, 30, 30) == 1.2, "at n == k an index is taken half"
    assert shrink(1.4, None, 30) == 1.0, "no sample, no claim"
    assert shrink(1.4, 0, 30) == 1.0
    assert round(shrink(4.0, 6, 6, toward=5.2), 3) == 4.6, \
        "start length regresses toward the league's, not toward 1.0"

    # ---- the distribution. Fitted to a sample drawn from a KNOWN shape, so
    # a wrong formula cannot pass by accident.
    import random
    random.seed(7)
    true_mean, true_r = 3.6, 5.0
    p = true_r / (true_r + true_mean)

    def geometric():
        """Failures before the first success. NB(1, p)."""
        n = 0
        while random.random() >= p:
            n += 1
        return n

    # NB(r, p) is the sum of r independent geometrics, for integer r. The
    # first version of this line used ONE geometric and called it NB(5),
    # which is NB(1) -- the fitted shape came back at 1.02 and the assertion
    # caught it. Worth keeping the note: a sampler that is quietly wrong
    # makes the thing it is testing look right.
    draws = [sum(geometric() for _ in range(int(true_r)))
             for _ in range(40000)]
    obs = {"n": len(draws), "mean": sum(draws) / len(draws),
           "var": sum((d - sum(draws) / len(draws)) ** 2
                      for d in draws) / (len(draws) - 1)}
    r_hat = dispersion(obs)
    assert r_hat is not None and 3.5 < r_hat < 7.5, (r_hat, obs)

    # A thin sample, and a sample that is not overdispersed, both decline to
    # answer rather than inventing a shape.
    assert dispersion({"n": 20, "mean": 3.6, "var": 5.0}) is None
    assert dispersion({"n": 5000, "mean": 3.6, "var": 3.6}) is None
    assert dispersion({"n": 5000, "mean": 3.6, "var": 2.0}) is None

    # The pmf sums to one, which is the one check that catches a wrong
    # normalising constant.
    total = sum(math.exp(_log_nb_pmf(x, 3.6, 5.0)) for x in range(200))
    assert abs(total - 1.0) < 1e-9, total

    # P(>= 4) against the empirical frequency from the same draws.
    empirical = sum(1 for d in draws if d >= 4) / len(draws)
    modelled = p_at_least(4, true_mean, true_r)
    assert abs(modelled - empirical) < 0.02, (modelled, empirical)

    # Over 3.5 is P(>= 4); the half point is what stops a push.
    assert p_over(3.5, true_mean, true_r) == p_at_least(4, true_mean, true_r)
    # A whole-number line is NOT treated as a push: 4 is floor(4) + 1 = 5.
    assert p_over(4.0, true_mean, true_r) == p_at_least(5, true_mean, true_r)
    # More runs projected, more often over. Monotone, or the price is noise.
    assert (p_over(3.5, 3.0, 5.0) < p_over(3.5, 3.6, 5.0)
            < p_over(3.5, 4.5, 5.0))
    assert p_at_least(4, 3.6, None) is None, "no shape, no probability"

    # ---- the projection. Each input moved one at a time, so a sign error in
    # any single factor cannot hide behind the others.
    base = dict(league_f7=3.6, team_rs_pg=3.6, team_games=162,
                sp={"r_per_inning": 0.45, "innings": 180, "starts": 30,
                    "ip_per_start": 6.0},
                pen_rpi=0.45, pen_ip=500, league_rpi=0.45, park=1.0)
    flat = project(**base)
    assert abs(flat["projection"] - 3.6) < 0.02, flat
    assert flat["offence"] == 1.0
    # Six innings a start, regressed toward the league's 5.2 over 30 starts.
    # NOT 6.0: the length is shrunk like every other index, and asserting
    # the raw value here would quietly pin the shrink out of existence.
    assert 5.8 < flat["sp_innings"] < 5.9, flat["sp_innings"]

    better_lineup = project(**{**base, "team_rs_pg": 4.4})
    assert better_lineup["projection"] > flat["projection"]

    # An ace suppresses, and a batting-practice arm does not.
    ace = project(**{**base, "sp": {**base["sp"], "r_per_inning": 0.30}})
    assert ace["projection"] < flat["projection"], ace

    # The bullpen matters, and it matters MORE behind a short starter. This
    # is the assertion the whole file exists for: with the same terrible
    # bullpen, the club whose starter goes four concedes more than the club
    # whose starter goes seven.
    bad_pen = {**base, "pen_rpi": 0.70}
    deep = project(**{**bad_pen,
                      "sp": {**base["sp"], "ip_per_start": 7.0}})
    short = project(**{**bad_pen,
                       "sp": {**base["sp"], "ip_per_start": 4.0}})
    assert short["projection"] > deep["projection"], (short, deep)
    assert deep["pen_index"] == short["pen_index"], "same bullpen, both cards"
    assert short["sp_innings"] < deep["sp_innings"], (short, deep)

    # A starter who goes the whole seven leaves the bullpen no innings, so
    # his card must not move at all when the bullpen changes. Reaching seven
    # AFTER regression needs a long enough record that the shrink is done,
    # which is itself the point: a rookie does not get credited with it.
    whole = {"r_per_inning": 0.45, "innings": 700, "starts": 100,
             "ip_per_start": 7.0}
    a = project(**{**base, "sp": whole, "pen_rpi": 0.30})
    b = project(**{**base, "sp": whole, "pen_rpi": 0.90})
    assert a["sp_innings"] > 6.85, a["sp_innings"]
    deep_spread = abs(a["projection"] - b["projection"])

    # The same two bullpens behind a four-inning starter. Stated as a ratio
    # rather than a tolerance: the claim is that the bullpen's influence
    # scales with the innings it is handed, and a bare "these are close"
    # would pass even if the weighting were dropped entirely.
    stub = {"r_per_inning": 0.45, "innings": 700, "starts": 100,
            "ip_per_start": 4.0}
    c = project(**{**base, "sp": stub, "pen_rpi": 0.30})
    d = project(**{**base, "sp": stub, "pen_rpi": 0.90})
    short_spread = abs(c["projection"] - d["projection"])
    assert short_spread > 8 * deep_spread, (short_spread, deep_spread)

    # The park multiplies the answer and nothing else.
    coors = project(**{**base, "park": 1.15})
    assert abs(coors["projection"] - flat["projection"] * 1.15) < 0.02

    # No baseline, no projection -- rather than a projection of zero.
    assert project(**{**base, "league_f7": 0}) is None

    # ---- pricing joins the two halves, one rung at a time.
    priced = price(flat, 5.0)
    assert set(priced["probs"]) == {"2.5", "3.5", "4.5"}, priced["probs"]
    assert 0.4 < priced["probs"]["3.5"] < 0.6, priced["probs"]
    # A higher line is harder to clear. If the ladder ever reads the other
    # way round the floor/ceiling in p_over has been inverted.
    assert (priced["probs"]["2.5"] > priced["probs"]["3.5"]
            > priced["probs"]["4.5"]), priced["probs"]
    assert price(flat, None)["probs"] == {}, "no shape, no ladder"

    # ---- the store. A doubleheader is the case a date key gets wrong.
    hist = []
    twin = [
        {"game_pk": 1, "team_id": 112, "projection": 3.8,
         "probs": {"3.5": 0.52}},
        {"game_pk": 2, "team_id": 112, "projection": 3.4,
         "probs": {"3.5": 0.45}},
    ]
    assert merge(hist, twin) == 2
    assert merge(hist, twin) == 0, "a published number is never republished"
    assert grade(hist, {(1, 112): 6, (2, 112): 1}) == 2
    assert hist[0]["actual"] == 6 and hist[1]["actual"] == 1
    assert hist[0]["miss"] == 2.2, hist[0]
    assert grade(hist, {(1, 112): 99}) == 0, "a graded row is never re-graded"
    assert hist[0]["actual"] == 6

    # ---- the summary, including the baseline it has to beat.
    s = summary(hist)
    assert s["graded"] == 2 and s["published"] == 2
    assert s["mae"] == round((2.2 + 2.4) / 2, 3), s
    assert s["baseline_mae"] is not None and s["baseline"] == 3.5
    # One rung, two rows: the board said 48.5% and one of the two went over.
    rung = next(r for r in s["over_rate"] if r["line"] == 3.5)
    assert rung["n"] == 2 and rung["said"] == 0.485 and rung["were"] == 0.5, rung
    # The rungs nobody was priced on are absent, not reported as zero.
    assert [r["line"] for r in s["over_rate"]] == [3.5], s["over_rate"]
    assert summary([])["graded"] == 0

    # ---- build(), on a stubbed slate. No network: `data` is handed in, and
    # the one call build() makes on its own is stubbed out.
    real_season = mlb_api.pitcher_season
    mlb_api.pitcher_season = lambda pid, season: {
        "r_per_inning": 0.40, "innings": 150, "starts": 26,
        "ip_per_start": 5.8, "era": 3.20}
    try:
        slate = [
            {"pitcher_id": 1, "name": "A Starter", "hand": "R",
             "team": "CLE", "team_id": 114, "opponent": "CWS",
             "opponent_id": 145, "is_home": True, "game_pk": 77,
             "game_time": "2026-09-20T17:10:00Z", "venue": "Progressive Field"},
            {"pitcher_id": 2, "name": "B Starter", "hand": "L",
             "team": "CWS", "team_id": 145, "opponent": "CLE",
             "opponent_id": 114, "is_home": False, "game_pk": 77,
             "game_time": "2026-09-20T17:10:00Z", "venue": "Progressive Field"},
        ]
        data = {
            "games": 1200, "league_f7": 3.6, "league_rpi": 0.45,
            "teams": {114: {"g": 150, "rs_pg": 4.1, "ra_pg": 3.4},
                      145: {"g": 150, "rs_pg": 3.0, "ra_pg": 4.0}},
            "staff": {114: {"rp_rpi": 0.38, "rp_ip": 520},
                      145: {"rp_rpi": 0.55, "rp_ip": 510}},
            "spread": obs,
            # Cleveland's park suppresses; Chicago's is not used here,
            # because both halves of this game are played in Cleveland.
            "park": {114: {"factor": 0.94}, 145: {"factor": 1.08}},
        }
        rows = build(slate, 2026, verbose=False, data=data)
        assert len(rows) == 2, rows
        by_team = {r["team"]: r for r in rows}

        # The row a starter produces is the OTHER club's projection. Get
        # this backwards and every card on the board is the wrong lineup
        # against the wrong arm, while looking entirely plausible.
        assert by_team["CWS"]["opponent"] == "CLE", by_team["CWS"]
        assert by_team["CWS"]["pitcher"] == "A Starter"
        assert by_team["CLE"]["pitcher"] == "B Starter"
        assert by_team["CWS"]["team_id"] == 145

        # Both halves are played in the same park, so both carry Cleveland's
        # factor. Taking the batting club's park instead is the natural bug
        # and would give the two halves different ones.
        assert by_team["CWS"]["park"] == 0.94, by_team["CWS"]
        assert by_team["CLE"]["park"] == 0.94, by_team["CLE"]

        # Cleveland's better lineup against Chicago's worse bullpen outscores
        # the reverse.
        assert (by_team["CLE"]["projection"]
                > by_team["CWS"]["projection"]), by_team

        # The home club is the one NOT in the starter row that made it.
        assert by_team["CLE"]["is_home"] is True
        assert by_team["CWS"]["is_home"] is False
        assert by_team["CLE"]["game_pk"] == 77
        assert by_team["CLE"]["probs"]["3.5"] > 0

        # No starters, no board -- rather than an empty page of zeroes.
        assert build([], 2026, verbose=False, data=data) == []
        # No baseline, no board.
        assert build(slate, 2026, verbose=False,
                     data={**data, "league_f7": None}) == []
    finally:
        mlb_api.pitcher_season = real_season

    # ---- end to end: is the ladder honest?
    # A synthetic season where the projection is EXACTLY right by
    # construction. If the pricing is sound, the clubs the board gives 44%
    # to must go over about 44% of the time -- and if it is not, no amount
    # of work on the projection will make the percentages mean anything.
    #
    # This is the one test that covers dispersion, p_over and summary
    # together. Each has passed on its own while the chain was wrong.
    random.seed(11)
    true_r = 4.5

    def nb_draw(mean, r):
        """A negative binomial draw for any r, integer or not.

        Gamma-Poisson: the run environment of one game is itself drawn from
        a Gamma, and runs within it are Poisson. That IS the negative
        binomial, and it is the only formulation that works at r = 4.5 --
        summing r geometrics needs an integer, and rounding r to get one
        quietly tests a different distribution than the board prices with.
        """
        lam = random.gammavariate(r, mean / r)
        # Knuth. Fine at these rates; the loop runs mean-ish times.
        target, k, prod = math.exp(-lam), 0, random.random()
        while prod > target:
            k += 1
            prod *= random.random()
        return k

    sim = []
    for i in range(6000):
        mean = random.uniform(2.4, 5.2)
        actual = nb_draw(mean, true_r)
        row = price({"projection": round(mean, 2)}, true_r)
        row.update({"game_pk": i, "team_id": 1, "actual": actual,
                    "miss": round(actual - mean, 2)})
        sim.append(row)
    cal = summary(sim)
    for rung in cal["over_rate"]:
        gap = abs(rung["said"] - rung["were"])
        assert gap < 0.035, (rung, "the ladder is not calibrated")
    # And the model beats the flat baseline when the model is right, which
    # is the comparison the page publishes.
    assert cal["mae"] < cal["baseline_mae"], cal

    print("f7 self-test: the bullpen gets the innings the starter does not")


if __name__ == "__main__":
    _self_test()
