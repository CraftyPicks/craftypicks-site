"""Points, assists and rebounds projected for tonight's NBA slate.

The same argument the NFL yardage boards make, in a sport that plays every
night: a player's own rate, shaded toward last season's while this one is
young, then adjusted for how much the opponent gives up. Nothing here costs
a credit -- the schedule and the box scores are both free release files.

What is deliberately NOT here
-----------------------------
A posted line. Prop prices cost Odds API credits, the strikeout board's
measured record argues against spending more of them on player props, and a
projection is worth publishing on its own: the hit strip scores it against
our own number and says so.
"""
from __future__ import annotations

import csv
import io
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import nba_data            # noqa: E402
import nfl_data            # noqa: E402

SCHEDULE = (nba_data.RELEASE
            + "/espn_nba_schedules/nba_schedule_{season}.csv")

# Ten games of this season weigh the same as all of last season. Stated, not
# tuned: an 82-game season should take longer to trust than a 17-game one,
# and nfl_data.blend uses 4. Grading can argue with it later.
BLEND_K = 10

# How many players a club puts on the board. Three is the NFL boards' number
# and the reason is the same: a card per rotation player is a phone book.
TOP_N = 3

# A player needs this many games before a per-game rate means anything.
MIN_GAMES = 5

_sched_cache: dict = {}


