"""Projected passing, rushing and receiving yards, and how wrong they were.

One model, three categories. The number is the player's own per-game rate,
blended between this season and last, multiplied by how much the defence he
faces allows relative to the league:

    projection = rate * (opponent_allowed_per_game / league_allowed_per_game)

There is no book line beside it, and that is deliberate -- a posted line is
what makes the pitcher board cost money. What replaces it is the baseline:
the same player's rate with NO opponent adjustment, stored on every row.
If the adjusted number cannot beat that, the adjustment is decoration, and
the page is built to reveal that rather than hide it.

The defensive term is not regressed in this first version. With no line to
disagree with, an unregressed number is easier to read the grading of, and
the grading is what will say whether regression is needed. Not regressed is
not the same as not blended, though: the defensive rate is still shaded
between this season and last exactly as the offensive rate is (see
nfl_data.blend_defence), so that week 2 does not compute an entire team's
defence off a single game.
"""
from __future__ import annotations

import nfl_data
import projection

# Per category: the yardage column, the column that decides who is worth
# listing, and how many names per team the board shows.
CATEGORIES = {
    "passing":   {"field": "passing_yards",   "volume": "attempts",
                  "td_field": "passing_tds",   "per_team": 1,
                  "label": "Passing yards"},
    "rushing":   {"field": "rushing_yards",   "volume": "carries",
                  "td_field": "rushing_tds",   "per_team": 2,
                  "label": "Rushing yards"},
    "receiving": {"field": "receiving_yards", "volume": "targets",
                  "td_field": "receiving_tds", "per_team": 3,
                  "label": "Receiving yards"},
}

# Below this a season line is a sample, not a rate.
MIN_GAMES = 4


def _def_factor(opp_allowed: float, league: float) -> float:
    """The multiplier project() actually applies to a rate.

    Exists so the row's own stored explanation can never drift from the
    adjustment that was really used: guarded on the exact same condition as
    project() below, a defence with no record (or a league mean of zero)
    reads as neutral, 1.0 -- never as a suppressor that zeroed the player
    out on no evidence.
    """
    if league <= 0 or opp_allowed <= 0:
        return 1.0
    return opp_allowed / league


def project(rate: float, opp_allowed: float, league: float) -> float:
    """A player's rate, adjusted for the defence he faces.

    Returns the unadjusted rate when there is nothing to compare against.
    A defence with no record is not a perfect defence, and zeroing a player
    out on the strength of no evidence would be the worst kind of wrong --
    confident and unfounded.
    """
    return rate * _def_factor(opp_allowed, league)


def grade(history: list[dict], weekly: list[dict], category: str) -> int:
    """Record what each projected player actually did.

    Matched on the player and the game, so a player projected twice in a
    season is graded against the right week. A game with no line in the
    feed yet stays ungraded rather than being recorded as zero.

    Also gated on projection.game_over: nflverse can publish a partial
    weekly line while a game is still being played (a stat correction, a
    backfill from an earlier week), and settling a row the moment ANY
    line exists for that game -- rather than once the game itself is
    over -- is what let a still-live game grade. A row with no parseable
    commence_time never settles, the same conservative default game_over
    already uses.
    """
    field = CATEGORIES[category]["field"]
    actuals = {}
    for r in weekly:
        value = r.get(field)
        if value is None:
            continue
        actuals[(r.get("player_id"), r.get("game_id"))] = value
    graded = 0
    for row in history:
        if row.get("actual") is not None:
            continue
        if not projection.game_over(row):
            continue
        key = (row.get("player_id"), row.get("game_id"))
        if key not in actuals:
            continue
        row["actual"] = actuals[key]
        graded += 1
    return graded


def summary(history: list[dict]) -> dict:
    """How wrong the projections were, against the unadjusted baseline."""
    return projection.error_summary(
        history, actual_key="actual", projection_key="projection")


def season_weekly(season: int) -> list[dict]:
    """One season of per-player weekly lines, or an empty list.

    An empty list is the correct answer for a season that has not started:
    stats_player_week_2026.csv.gz does not exist until the first week is
    played, and that is what makes the blend weight zero rather than an
    error.
    """
    assets = nfl_data.asset_urls()
    url = assets.get(f"stats_player_week_{season}.csv.gz")
    if not url:
        return []
    return nfl_data.parse_weekly(nfl_data.fetch_csv_gz(url) or [])


