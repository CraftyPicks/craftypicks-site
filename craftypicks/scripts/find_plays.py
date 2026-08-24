"""Turn a pile of raw odds into a short card of plays.

For every two-way market we:
  * find the point (spread/total) that most books agree on,
  * de-vig each book's pair of prices to get that book's honest probability,
  * average those across the other books to get a consensus fair probability,
  * measure what the best available price on the board is worth against it.

A play is posted only when that gap clears MIN_EDGE_PCT. Everything else is
noise, and noise is what turns a card into a losing month.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

import config
import odds_math as om

MARKET_LABEL = {"h2h": "Moneyline", "spreads": "Spread", "totals": "Total"}


def league_of(sport_key: str) -> str:
    parent = config.LEAGUE_ALIASES.get(sport_key, sport_key)
    return config.LEAGUES.get(parent, {}).get("label", parent)


def league_short(sport_key: str) -> str:
    parent = config.LEAGUE_ALIASES.get(sport_key, sport_key)
    return config.LEAGUES.get(parent, {}).get("short", parent)


def find_candidates(games: list[dict]) -> list[dict]:
    """Every qualifying edge across every game, unsorted."""
    out = []
    for game in games:
        books = game.get("bookmakers") or []
        if len(books) < config.MIN_BOOKS:
            continue
        for market_key in config.MARKETS:
            out.extend(_scan_market(game, books, market_key))
    return out


def _scan_market(game: dict, books: list[dict], market_key: str) -> list[dict]:
    # Gather each book's two-sided quote for this market.
    quotes: list[tuple[str, str, dict, dict]] = []   # (book_key, book_title, side_a, side_b)
    points: Counter = Counter()
    for book in books:
        market = next((m for m in book.get("markets", []) if m.get("key") == market_key), None)
        if not market:
            continue
        outcomes = [o for o in market.get("outcomes", []) if o.get("price") is not None]
        if len(outcomes) != 2:
            continue
        quotes.append((book.get("key", ""), book.get("title", ""), outcomes[0], outcomes[1]))
        if market_key != "h2h":
            pt = outcomes[0].get("point")
            if pt is not None:
                points[abs(float(pt))] += 1

    if len(quotes) < config.MIN_BOOKS:
        return []

    # For spreads/totals, only compare books sitting on the same number.
    consensus_point = None
    if market_key != "h2h":
        if not points:
            return []
        consensus_point = points.most_common(1)[0][0]
        quotes = [
            q for q in quotes
            if q[2].get("point") is not None
            and abs(abs(float(q[2]["point"])) - consensus_point) < 1e-9
        ]
        if len(quotes) < config.MIN_BOOKS:
            return []

    # De-vig every book's pair, keyed by outcome name.
    fair_by_side: dict[str, list[float]] = defaultdict(list)
    prices_by_side: dict[str, list[tuple[str, str, float, float | None]]] = defaultdict(list)
    for book_key, book_title, a, b in quotes:
        fa, fb = om.devig_pair(a["price"], b["price"])
        for outcome, fair in ((a, fa), (b, fb)):
            name = outcome["name"]
            fair_by_side[name].append(fair)
            prices_by_side[name].append(
                (book_key, book_title, float(outcome["price"]), outcome.get("point"))
            )

    results = []
    for side, fairs in fair_by_side.items():
        offers = prices_by_side[side]
        if len(offers) < config.MIN_BOOKS:
            continue
        # Best price on the board for this side.
        book_key, book_title, price, point = max(
            offers, key=lambda o: om.american_to_decimal(o[2])
        )
        if not (config.MIN_PRICE <= price <= config.MAX_PRICE):
            continue
        # Consensus excludes the book we'd be betting — otherwise the outlier
        # drags the "fair" price toward itself and manufactures an edge.
        others = [
            f for f, o in zip(fairs, offers) if o[0] != book_key
        ]
        if len(others) < config.MIN_BOOKS - 1:
            continue
        fair_prob = sum(others) / len(others)
        edge = om.expected_value_pct(fair_prob, price)
        if edge < config.MIN_EDGE_PCT:
            continue

        shorter = sum(
            1 for _, _, p, _ in offers if om.american_to_decimal(p) < om.american_to_decimal(price)
        )
        results.append({
            "event_id": game.get("id"),
            "sport_key": game.get("sport_key", ""),
            "league": league_of(game.get("sport_key", "")),
            "league_short": league_short(game.get("sport_key", "")),
            "commence_time": game.get("commence_time"),
            "home_team": game.get("home_team"),
            "away_team": game.get("away_team"),
            "matchup": f"{game.get('away_team')} @ {game.get('home_team')}",
            "matchup_short": f"{_nickname(game.get('away_team'))} / {_nickname(game.get('home_team'))}",
            "market": market_key,
            "market_label": MARKET_LABEL.get(market_key, market_key),
            "side": side,
            "point": float(point) if point is not None else None,
            "price": int(round(price)),
            "book": book_title,
            "book_key": book_key,
            "fair_prob": round(fair_prob, 5),
            "fair_price": om.prob_to_american(fair_prob),
            "edge_pct": round(edge, 2),
            "books_counted": len(offers),
            "books_shorter": shorter,
            "stake": config.STAKE_UNITS,
        })
    return results


def build_card(candidates: list[dict]) -> list[dict]:
    """Rank, thin out, and label the plays that make today's card."""
    ranked = sorted(candidates, key=lambda c: c["edge_pct"], reverse=True)
    card: list[dict] = []
    per_league: Counter = Counter()
    seen_events: set[tuple] = set()

    for cand in ranked:
        if len(card) >= config.MAX_PLAYS_PER_DAY:
            break
        # One play per game, full stop. Two plays on the same event is
        # correlated risk dressed up as diversification.
        key = cand["event_id"]
        if key in seen_events:
            continue
        if per_league[cand["league"]] >= config.MAX_PLAYS_PER_LEAGUE:
            continue
        seen_events.add(key)
        per_league[cand["league"]] += 1
        cand["pick"] = _pick_label(cand)
        cand["reasons"] = _reasons(cand)
        card.append(cand)

    card.sort(key=lambda c: (c.get("commence_time") or "", -c["edge_pct"]))
    for i, play in enumerate(card, 1):
        play["slot"] = i
        play["id"] = f"{play['event_id']}-{play['market']}-{play['side']}".replace(" ", "_")
    return card