def fetch_schedule(season: int, timeout: int = 120) -> list[dict]:
    if season in _sched_cache:
        return _sched_cache[season]
    url = SCHEDULE.format(season=season)
    req = urllib.request.Request(url, headers={"User-Agent": "craftypicks/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"!! nba schedule {url} failed ({type(e).__name__}: {e})",
              file=sys.stderr)
        _sched_cache[season] = []
        return []
    rows = parse_schedule(list(csv.DictReader(io.StringIO(text))))
    _sched_cache[season] = rows
    return rows


def parse_schedule(rows) -> list[dict]:
    """Regular-season fixtures between two real clubs, oldest first."""
    out = []
    for r in rows or []:
        if str(r.get("season_type", "")).strip() != nba_data.REGULAR:
            continue
        home = (r.get("home_abbreviation") or "").strip()
        away = (r.get("away_abbreviation") or "").strip()
        day = (r.get("game_date") or "").strip()
        if home not in nba_data.CLUBS or away not in nba_data.CLUBS or not day:
            continue
        out.append({
            "game_id": (r.get("id") or "").strip(),
            "date": day,
            "commence_time": (r.get("date") or "").strip(),
            "home": home, "away": away,
            "home_name": (r.get("home_display_name") or "").strip(),
            "away_name": (r.get("away_display_name") or "").strip(),
            "completed": str(r.get("status_type_completed", "")
                             ).strip().lower() == "true",
        })
    out.sort(key=lambda g: (g["date"], g["game_id"]))
    return out


def tonight(schedule, date_str: str) -> list[dict]:
    return [g for g in schedule if g["date"] == date_str]


def project(rate: float | None, allowed: float | None,
            league: float | None) -> float | None:
    """A player's rate, scaled by how much this opponent gives up.

    The same odds-free adjustment the NFL boards use: if a club allows 10%
    more than the league, everyone facing it is projected 10% higher. It is
    a blunt instrument and the calibration page is where it gets judged.
    """
    if rate is None:
        return None
    if not allowed or not league:
        return round(rate, 1)
    return round(rate * (allowed / league), 1)


def build(season: int, field: str, date_str: str, verbose: bool = True,
          top_n: int = TOP_N) -> list[dict]:
    """One row per player worth showing in tonight's games."""
    games = tonight(fetch_schedule(season), date_str)
    if not games:
        if verbose:
            print(f"   nba {field}: no games on {date_str}")
        return []

    # fetch() already parses. Parsing its output a second time hands raw-row
    # code a list of clean rows, every one of which it drops for having no
    # `did_not_play` field -- an empty board, no error, no clue. Caught by
    # projecting a night from last season and getting nothing back.
    current = nba_data.fetch(season)
    prior = nba_data.fetch(season - 1)
    if not current and not prior:
        return []

    rates = nfl_data.blend(
        nba_data.player_rates(current, field, MIN_GAMES),
        nba_data.player_rates(prior, field, MIN_GAMES), k=BLEND_K)
    # Defence from whichever season has games. Early on that is last
    # season's, which is the honest answer rather than a table of noise.
    allowed = nba_data.defence(current, field) or nba_data.defence(prior, field)
    league = nba_data.league_rate(allowed)

    by_team: dict[str, list] = {}
    for pid, row in rates.items():
        by_team.setdefault(row["team"], []).append((pid, row))

    rows = []
    for game in games:
        for side, other in ((game["home"], game["away"]),
                            (game["away"], game["home"])):
            squad = sorted(by_team.get(side, []),
                           key=lambda kv: -kv[1]["per_game"])[:top_n]
            for pid, row in squad:
                projection = project(row["per_game"], allowed.get(other),
                                     league)
                if projection is None:
                    continue
                rows.append({
                    "player_id": pid, "name": row["name"],
                    "team": side, "opponent": other,
                    # Carried, not inferred. The NFL boards had to unpick
                    # which club was hosting from the shape of a game id;
                    # the schedule says so outright, so the row says so too.
                    "is_home": side == game["home"],
                    "position": row.get("position", ""),
                    "game_id": game["game_id"],
                    "commence_time": game["commence_time"],
                    "date": date_str,
                    "stat": field,
                    "per_game": round(row["per_game"], 1),
                    "projection": projection,
                    "opp_allowed": round(allowed.get(other) or 0.0, 1),
                    "league_allowed": round(league, 1),
                    "weight": row["weight"],
                    "recent": nba_data.recent(current or prior, pid, field),
                    # Both seasons, because in October this season holds no
                    # meetings at all and the matchup is the whole point of
                    # the line. Two clubs meet three or four times a year, so
                    # even last season's four games are a real sample of a
                    # real matchup rather than a novelty.
                    "vs_opp": nba_data.vs_opponent(
                        (current or []) + (prior or []), pid, other, field),
                    "actual": None,
                })
    rows.sort(key=lambda r: (r["commence_time"], -r["projection"]))
    if verbose:
        print(f"   nba {field}: {len(rows)} player(s) across {len(games)} "
              f"game(s), league {league:.1f} allowed")
    return rows


def grade(history: list[dict], box_rows, field: str) -> int:
    """Fill in what each projected player actually did. Free, same file."""
    done = {(r["player_id"], r["date"]): r for r in box_rows
            if r.get(field) is not None}
    graded = 0
    for row in history:
        if row.get("actual") is not None or row.get("stat") != field:
            continue
        played = done.get((row.get("player_id"), row.get("date")))
        if played is None:
            continue
        row["actual"] = played[field]
        graded += 1
    return graded


def summary(history: list[dict], field: str = "") -> dict:
    """How far off the projections were, against doing nothing at all.

    There is no posted line on this board, so the benchmark is the simplest
    alternative to having a model: the player's own season average, with no
    opponent adjustment. `baseline` is that number's error on the same rows.

    It is here because a walk-forward backtest of 37 nights said the
    adjustment is worth almost nothing -- points -0.020 +/- 0.023, assists
    -0.012 +/- 0.010, rebounds -0.023 +/- 0.012 MAE. Two of the three are
    inside one standard error of zero. A board that publishes a projection
    should publish the number that says whether the projection earned its
    keep, and keep publishing it as the sample grows.
    """
    rows = [r for r in history if not field or r.get("stat") == field]
    done = [r for r in rows if r.get("actual") is not None]
    if not done:
        return {"rated": len(rows), "graded": 0, "mae": None,
                "baseline": None, "bias": None}
    mae = sum(abs(r["actual"] - r["projection"]) for r in done) / len(done)
    bias = sum(r["projection"] - r["actual"] for r in done) / len(done)
    flat = [r for r in done if r.get("per_game") is not None]
    baseline = (round(sum(abs(r["actual"] - r["per_game"]) for r in flat)
                      / len(flat), 2) if flat else None)
    return {"rated": len(rows), "graded": len(done),
            "mae": round(mae, 2), "baseline": baseline,
            "bias": round(bias, 2)}


def _self_test() -> None:
    sched_raw = [
        {"id": "g1", "game_date": "2026-10-20", "date": "2026-10-21T00:00Z",
         "season_type": "2", "home_abbreviation": "SA",
         "away_abbreviation": "OKC", "home_display_name": "San Antonio Spurs",
         "away_display_name": "Oklahoma City Thunder",
         "status_type_completed": "false"},
        # The All-Star Game again: real season_type 2, unreal clubs.
        {"id": "as1", "game_date": "2027-02-14", "date": "2027-02-14T00:00Z",
         "season_type": "2", "home_abbreviation": "STARS",
         "away_abbreviation": "STRIPES", "home_display_name": "Team Stars",
         "away_display_name": "Team Stripes",
         "status_type_completed": "false"},
        {"id": "p1", "game_date": "2027-04-20", "date": "2027-04-20T00:00Z",
         "season_type": "3", "home_abbreviation": "SA",
         "away_abbreviation": "OKC", "status_type_completed": "false"},
    ]
    sched = parse_schedule(sched_raw)
    assert len(sched) == 1 and sched[0]["home"] == "SA", sched
    assert sched[0]["away"] == "OKC"
    assert tonight(sched, "2026-10-20") and not tonight(sched, "2026-10-21")

    # --- the projection ------------------------------------------------------
    # A club that allows 10% more than the league lifts everyone facing it.
    assert project(20.0, 110.0, 100.0) == 22.0
    assert project(20.0, 90.0, 100.0) == 18.0
    # No defensive number is not a zero-point opponent.
    assert project(20.0, None, 100.0) == 20.0
    assert project(20.0, 110.0, 0.0) == 20.0
    assert project(None, 110.0, 100.0) is None

    # --- the opponent line ---------------------------------------------------
    # It is built from BOTH seasons on purpose. Checked here because an
    # October board built from this season alone would have an empty line on
    # every card, which is the one time of year the line matters most.
    seasons = [{"player_id": "1", "opponent": "GS", "points": 30.0},
               {"player_id": "1", "opponent": "GS", "points": 20.0}]
    assert nba_data.vs_opponent(seasons, "1", "GS", "points")["games"] == 2
    assert nba_data.vs_opponent(seasons[:0] + seasons[1:], "1", "GS",
                                "points")["per_game"] == 20.0

    # --- grading and the summary --------------------------------------------
    hist = [{"player_id": "1", "date": "2026-10-20", "stat": "points",
             "projection": 25.0, "actual": None},
            {"player_id": "2", "date": "2026-10-20", "stat": "points",
             "projection": 18.0, "actual": None},
            # A different stat's row must not be graded off the points column.
            {"player_id": "1", "date": "2026-10-20", "stat": "assists",
             "projection": 7.0, "actual": None}]
    box = [{"player_id": "1", "date": "2026-10-20", "points": 30.0,
            "assists": 9.0},
           {"player_id": "2", "date": "2026-10-20", "points": 12.0,
            "assists": 1.0}]
    assert grade(hist, box, "points") == 2
    assert hist[0]["actual"] == 30.0 and hist[2]["actual"] is None
    assert grade(hist, box, "points") == 0, "grading twice is not two gradings"
    assert grade(hist, box, "assists") == 1 and hist[2]["actual"] == 9.0

    for row, avg in zip(hist, (26.0, 20.0, 8.0)):
        row["per_game"] = avg
    s = summary(hist, "points")
    assert s["graded"] == 2
    # |25-30| + |18-12| = 11, over two.
    assert s["mae"] == 5.5, s
    # Positive bias means the projections were too high on average:
    # (25-30) + (18-12) = 1, over two.
    assert s["bias"] == 0.5, s
    # The benchmark: the same rows scored against the season average alone.
    # |26-30| + |20-12| = 12, over two.
    assert s["baseline"] == 6.0, s
    assert summary([], "points")["mae"] is None
    assert summary([], "points")["baseline"] is None
    # A row with no average cannot contribute to the benchmark, and must not
    # be silently scored as though its average were zero.
    no_avg = [{"player_id": "1", "date": "d", "stat": "points",
               "projection": 20.0, "actual": 22.0}]
    assert summary(no_avg, "points")["baseline"] is None
    assert summary(no_avg, "points")["mae"] == 2.0

    # A player who did not play is not graded as a zero -- nba_data.parse
    # has already dropped the row, so there is nothing to match against.
    absent = [{"player_id": "9", "date": "2026-10-20", "stat": "points",
               "projection": 20.0, "actual": None}]
    assert grade(absent, box, "points") == 0
    assert absent[0]["actual"] is None

    print("nba_stats self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
