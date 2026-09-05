"""Rate every game on today's board, and keep score of the ratings.

Two things happen here, and the second is the one that matters:

  1. Every MLB game today gets a win probability, published next to the
     market's own vig-free number so a reader can see where we disagree.
  2. Every rated game is stored and later graded, whether or not it became
     a play — which is what makes the numbers checkable in weeks instead of
     years. A card of two plays a day takes over a decade to prove anything.
     Fifteen rated games a day produces 450 data points a month.

Costs nothing extra: the odds board is already pulled for the scanner, and
everything from MLB is free.
"""
from __future__ import annotations

from datetime import datetime, timezone

import config
import find_plays
import odds_math as om
import rate_mlb
import mlb_api

SPORT = "baseball_mlb"


def market_probability(game: dict) -> dict | None:
    """The market's vig-free opinion of the home team, across all books."""
    books = find_plays._fresh_books(game.get("bookmakers") or [])
    home, away = game.get("home_team"), game.get("away_team")
    fairs, best_home, best_away = [], None, None
    for book in books:
        market = next((m for m in book.get("markets", [])
                       if m.get("key") == "h2h"), None)
        if not market:
            continue
        prices = {o.get("name"): o.get("price") for o in market.get("outcomes", [])
                  if o.get("price") is not None}
        if home not in prices or away not in prices:
            continue
        fh, _fa = om.devig_pair(prices[home], prices[away], config.DEVIG_METHOD)
        fairs.append(fh)
        if best_home is None or om.american_to_decimal(prices[home]) > om.american_to_decimal(best_home):
            best_home = float(prices[home])
        if best_away is None or om.american_to_decimal(prices[away]) > om.american_to_decimal(best_away):
            best_away = float(prices[away])
    if not fairs:
        return None
    fair = sum(fairs) / len(fairs)
    return {"market_home_prob": round(fair, 4), "books": len(fairs),
            "best_home_price": best_home, "best_away_price": best_away}


def _iso(us_date: str) -> str:
    """'09/01/2026' -> '2026-09-01'. The schedule wants one, standings the other."""
    month, day, year = us_date.split("/")
    return f"{year}-{month}-{day}"


def pair_starters(games: list[dict], teams: dict,
                  starters: list[dict]) -> dict:
    """Which starter belongs to which game, when a club plays twice.

    Keyed on the club alone -- which is what this replaces -- a doubleheader
    silently gave both games the same pitcher: the dict comprehension kept
    whichever row came last, so Cleveland's opener was drawn with the
    nightcap's starter and both cards carried the same win probability,
    because the rating reads his ERA.

    Start times are deliberately NOT compared for equality. The odds feed and
    the schedule disagree by a minute or two about the same game -- 2:11 PM
    against 2:10 PM on the day this was found. Both lists are sorted and
    paired in order instead, which is exact for a doubleheader and identical
    to the old behaviour for every single-game slate.

    Does not invent a pairing. A club with fewer announced starters than games
    leaves the later games unassigned, which draws a card with no pitcher
    rather than a card with the wrong one.
    """
    by_team: dict = {}
    for s in starters:
        by_team.setdefault(s["team_id"], []).append(s)
    for rows in by_team.values():
        rows.sort(key=lambda r: r.get("game_time") or "")

    games_by_team: dict = {}
    for i, g in enumerate(games):
        for side in ("home_team", "away_team"):
            tid = teams.get(str(g.get(side, "")).strip().lower())
            if tid:
                games_by_team.setdefault(tid, []).append(
                    (g.get("commence_time") or "", i))
    for rows in games_by_team.values():
        rows.sort()

    out: dict = {}
    for tid, rows in games_by_team.items():
        available = by_team.get(tid, [])
        for n, (_when, i) in enumerate(rows):
            if n < len(available):
                out[(i, tid)] = available[n]
    return out


