"""Pitcher prop scanning.

Props differ from sides in two ways that matter:

  * They live on a per-event endpoint, one game at a time, and cost a credit
    per market per event. On the free tier that limits us to a handful of
    games a day — see PROP_MAX_EVENTS.
  * A single prop market contains many players. Outcomes carry a
    `description` holding the player name, so Over/Under pairs have to be
    matched on player AND number. Pairing them the way we pair sides would
    de-vig one pitcher's over against a different pitcher's under and
    manufacture nonsense.

The value method is otherwise identical: de-vig each book's pair, average
across the others, and look for a book out of line with that consensus.
"""
from __future__ import annotations

from collections import defaultdict

import config
import find_plays
import odds_math as om

PROP_LABEL = {
    "pitcher_strikeouts": "Strikeouts",
    "pitcher_outs": "Outs recorded",
    "pitcher_hits_allowed": "Hits allowed",
    "pitcher_earned_runs": "Earned runs",
    "pitcher_walks": "Walks",
}


def scan_event(event: dict, market_key: str) -> list[dict]:
    """Every qualifying prop edge in one game, for one market."""
    books = find_plays._fresh_books(event.get("bookmakers") or [])
    if len(books) < getattr(config, "PROP_MIN_BOOKS", 4):
        return []

    # (player, point) -> list of (book_key, book_title, over_price, under_price)
    quotes: dict[tuple, list] = defaultdict(list)
    for book in books:
        market = next((m for m in book.get("markets", [])
                       if m.get("key") == market_key), None)
        if not market:
            continue
        by_player: dict[tuple, dict] = defaultdict(dict)
        for outcome in market.get("outcomes", []):
            player = outcome.get("description")
            point = outcome.get("point")
            price = outcome.get("price")
            if not player or point is None or price is None:
                continue
            side = str(outcome.get("name", "")).lower()
            if side.startswith("over"):
                by_player[(player, float(point))]["over"] = float(price)
            elif side.startswith("under"):
                by_player[(player, float(point))]["under"] = float(price)
        for key, pair in by_player.items():
            if "over" in pair and "under" in pair:
                quotes[key].append(
                    (book.get("key", ""), book.get("title", ""), pair["over"], pair["under"]))

    results = []
    for (player, point), offers in quotes.items():
        if len(offers) < getattr(config, "PROP_MIN_BOOKS", 4):
            continue
        fair_over, fair_under = [], []
        for _bk, _bt, over, under in offers:
            fo, fu = om.devig_pair(over, under, config.DEVIG_METHOD)
            fair_over.append(fo)
            fair_under.append(fu)

        for side_name, fairs, idx in (("Over", fair_over, 2), ("Under", fair_under, 3)):
            book_key, book_title, best_price = None, None, None
            best_dec = 0.0
            for offer in offers:
                dec = om.american_to_decimal(offer[idx])
                if dec > best_dec:
                    best_dec, best_price = dec, offer[idx]
                    book_key, book_title = offer[0], offer[1]
            if best_price is None:
                continue
            if not (config.MIN_PRICE <= best_price <= config.MAX_PRICE):
                continue
            others = [f for f, o in zip(fairs, offers) if o[0] != book_key]
            if len(others) < getattr(config, "PROP_MIN_BOOKS", 4) - 1:
                continue
            fair = sum(others) / len(others)
            edge = om.expected_value_pct(fair, best_price)
            if edge < getattr(config, "PROP_MIN_EDGE_PCT", 3.0) or edge > config.MAX_EDGE_PCT:
                continue

            label = PROP_LABEL.get(market_key, market_key)
            results.append({
                "event_id": event.get("id"),
                "sport_key": event.get("sport_key", ""),
                "league": find_plays.league_of(event.get("sport_key", "")),
                "league_short": find_plays.league_short(event.get("sport_key", "")),
                "commence_time": event.get("commence_time"),
                "home_team": event.get("home_team"), "away_team": event.get("away_team"),
                "matchup": f"{event.get('away_team')} @ {event.get('home_team')}",
                "market": market_key,
                "market_label": f"{label} prop",
                "side": f"{player} {side_name}",
                "player": player,
                "point": point,
                "price": int(round(best_price)),
                "book": book_title, "book_key": book_key,
                "fair_prob": round(fair, 5),
                "fair_price": om.prob_to_american(fair),
                "edge_pct": round(edge, 2),
                "books_counted": len(offers),
                "books_shorter": sum(
                    1 for o in offers
                    if om.american_to_decimal(o[idx]) < om.american_to_decimal(best_price)),
                "stake": config.STAKE_UNITS,
                "pick": f"{player} {side_name.lower()} {om._trim(point)} {label.lower()}",
                "is_prop": True,
            })
            results[-1]["reasons"] = reasons_for(results[-1])
    return results


def reasons_for(play: dict) -> list[str]:
    return [
        f"Vig-free consensus across <b>{play['books_counted']} books</b> is "
        f"{om.format_american(play['fair_price'])}",
        f"Best number on the board is <b>{om.format_american(play['price'])} "
        f"at {play['book']}</b>",
        f"<b>{play['books_shorter']} of {play['books_counted']}</b> books price "
        "this shorter than we're getting it",
        f"Expected value at that price: <b>+{play['edge_pct']:.1f}%</b> per unit risked",
    ]


def pick_events(games: list[dict], limit: int) -> list[dict]:
    """Which games to spend prop credits on.

    Earliest starts first — those are the ones a reader can still act on by
    the time they read the card, and it's a rule that can't be accused of
    cherry-picking after the fact.
    """
    ordered = sorted(games, key=lambda g: g.get("commence_time") or "")
    return ordered[:limit]