def _nickname(team: str | None) -> str:
    """'Cleveland Guardians' -> 'Guardians'. Keeps play labels short."""
    if not team:
        return ""
    parts = str(team).split()
    return parts[-1] if len(parts) > 1 else str(team)


def _pick_label(play: dict) -> str:
    side, market, point = play["side"], play["market"], play["point"]
    if market == "h2h":
        return f"{_nickname(side)} ML"
    if market == "spreads":
        return f"{_nickname(side)} {om.format_point(point)}"
    letter = "o" if side.lower().startswith("over") else "u"
    return f"{play['matchup_short']} {letter}{om._trim(abs(point))}"


def _reasons(play: dict) -> list[str]:
    fair = om.format_american(play["fair_price"])
    price = om.format_american(play["price"])
    pct = f"{play['fair_prob'] * 100:.1f}%"
    reasons = [
        f"Vig-free consensus across <b>{play['books_counted']} books</b> is {fair} ({pct} to win)",
        f"Best number on the board is <b>{price} at {play['book']}</b>",
        f"<b>{play['books_shorter']} of {play['books_counted']}</b> books price this shorter than we're getting it",
        f"Expected value at that price: <b>+{play['edge_pct']:.1f}%</b> per unit risked",
    ]
    if play["market"] != "h2h":
        reasons.insert(2, f"Consensus number is {om._trim(abs(play['point']))} — books off that number were excluded")
    return reasons[:4]


def summarize(card: list[dict]) -> dict:
    by_league = Counter(p["league"] for p in card)
    return {
        "count": len(card),
        "units_risked": round(sum(p["stake"] for p in card), 2),
        "by_league": dict(by_league),
        "avg_edge": round(sum(p["edge_pct"] for p in card) / len(card), 2) if card else 0.0,
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