def schedule(season: int) -> list[dict]:
    assets = nfl_data.asset_urls()
    url = assets.get("games.csv")
    if not url:
        return []
    return nfl_data.parse_schedule(nfl_data.fetch_csv(url) or [], season)


def _next_week(games: list[dict]) -> int | None:
    """The earliest week that has not finished yet."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    upcoming = [g for g in games
                if not projection.game_over(g, now)]
    return min((g["week"] for g in upcoming), default=None)


def build(season: int, category: str, week: int | None = None) -> list[dict]:
    """One rated row per player worth listing in the coming week's games.

    Returns an empty list rather than raising whenever anything it needs is
    missing. An empty board says nothing; a traceback stops the run.
    """
    if category not in CATEGORIES:
        return []
    spec = CATEGORIES[category]
    games = schedule(season)
    if not games:
        return []
    if week is None:
        week = _next_week(games)
        if week is None:
            return []
    games = [g for g in games if g["week"] == week]
    if not games:
        return []

    prior_weekly = season_weekly(season - 1)
    cur_weekly = season_weekly(season)
    if not prior_weekly and not cur_weekly:
        return []

    field, volume = spec["field"], spec["volume"]
    rates = nfl_data.blend(nfl_data.player_rates(cur_weekly, field),
                           nfl_data.player_rates(prior_weekly, field))
    vols = nfl_data.blend(nfl_data.player_rates(cur_weekly, volume),
                          nfl_data.player_rates(prior_weekly, volume))
    # Blended, not "current if any current exists else prior": one game of
    # a new season is not a defence's true rate, and the offence side
    # already gets this same shading -- see nfl_data.blend_defence.
    allowed = nfl_data.blend_defence(cur_weekly, prior_weekly, field)
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

            if category == "passing":
                # The schedule names the starter, which beats any guess --
                # and deliberately skips the MIN_GAMES floor below. A QB
                # with one game of history but named by the schedule is
                # still better evidence than inferring someone else off a
                # bigger sample; the floor exists for the players we have
                # to guess about, and the schedule already answered that
                # question for the passer.
                pid = game[f"{side}_qb_id"]
                picked = [(pid, rates[pid])] if pid in rates else []
            else:
                picked = sorted(
                    by_team.get(team, []),
                    key=lambda kv: vols.get(kv[0], {}).get("per_game", 0.0),
                    reverse=True)[:spec["per_team"]]

            for pid, row in picked:
                rows.append({
                    "player_id": pid,
                    "name": row["name"],
                    "team": team,
                    "opponent": other,
                    "position": row["position"],
                    "per_game": round(row["per_game"], 1),
                    "baseline": round(row["per_game"], 1),
                    "projection": round(
                        project(row["per_game"], opp_allowed, league), 1),
                    "weight": row["weight"],
                    "opp_allowed": round(opp_allowed, 1),
                    "league_allowed": round(league, 1),
                    "def_factor": round(_def_factor(opp_allowed, league), 3),
                    "week": game["week"],
                    "game_id": game["game_id"],
                    "commence_time": game["commence_time"],
                    "actual": None,
                })
    rows.sort(key=lambda r: (r["commence_time"], -r["projection"]))
    return rows


def _self_test() -> None:
    # An average defence leaves the player's own rate untouched.
    assert project(80.0, 100.0, 100.0) == 80.0

    # A defence allowing 20% more than the league lifts him 20%.
    assert abs(project(80.0, 120.0, 100.0) - 96.0) < 1e-9

    # A league mean of zero cannot divide, and must not raise. With nothing
    # to compare against, the player's own rate is the honest answer.
    assert project(80.0, 120.0, 0.0) == 80.0

    # A defence that has allowed nothing yet is not infinitely good; with
    # no evidence the adjustment is neutral rather than zeroing him out.
    assert project(80.0, 0.0, 100.0) == 80.0

    # Three categories, each naming the column it reads and the one that
    # decides who is worth listing.
    assert set(CATEGORIES) == {"passing", "rushing", "receiving"}
    assert CATEGORIES["passing"]["field"] == "passing_yards"
    assert CATEGORIES["rushing"]["field"] == "rushing_yards"
    assert CATEGORIES["receiving"]["field"] == "receiving_yards"
    assert CATEGORIES["rushing"]["volume"] == "carries"
    assert CATEGORIES["receiving"]["volume"] == "targets"

    # Grading matches on the player and the game, and records the signed
    # error. A game with no line yet stays ungraded. Both rows' games are
    # long finished, so game_over does not stand between the feed line
    # and the verdict here.
    import datetime as _dt
    long_past = (_dt.datetime.now(_dt.timezone.utc)
                - _dt.timedelta(hours=10)).isoformat()
    hist = [{"player_id": "p1", "game_id": "g9", "projection": 80.0,
             "actual": None, "commence_time": long_past},
            {"player_id": "p2", "game_id": "g9", "projection": 60.0,
             "actual": None, "commence_time": long_past}]
    weekly = [{"player_id": "p1", "game_id": "g9", "rushing_yards": 95.0}]
    assert grade(hist, weekly, "rushing") == 1
    assert hist[0]["actual"] == 95.0
    assert hist[1]["actual"] is None, "no line means no verdict"
    assert grade(hist, weekly, "rushing") == 0, "graded once"

    s = summary(hist)
    assert s["graded"] == 1
    assert s["mae"] == 15.0, s

    # Finding 3: grading must be gated on the game being over, not merely
    # on a feed line existing for it. A future game must never settle no
    # matter how many times grade() is called against it, and missing,
    # blank or unparseable commence_time must never be treated as "settle
    # it now" -- the same conservative default projection.game_over uses
    # everywhere else on the site.
    soon = (_dt.datetime.now(_dt.timezone.utc)
           + _dt.timedelta(hours=2)).isoformat()
    future_row = {"player_id": "fp", "game_id": "gf", "projection": 50.0,
                  "actual": None, "commence_time": soon}
    future_weekly = [{"player_id": "fp", "game_id": "gf",
                      "rushing_yards": 40.0}]
    assert grade([future_row], future_weekly, "rushing") == 0, \
        "a future game must not be graded just because a line exists"
    assert future_row["actual"] is None
    # Calling it again, still before kickoff, changes nothing.
    assert grade([future_row], future_weekly, "rushing") == 0
    assert future_row["actual"] is None

    # Once the same game is in the past, it grades normally.
    future_row["commence_time"] = long_past
    assert grade([future_row], future_weekly, "rushing") == 1
    assert future_row["actual"] == 40.0

    for bad_time in (None, "", "garbage"):
        row = {"player_id": "bp", "game_id": "gb", "projection": 1.0,
              "actual": None, "commence_time": bad_time}
        bad_weekly = [{"player_id": "bp", "game_id": "gb",
                      "rushing_yards": 5.0}]
        assert grade([row], bad_weekly, "rushing") == 0, bad_time
        assert row["actual"] is None, bad_time

    # build(), with every download stubbed. This is the only way it can be
    # tested in an environment with no network.
    real_weekly, real_sched = season_weekly, schedule
    try:
        globals()["season_weekly"] = lambda yr: (
            [] if yr == 2026 else [
                {"player_id": "qb1", "name": "Home Passer", "team": "SEA",
                 "position": "QB", "opponent_team": "NE", "season": 2025,
                 "week": w, "game_id": f"a{w}", "passing_yards": 300.0,
                 "attempts": 35.0, "passing_tds": 2.0}
                for w in range(1, 9)
            ] + [
                {"player_id": "qb2", "name": "Away Passer", "team": "NE",
                 "position": "QB", "opponent_team": "SEA", "season": 2025,
                 "week": w, "game_id": f"b{w}", "passing_yards": 200.0,
                 "attempts": 30.0, "passing_tds": 1.0}
                for w in range(1, 9)
            ])
        globals()["schedule"] = lambda yr: [{
            "game_id": "2026_01_NE_SEA", "week": 1, "gameday": "2026-09-09",
            "commence_time": "2026-09-09T20:15:00+00:00",
            "away_team": "NE", "home_team": "SEA",
            "home_qb_id": "qb1", "home_qb_name": "Home Passer",
            "away_qb_id": "qb2", "away_qb_name": "Away Passer",
            "roof": "outdoors", "stadium": "Lumen Field"}]
        rows = build(2026, "passing", week=1)
    finally:
        globals()["season_weekly"] = real_weekly
        globals()["schedule"] = real_sched

    assert len(rows) == 2, f"one passer a side: {rows}"
    by_id = {r["player_id"]: r for r in rows}
    home = by_id["qb1"]
    assert home["team"] == "SEA" and home["opponent"] == "NE"
    assert home["commence_time"] == "2026-09-09T20:15:00+00:00"
    assert home["actual"] is None and home["week"] == 1
    assert home["game_id"] == "2026_01_NE_SEA"
    # No 2026 file exists, so the weight must be exactly zero and the
    # baseline must be last season's raw rate.
    assert home["weight"] == 0.0, home
    assert home["baseline"] == 300.0, home
    # SEA's defence allowed 200/game, NE's allowed 300/game, league mean 250.
    # Home passer faces NE: 300 * (300/250) = 360.
    assert abs(home["projection"] - 360.0) < 1e-6, home

    # MIN_GAMES excludes a low-sample runner from the ranking: a single game
    # of history must not put a name on the board next to a full season's
    # worth of evidence.
    try:
        globals()["season_weekly"] = lambda yr: (
            [] if yr == 2026 else [
                {"player_id": "rb_ok", "name": "Steady Back", "team": "SEA",
                 "position": "RB", "opponent_team": "NE", "season": 2025,
                 "week": w, "game_id": f"c{w}", "rushing_yards": 80.0,
                 "carries": 18.0, "rushing_tds": 0.0}
                for w in range(1, 9)
            ] + [
                {"player_id": "rb_low", "name": "Thin Sample", "team": "SEA",
                 "position": "RB", "opponent_team": "NE", "season": 2025,
                 "week": 1, "game_id": "d1", "rushing_yards": 20.0,
                 "carries": 5.0, "rushing_tds": 0.0}
            ])
        globals()["schedule"] = lambda yr: [{
            "game_id": "2026_01_NE_SEA", "week": 1, "gameday": "2026-09-09",
            "commence_time": "2026-09-09T20:15:00+00:00",
            "away_team": "NE", "home_team": "SEA",
            "home_qb_id": "", "home_qb_name": "",
            "away_qb_id": "", "away_qb_name": "",
            "roof": "outdoors", "stadium": "Lumen Field"}]
        rushing_rows = build(2026, "rushing", week=1)
    finally:
        globals()["season_weekly"] = real_weekly
        globals()["schedule"] = real_sched
    rushing_ids = {r["player_id"] for r in rushing_rows}
    assert "rb_low" not in rushing_ids, \
        f"a runner with one game of history leaked past MIN_GAMES: {rushing_rows}"
    assert "rb_ok" in rushing_ids, rushing_rows

    # A week absent from an otherwise populated schedule is also empty --
    # asking for a week nothing was scheduled for must not raise or
    # silently fall back to some other week.
    try:
        globals()["schedule"] = lambda yr: [{
            "game_id": "2026_01_NE_SEA", "week": 1, "gameday": "2026-09-09",
            "commence_time": "2026-09-09T20:15:00+00:00",
            "away_team": "NE", "home_team": "SEA",
            "home_qb_id": "", "home_qb_name": "",
            "away_qb_id": "", "away_qb_name": "",
            "roof": "outdoors", "stadium": "Lumen Field"}]
        assert build(2026, "rushing", week=5) == [], \
            "a week absent from the schedule must return []"
    finally:
        globals()["schedule"] = real_sched

    # An unknown category is a quiet empty board, not a KeyError.
    assert build(2026, "not_a_category") == [], \
        "an unknown category must return [] rather than raise"

    # def_factor guard (Finding 2): an opponent with no defensive record at
    # all must read as neutral -- def_factor 1.0 and projection == baseline
    # -- not as a zero that implies the defence suppresses everything.
    try:
        globals()["season_weekly"] = lambda yr: (
            [] if yr == 2026 else [
                {"player_id": "rb_new_opp", "name": "Runner", "team": "SEA",
                 "position": "RB", "opponent_team": "ZZZ", "season": 2025,
                 "week": w, "game_id": f"e{w}", "rushing_yards": 90.0,
                 "carries": 20.0, "rushing_tds": 0.0}
                for w in range(1, 9)
            ])
        globals()["schedule"] = lambda yr: [{
            "game_id": "2026_01_SEA_NEW", "week": 1, "gameday": "2026-09-09",
            "commence_time": "2026-09-09T20:15:00+00:00",
            "away_team": "NEW", "home_team": "SEA",
            "home_qb_id": "", "home_qb_name": "",
            "away_qb_id": "", "away_qb_name": "",
            "roof": "outdoors", "stadium": "Lumen Field"}]
        no_record_rows = build(2026, "rushing", week=1)
    finally:
        globals()["season_weekly"] = real_weekly
        globals()["schedule"] = real_sched
    assert len(no_record_rows) == 1, no_record_rows
    no_record_row = no_record_rows[0]
    assert no_record_row["opponent"] == "NEW"
    assert no_record_row["opp_allowed"] == 0.0, no_record_row
    assert no_record_row["def_factor"] == 1.0, \
        f"an opponent with no record must read neutral, not suppressive: {no_record_row}"
    assert no_record_row["projection"] == no_record_row["baseline"], no_record_row

    # An empty schedule is a quiet board, not a traceback.
    try:
        globals()["schedule"] = lambda yr: []
        assert build(2026, "passing") == []
    finally:
        globals()["schedule"] = real_sched

    # Finding 1: schedule() called nfl_data.fetch_csv, a function that did
    # not exist -- and every self-test before this one stubbed schedule()
    # itself, so the AttributeError was never once exercised. This block
    # stubs only the HTTP layer (nfl_data._get) and calls the real
    # schedule() and season_weekly(), which is the only way a missing
    # method on nfl_data would actually be caught.
    import gzip as _gzip

    games_csv = (
        "season,game_type,week,gameday,gametime,game_id,away_team,"
        "home_team,home_qb_id,home_qb_name,away_qb_id,away_qb_name,"
        "roof,stadium\n"
        "2026,REG,1,2026-09-09,20:15,2026_01_NE_SEA,NE,SEA,"
        "00-11,Home Passer,00-22,Away Passer,outdoors,Lumen Field\n"
    ).encode("utf-8")
    weekly_csv = (
        "player_id,player_display_name,position,position_group,team,"
        "opponent_team,season,week,season_type,game_id,passing_yards,"
        "rushing_yards,receiving_yards,passing_tds,rushing_tds,"
        "receiving_tds,attempts,carries,targets,receptions\n"
        "00-11,Home Passer,QB,QB,SEA,NE,2025,1,REG,2025_01_NE_SEA,"
        "300,10,0,2,0,0,35,2,0,0\n"
    ).encode("utf-8")
    urls = {"games.csv": "https://x.invalid/games.csv",
            "stats_player_week_2025.csv.gz": "https://x.invalid/wk25.csv.gz"}

    def stub_get(url, want_json=True):
        if url.startswith(nfl_data.RELEASES):
            if "page=1" in url:
                return [{"assets": [
                    {"name": name, "browser_download_url": link}
                    for name, link in urls.items()]}]
            return []
        if url == urls["games.csv"]:
            return games_csv
        if url == urls["stats_player_week_2025.csv.gz"]:
            return _gzip.compress(weekly_csv)
        return None

    real_http_get = nfl_data._get
    try:
        nfl_data._get = stub_get
        nfl_data._cache.clear()
        real_games = schedule(2026)
        assert len(real_games) == 1, real_games
        assert real_games[0]["home_team"] == "SEA", real_games[0]
        assert real_games[0]["game_id"] == "2026_01_NE_SEA", real_games[0]

        nfl_data._cache.clear()
        weekly_2025 = season_weekly(2025)
        assert len(weekly_2025) == 1, weekly_2025
        assert weekly_2025[0]["player_id"] == "00-11", weekly_2025[0]
        assert weekly_2025[0]["passing_yards"] == 300.0, weekly_2025[0]

        # 2026's file does not exist yet -- asset_urls() has no entry for
        # it, exactly like the real feed before week one is played.
        nfl_data._cache.clear()
        assert season_weekly(2026) == []
    finally:
        nfl_data._get = real_http_get
        nfl_data._cache.clear()

    print("nfl_yards self-test: the model holds and grades itself")


if __name__ == "__main__":
    _self_test()
