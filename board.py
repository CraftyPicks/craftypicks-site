#!/usr/bin/env python3
"""Price every game on the board, not only the ones worth betting."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config    # noqa: E402
import fair      # noqa: E402
import leagues   # noqa: E402

# Which outcome is side "a" for each market. Fixing this once is what lets
# every consumer read fair_a as "the home team" without asking.
#   h2h/spreads — a is the home team, b is the away team
#   totals      — a is the over, b is the under
SIDE_A_TOTALS = "over"

# The play-picker's book floor is a betting gate. A visitor-facing board
# still needs two books so a single quote cannot invent a market, but it
# cannot inherit the six-book floor or half the slate would vanish.
BOARD_MIN_BOOKS = 2


def _outcomes(game: dict, book: dict, market: str) -> list[dict] | None:
    for m in book.get("markets") or []:
        if m.get("key") == market:
            return m.get("outcomes") or []
    return None


def quotes_for(game: dict, market: str) -> tuple[list[dict], float | None]:
    """One market projected into fair.py's flat quote shape.

    For spreads and totals the books do not all hang the same number, so the
    modal line is chosen and only the books quoting it are returned. Devigging
    a -1.5 against a -2.5 produces a fair price for a market nobody offers,
    which is worse than no price at all.

    Deliberately does not fall back to a nearby line when a book is off the
    modal number. A book quoting a different line is evidence about a
    different market; borrowing it would quietly widen the sample with the
    wrong data.
    """
    home, away = game.get("home_team"), game.get("away_team")
    if market == "totals":
        want_a, want_b = "over", "under"
    else:
        want_a, want_b = home, away

    raw = []
    for book in game.get("bookmakers") or []:
        outcomes = _outcomes(game, book, market)
        if not outcomes:
            continue
        by_name = {}
        for o in outcomes:
            name = (o.get("name") or "")
            by_name[name.lower() if market == "totals" else name] = o
        a = by_name.get(want_a.lower() if market == "totals" else want_a)
        b = by_name.get(want_b.lower() if market == "totals" else want_b)
        if not a or not b:
            continue
        if a.get("price") is None or b.get("price") is None:
            continue
        raw.append({
            "book": book.get("title") or book.get("key") or "",
            "price_a": int(a["price"]),
            "price_b": int(b["price"]),
            "point": a.get("point"),
        })

    if market == "h2h":
        return [{k: q[k] for k in ("book", "price_a", "price_b")}
                for q in raw], None

    points = [q["point"] for q in raw if q["point"] is not None]
    if not points:
        return [], None
    modal = Counter(points).most_common(1)[0][0]
    kept = [{k: q[k] for k in ("book", "price_a", "price_b")}
            for q in raw if q["point"] == modal]
    return kept, modal


def _price_market(quotes: list[dict]) -> dict | None:
    """fair.price_market with the board's own book floor.

    Does not change config.MIN_BOOKS for the rest of the process. The daily
    job imports both find_plays and board; leaking a lower floor into the
    play picker would put thin markets on the card.
    """
    saved = config.MIN_BOOKS
    config.MIN_BOOKS = BOARD_MIN_BOOKS
    try:
        return fair.price_market(quotes)
    finally:
        config.MIN_BOOKS = saved


def price_game(game: dict, short: str) -> dict | None:
    """Every market of one game, priced, or None if nothing could be priced.

    A game reaches the board only if at least one market cleared
    BOARD_MIN_BOOKS. Showing a game with no number on it invites the reader
    to supply their own, which is the opposite of what this page is for.

    Does not rate the game. The model's win probability is merged in later by
    whatever knows that league's ratings; this function only reads the market.
    """
    markets: dict[str, dict] = {}
    for market in config.MARKETS:
        quotes, point = quotes_for(game, market)
        priced = _price_market(quotes)
        if not priced:
            continue
        entry = {
            "point": point,
            "fair_home": priced["fair_a"],
            "fair_away": priced["fair_b"],
            "fair_price_home": priced["fair_price_a"],
            "fair_price_away": priced["fair_price_b"],
            "best_home": priced["best_a"],
            "best_away": priced["best_b"],
            "edge_home": priced["edge_a"],
            "edge_away": priced["edge_b"],
            # Books hanging this line, not the consensus-after-exclusion
            # count fair.py reports. The card says "{n} books".
            "books": len(quotes),
            "width": priced["width"],
        }
        if market == "totals":
            # There is no scoring model. Elo gives a win probability, not a
            # run distribution, so this stays None until one exists and is
            # validated. See the spec: the row reads "market only".
            entry["model"] = None
        markets[market] = entry

    if not markets:
        return None

    return {
        "event_id": game.get("id"),
        "league": short,
        "commence_time": game.get("commence_time"),
        "home": game.get("home_team"),
        "away": game.get("away_team"),
        "markets": markets,
        "model": None,
    }


def build(games: list[dict], short: str) -> list[dict]:
    """Every priceable game in one league, in start-time order.

    Does not filter by edge, price or book count beyond what pricing itself
    requires. This is a board: a game the site would never bet is exactly as
    interesting as one it would, and leaving it out is how a tipster site
    hides its misses.
    """
    rows = [r for r in (price_game(g, short) for g in games) if r]
    rows.sort(key=lambda r: (r.get("commence_time") or "", r.get("home") or ""))
    return rows


def document(boards: dict[str, list[dict]], generated_at: str,
             date: str) -> dict:
    """The whole board as one JSON-serialisable document.

    Leagues with no games are omitted rather than written empty, so a page can
    ask whether a league is on tonight by asking whether it is present.

    Does not embed the ratings or the schedule for leagues that are out of
    season; an absent league means no games today, not an error.
    """
    out = {}
    for short in leagues.ORDER:
        rows = boards.get(short) or []
        if not rows:
            continue
        out[short] = {"label": leagues.LEAGUES[short].label, "games": rows}
    return {
        "generated_at": generated_at,
        "date": date,
        "leagues": out,
        "counts": {short: len(v["games"]) for short, v in out.items()},
    }


def _self_test() -> None:
    # A three-book moneyline where one book is clearly the best price.
    game = {
        "id": "evt1", "sport_key": "baseball_mlb",
        "commence_time": "2026-08-31T23:05:00Z",
        "home_team": "Milwaukee Brewers", "away_team": "Chicago Cubs",
        "bookmakers": [
            {"key": "fanduel", "title": "FanDuel", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Milwaukee Brewers", "price": -130},
                    {"name": "Chicago Cubs", "price": 110}]},
                {"key": "spreads", "outcomes": [
                    {"name": "Milwaukee Brewers", "price": 130, "point": -1.5},
                    {"name": "Chicago Cubs", "price": -155, "point": 1.5}]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -105, "point": 8.5},
                    {"name": "Under", "price": -115, "point": 8.5}]}]},
            {"key": "draftkings", "title": "DraftKings", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Milwaukee Brewers", "price": -128},
                    {"name": "Chicago Cubs", "price": 108}]},
                {"key": "spreads", "outcomes": [
                    {"name": "Milwaukee Brewers", "price": 134, "point": -1.5},
                    {"name": "Chicago Cubs", "price": -160, "point": 1.5}]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -108, "point": 8.5},
                    {"name": "Under", "price": -112, "point": 8.5}]}]},
            {"key": "caesars", "title": "Caesars", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Milwaukee Brewers", "price": -125},
                    {"name": "Chicago Cubs", "price": 114}]},
                # Caesars hangs a different total. It must not be devigged
                # against the other two — that would price a market nobody
                # is offering.
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -110, "point": 9.5},
                    {"name": "Under", "price": -110, "point": 9.5}]}]},
        ],
    }

    quotes, point = quotes_for(game, "h2h")
    assert point is None, "a moneyline has no line to hang"
    assert len(quotes) == 3, quotes
    assert quotes[0]["book"] == "FanDuel", "the display title, not the key"
    assert quotes[0]["price_a"] == -130 and quotes[0]["price_b"] == 110, \
        "side a is the home team"

    # The modal total is 8.5 (two books); Caesars' 9.5 is excluded.
    tq, tpoint = quotes_for(game, "totals")
    assert tpoint == 8.5, tpoint
    assert len(tq) == 2, "only the books hanging the modal line are priced"
    assert tq[0]["price_a"] == -105, "side a is the over"

    # Only two books post a spread, and both hang -1.5.
    sq, spoint = quotes_for(game, "spreads")
    assert spoint == -1.5, "the line is quoted from the home team's side"
    assert len(sq) == 2

    # A market no book posts yields nothing rather than raising.
    bare = {"id": "e", "home_team": "A", "away_team": "B", "bookmakers": []}
    assert quotes_for(bare, "h2h") == ([], None)

    row = price_game(game, "mlb")
    assert row is not None
    assert row["event_id"] == "evt1"
    assert row["league"] == "mlb"
    assert row["home"] == "Milwaukee Brewers"
    assert set(row["markets"]) <= {"h2h", "spreads", "totals"}

    ml = row["markets"]["h2h"]
    assert ml["best_home"]["book"] == "Caesars", \
        "-125 is the best price on the home side"
    assert 0.0 < ml["fair_home"] < 1.0
    assert abs(ml["fair_home"] + ml["fair_away"] - 1.0) < 1e-9, \
        "a two-way market's fair probabilities sum to 1"
    assert ml["books"] == 3

    tot = row["markets"]["totals"]
    assert tot["point"] == 8.5
    assert tot["books"] == 2, "Caesars hung 9.5 and is not counted"
    assert tot["model"] is None, \
        "there is no scoring model; a total must never carry our own number"

    # A game with too few books to price at all is dropped from the board
    # rather than shown with an invented number.
    thin = dict(game, id="evt2", bookmakers=game["bookmakers"][:1])
    assert price_game(thin, "mlb") is None

    rows = build([game, thin], "mlb")
    assert len(rows) == 1, "only the priceable game reaches the board"

    doc = document({"mlb": rows}, "2026-08-31T13:00:00", "2026-08-31")
    assert doc["date"] == "2026-08-31"
    assert doc["leagues"]["mlb"]["label"] == "MLB"
    assert doc["leagues"]["mlb"]["games"][0]["event_id"] == "evt1"
    assert doc["counts"]["mlb"] == 1

    print("board self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