def build(games: list[dict], date_str: str, season: int,
          verbose: bool = True) -> list[dict]:
    """One rated row per game on today's board."""
    if not games:
        return []

    results = rate_mlb.season_results(season)
    if not results:
        if verbose:
            print("   slate: no season results available, cannot rate")
        return []
    elo = rate_mlb.build_elo(results)
    recs = rate_mlb.records(results)
    teams = mlb_api.team_index(season)
    starter_rows = mlb_api.probable_starters(date_str)
    # The schedule's probablePitcher hydration carries no pitchHand, which is
    # why home_hand was an empty string on every card the board ever drew.
    # One /people call covers the whole slate.
    try:
        hands = mlb_api.pitch_hands(s["pitcher_id"] for s in starter_rows)
    except Exception:                                        # noqa: BLE001
        hands = {}
    for s_ in starter_rows:
        s_["hand"] = hands.get(s_["pitcher_id"], "")

    # Record, streak and last ten for all thirty clubs in one free request,
    # dated so the reader gets the table as it stood this morning rather than
    # one that already counts tonight.
    try:
        form = mlb_api.standings(season, _iso(date_str))
    except Exception:                                        # noqa: BLE001
        form = {}
    want_vs = getattr(config, "SLATE_VS_OPPONENT", True)
    if verbose:
        print(f"   slate: {len(results)} games of history, "
              f"{len(starter_rows)} probable starters")

    assigned = pair_starters(games, teams, starter_rows)

    rows = []
    for idx, game in enumerate(games):
        home_id = teams.get(str(game.get("home_team", "")).strip().lower())
        away_id = teams.get(str(game.get("away_team", "")).strip().lower())
        if not home_id or not away_id:
            continue

        def sp(team_id, opponent_id, _i=idx):
            s = assigned.get((_i, team_id))
            if not s:
                return {}, None, None, ""
            stats = mlb_api.pitcher_season(s["pitcher_id"], season)
            vs = None
            if want_vs:
                # Never allowed to break the board: this is a display extra.
                try:
                    vs = mlb_api.pitcher_vs_team(s["pitcher_id"],
                                                    opponent_id, season)
                except Exception:                            # noqa: BLE001
                    vs = None
            return stats, s["name"], vs, s.get("hand", "")

        home_stats, home_name, home_vs, home_hand = sp(home_id, away_id)
        away_stats, away_name, away_vs, away_hand = sp(away_id, home_id)

        # The season series, one free request per game and display-only, so
        # guarded exactly like the vs-opponent line above it. StatsAPI answers
        # in club ids and the stored-finals path answers in club names; this
        # is the one place that knows both, so the conversion happens here and
        # the renderer only ever sees names.
        try:
            raw_series = mlb_api.season_series(home_id, away_id, season,
                                               _iso(date_str))
        except Exception:                                    # noqa: BLE001
            raw_series = []
        name_of = {home_id: game.get("home_team"),
                   away_id: game.get("away_team")}
        series = [{"date": g["date"],
                   "away": name_of.get(g["away_id"], ""),
                   "away_runs": g["away_runs"],
                   "home": name_of.get(g["home_id"], ""),
                   "home_runs": g["home_runs"]}
                  for g in raw_series
                  if g["away_id"] in name_of and g["home_id"] in name_of]
        rating = rate_mlb.rate_game(elo, home_id, away_id, home_stats, away_stats)
        market = market_probability(game)

        row = {
            "event_id": game.get("id"),
            "date": date_str,
            "commence_time": game.get("commence_time"),
            "home": game.get("home_team"), "away": game.get("away_team"),
            "home_id": home_id, "away_id": away_id,
            "home_starter": home_name, "away_starter": away_name,
            "home_starter_era": home_stats.get("era"),
            "away_starter_era": away_stats.get("era"),
            # Display-only, like the club records beside it.
            "home_starter_wl": ([home_stats.get("w"), home_stats.get("l")]
                                if home_stats.get("w") is not None else None),
            "away_starter_wl": ([away_stats.get("w"), away_stats.get("l")]
                                if away_stats.get("w") is not None else None),
            "home_sp_innings": home_stats.get("innings"),
            "away_sp_innings": away_stats.get("innings"),
            "home_hand": home_hand, "away_hand": away_hand,
            # Shown on the card, deliberately absent from the rating.
            "home_record": recs.get(home_id),
            "away_record": recs.get(away_id),
            "home_form": form.get(home_id),
            "away_form": form.get(away_id),
            "series": series,
            "home_vs_opp": home_vs,
            "away_vs_opp": away_vs,
            "result": None,
            **rating,
        }
        if market:
            row.update(market)
            gap = round((rating["home_win_prob"] - market["market_home_prob"]) * 100, 1)
            row["disagreement"] = gap
            row["suspect"] = abs(gap) > rate_mlb.SUSPECT_DISAGREEMENT
        rows.append(row)

    rows.sort(key=lambda r: r.get("commence_time") or "")
    return rows


