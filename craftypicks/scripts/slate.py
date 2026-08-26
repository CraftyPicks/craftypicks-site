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
import screen_mlb

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
    teams = screen_mlb.team_index(season)
    starters = {s["team_id"]: s for s in screen_mlb.probable_starters(date_str)}
    want_vs = getattr(config, "SLATE_VS_OPPONENT", True)
    if verbose:
        print(f"   slate: {len(results)} games of history, "
              f"{len(starters)} probable starters")

    rows = []
    for game in games:
        home_id = teams.get(str(game.get("home_team", "")).strip().lower())
        away_id = teams.get(str(game.get("away_team", "")).strip().lower())
        if not home_id or not away_id:
            continue

        def sp(team_id, opponent_id):
            s = starters.get(team_id)
            if not s:
                return {}, None, None
            stats = screen_mlb.pitcher_season(s["pitcher_id"], season)
            vs = None
            if want_vs:
                # Never allowed to break the board: this is a display extra.
                try:
                    vs = screen_mlb.pitcher_vs_team(s["pitcher_id"],
                                                    opponent_id, season)
                except Exception:                            # noqa: BLE001
                    vs = None
            return stats, s["name"], vs

        home_stats, home_name, home_vs = sp(home_id, away_id)
        away_stats, away_name, away_vs = sp(away_id, home_id)
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
            # Shown on the card, deliberately absent from the rating.
            "home_record": recs.get(home_id),
            "away_record": recs.get(away_id),
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
