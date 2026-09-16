"""Strikeout-prop plumbing shared by the pitcher board.

What is left here is the part the pitcher board uses: name normalisation and
the per-event map of posted strikeout lines. The rules engine that used to
turn these into a separate set of posted plays is gone with the play card;
screen_rules and screen_config remain because the published rules page and
the season constant still read them.
"""
from __future__ import annotations

import unicodedata


MARKET = "pitcher_strikeouts"


def normalize(name: str) -> str:
    """'Tarik Skubal' -> 'tarik skubal', accents and punctuation stripped."""
    n = unicodedata.normalize("NFKD", str(name or ""))
    n = "".join(c for c in n if not unicodedata.combining(c))
    return " ".join(n.lower().replace(".", "").replace("'", "").split())


def lines_for_event(event: dict) -> dict:
    """{normalized pitcher: {line, over, under, over_book, under_book, books}}

    The number comes first: we find the point most books agree on for that
    pitcher, then take the best over and best under *at that number only*.
    Prices from other numbers are discarded rather than blended in.
    """
    books = find_plays._fresh_books(event.get("bookmakers") or [])
    by_player_point: dict[tuple, dict] = defaultdict(
        lambda: {"over": None, "under": None, "over_book": None,
                 "under_book": None, "over_key": None, "under_key": None,
                 "books": set()})
    points_seen: dict[str, Counter] = defaultdict(Counter)

    for book in books:
        market = next((m for m in book.get("markets", [])
                       if m.get("key") == MARKET), None)
        if not market:
            continue
        for o in market.get("outcomes", []):
            player = normalize(o.get("description"))
            point, price = o.get("point"), o.get("price")
            if not player or point is None or price is None:
                continue
            side = str(o.get("name", "")).lower()
            key = (player, float(point))
            points_seen[player][float(point)] += 1
            rec = by_player_point[key]
            rec["books"].add(book.get("key"))
            if side.startswith("over") and (rec["over"] is None or price > rec["over"]):
                rec["over"], rec["over_book"] = float(price), book.get("title")
                rec["over_key"] = book.get("key")
            elif side.startswith("under") and (rec["under"] is None or price > rec["under"]):
                rec["under"], rec["under_book"] = float(price), book.get("title")
                rec["under_key"] = book.get("key")

    out = {}
    for player, counter in points_seen.items():
        consensus_point = counter.most_common(1)[0][0]
        rec = by_player_point.get((player, consensus_point))
        if not rec:
            continue
        out[player] = {"line": consensus_point, **rec,
                       "books": len(rec["books"])}
    return out


GATE_PATTERNS = [
    ("missing ",              "missing data"),
    ("PA vs this roster",     "vs-roster sample too small"),
    ("vs-roster K%",          "vs-roster K% too low"),
    ("vs-roster AVG",         "vs-roster AVG too high"),
    ("vs-roster wOBA",        "vs-roster wOBA too high"),
    ("season K%",             "pitcher season K% too low"),
    ("K/9",                   "pitcher K/9 too low"),
    ("opponent K/game",       "opponent K/game"),
    ("fade",                  "on the fade list"),
    ("juice",                 "juice worse than allowed"),
    ("odds",                  "odds below the floor"),
    ("line",                  "line outside the allowed range"),
    ("daily cap",             "daily cap reached"),
    ("cap",                   "daily cap reached"),
]