def grade(rated: list[dict], scores_by_id: dict) -> int:
    """Mark rated games with who actually won. Ratings are never edited."""
    graded = 0
    for row in rated:
        if row.get("result"):
            continue
        event = scores_by_id.get(row.get("event_id"))
        if not event or not event.get("completed"):
            continue
        s = event.get("scores") or {}
        if row["home"] not in s or row["away"] not in s:
            continue
        if s[row["home"]] == s[row["away"]]:
            # A suspended or tied game has no winner to score a probability
            # against. Leave it ungraded rather than quietly calling it away.
            continue
        row["result"] = "home" if s[row["home"]] > s[row["away"]] else "away"
        # Away–home, matching the "away @ home" order in the game column.
        row["final"] = f"{om._trim(s[row['away']])}–{om._trim(s[row['home']])}"
        row["graded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        graded += 1
    return graded


def summary(history: list[dict]) -> dict:
    """Calibration and Brier, plus how we compare to the market."""
    graded = [r for r in history if r.get("result")]
    with_market = [r for r in graded if r.get("market_home_prob") is not None]

    ours = rate_mlb.brier(graded)
    theirs = None
    if with_market:
        theirs = round(sum((r["market_home_prob"] -
                            (1.0 if r["result"] == "home" else 0.0)) ** 2
                           for r in with_market) / len(with_market), 4)
    return {
        "rated": len(history),
        "graded": len(graded),
        "calibration": rate_mlb.calibration(graded),
        "brier": ours,
        "market_brier": theirs,
        "market_compared": len(with_market),
    }


def _self_test() -> None:
    teams = {"cleveland guardians": 114, "detroit tigers": 116,
             "chicago cubs": 112}
    # The slate from the day the doubleheader bug was found.
    starters = [
        {"pitcher_id": 1, "name": "Logan Allen", "team_id": 114,
         "game_time": "2026-09-04T18:10:00Z"},
        {"pitcher_id": 2, "name": "Keider Montero", "team_id": 116,
         "game_time": "2026-09-04T18:10:00Z"},
        {"pitcher_id": 3, "name": "Foster Griffin", "team_id": 114,
         "game_time": "2026-09-04T23:15:00Z"},
        {"pitcher_id": 4, "name": "Andrew Sears", "team_id": 116,
         "game_time": "2026-09-04T23:15:00Z"},
    ]
    # The odds feed's times are a minute off the schedule's, and it listed the
    # nightcap first. Both are real; neither may change the pairing.
    games = [
        {"home_team": "Cleveland Guardians", "away_team": "Detroit Tigers",
         "commence_time": "2026-09-04T23:16:00Z"},
        {"home_team": "Cleveland Guardians", "away_team": "Detroit Tigers",
         "commence_time": "2026-09-04T18:11:00Z"},
    ]
    a = pair_starters(games, teams, starters)
    assert a[(1, 114)]["name"] == "Logan Allen", a[(1, 114)]
    assert a[(1, 116)]["name"] == "Keider Montero", a[(1, 116)]
    assert a[(0, 114)]["name"] == "Foster Griffin", a[(0, 114)]
    assert a[(0, 116)]["name"] == "Andrew Sears", a[(0, 116)]

    # A single-game slate must behave exactly as it did before.
    one = pair_starters(
        [{"home_team": "Cleveland Guardians", "away_team": "Chicago Cubs",
          "commence_time": "2026-09-04T18:11:00Z"}], teams, starters[:1])
    assert one[(0, 114)]["name"] == "Logan Allen", one

    # One announced starter across two games leaves the later one unassigned.
    # A card with no pitcher is honest; a card with the wrong one is not.
    short = pair_starters(games, teams, [starters[0]])
    assert (1, 114) in short and (0, 114) not in short, short

    # A club the team index does not recognise is skipped, not crashed on.
    assert pair_starters(
        [{"home_team": "Nowhere Nine", "away_team": "Nobody",
          "commence_time": "2026-09-04T18:11:00Z"}], teams, starters) == {}

    print("slate self-test: every game gets its own starter")


if __name__ == "__main__":
    _self_test()
