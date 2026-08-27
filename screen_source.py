"""Turn the strikeout screens into Craftypicks plays.

This is the bridge between the V2.2 screen system and the site. Three
things worth knowing about how it's wired:

  * It reuses the per-event prop odds the scanner already pulled. Screens
    cost ZERO extra API credits — they see whichever games props were
    fetched for, and no others. Widen PROP_MAX_EVENTS to widen their view.

  * Lines and prices are matched per player AND per number. The original
    odds.py kept the best over and best under independently while
    overwriting a shared `line`, so a 5.5 under price could end up filed
    under a 6.5 line — a bet no book was offering.

  * Every play is tagged source="screen", so the record can report its
    closing-line value separately from the price-based scanner's. That
    comparison is the whole point of running both.
"""
from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict

import find_plays
import odds_math as om
import screen_config as scfg
import screen_mlb
from screen_models import Candidate
from screen_rules import evaluate_all

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


def consensus(event: dict, player: str, point: float, side: str,
              exclude_book: str | None = None) -> float | None:
    """Vig-free market probability for this pitcher's over/under at `point`."""
    books = find_plays._fresh_books(event.get("bookmakers") or [])
    fairs = []
    for book in books:
        if exclude_book and book.get("key") == exclude_book:
            continue
        market = next((m for m in book.get("markets", [])
                       if m.get("key") == MARKET), None)
        if not market:
            continue
        pair = {}
        for o in market.get("outcomes", []):
            if normalize(o.get("description")) != player:
                continue
            if o.get("point") is None or abs(float(o["point"]) - point) > 1e-9:
                continue
            nm = str(o.get("name", "")).lower()
            if nm.startswith("over"):
                pair["over"] = float(o["price"])
            elif nm.startswith("under"):
                pair["under"] = float(o["price"])
        if "over" in pair and "under" in pair:
            fo, fu = om.devig_pair(pair["over"], pair["under"], scfg_devig())
            fairs.append(fo if side == "OVER" else fu)
    return (sum(fairs) / len(fairs)) if fairs else None


def scfg_devig() -> str:
    import config
    return getattr(config, "DEVIG_METHOD", "power")


def build_plays(prop_events: list[dict], date_str: str, verbose: bool = True) -> list[dict]:
    """Run the screens over the games we already have prop odds for."""
    if not prop_events:
        return []

    starters = screen_mlb.probable_starters(date_str)
    if not starters:
        if verbose:
            print("   screens: no probable starters listed")
        return []
    by_name = {normalize(s["name"]): s for s in starters}

    candidates, event_of = [], {}
    for event in prop_events:
        for player, quote in lines_for_event(event).items():
            starter = by_name.get(player)
            if not starter:
                continue
            season_stats = screen_mlb.pitcher_season(starter["pitcher_id"], scfg.SEASON)
            opp_k = screen_mlb.team_k_per_game(starter["opponent_id"], scfg.SEASON)

            cand = Candidate(
                pitcher_id=starter["pitcher_id"], name=starter["name"],
                team=starter["team"], opponent=starter["opponent"],
                game_time=starter.get("game_time", ""),
                k_pct=season_stats["k_pct"], k_per_9=season_stats["k_per_9"],
                innings=season_stats["innings"], opp_k_per_game=opp_k,
                line=quote["line"], over_odds=_int(quote["over"]),
                under_odds=_int(quote["under"]),
                book=quote.get("over_book") or quote.get("under_book") or "",
            )
            # vs_roster is one request per batter, so only pay for it when the
            # cheap gates are already satisfied — same gating as the original.
            # This pre-gate exists only to avoid a per-batter fetch for
            # pitchers no screen could take. It must therefore be looser than
            # every screen — reading the config rather than repeating its
            # numbers, or loosening a threshold there would silently starve
            # the roster data and show up as "missing" instead of a play.
            min_k = min(s["min_pitcher_k_pct"] for s in
                        (scfg.SCREEN_A, scfg.SCREEN_B))
            min_opp = min(scfg.SCREEN_A["min_opp_k_per_game"],
                          scfg.SCREEN_B["min_opp_k_per_game"])
            needs_roster = (cand.k_pct is not None and cand.k_pct >= min_k
                            and opp_k is not None and opp_k >= min_opp)
            if needs_roster:
                cand.vs_roster = screen_mlb.vs_roster(
                    starter["pitcher_id"], starter["opponent_id"], scfg.SEASON)
            candidates.append(cand)
            event_of[cand.pitcher_id] = (event, player, quote)

    if not candidates:
        if verbose:
            print("   screens: no starters matched the posted strikeout lines")
        return []

# Every rejection reason the rules can produce, mapped to the gate that
# produced it. Counting these is the only way to know which threshold is
# actually costing plays — guessing at it once already cost a day of tuning
# the wrong knob.
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


def gate_of(reason: str) -> str:
    text = str(reason)
    for needle, label in GATE_PATTERNS:
        if needle in text:
            return label
    return "other"


def report_gates(rejections) -> None:
    """Which gate stopped how many, worst offender first."""
    from collections import Counter
    counts = Counter(gate_of(reason) for _c, _s, reason in rejections)
    for label, n in counts.most_common():
        print(f"      gate — {label}: {n}")

    # For the sample gate specifically, how close were they? A wall of
    # "28 PA, needed 30" is a different problem from "3 PA, needed 30".
    shortfalls = []
    for cand, _screen, reason in rejections:
        if "PA vs this roster" in str(reason):
            pa = getattr(getattr(cand, "vs_roster", None), "pa", None)
            if pa is not None:
                shortfalls.append((pa, cand.name))
    if shortfalls:
        shortfalls.sort(reverse=True)
        best = ", ".join(f"{n} ({pa} PA)" for pa, n in shortfalls[:4])
        print(f"      closest on sample: {best}")


    plays, rejections = evaluate_all(candidates)
    if verbose:
        print(f"   screens: {len(candidates)} starters evaluated, {len(plays)} play(s)")
        report_gates(rejections)
        for cand, screen, reason in rejections[:6]:
            print(f"      [{screen}] {cand.name}: {reason}")

    out = []
    for play in plays:
        event, player, quote = event_of[play.candidate.pitcher_id]
        book = quote["over_book"] if play.side == "OVER" else quote["under_book"]
        book_key = quote["over_key"] if play.side == "OVER" else quote["under_key"]
        fair = consensus(event, player, play.line, play.side, exclude_book=book_key)
        edge = om.expected_value_pct(fair, play.odds) if fair is not None else None

        out.append({
            "event_id": event.get("id"),
            "sport_key": event.get("sport_key", "baseball_mlb"),
            "league": "MLB", "league_short": "mlb",
            "commence_time": event.get("commence_time"),
            "home_team": event.get("home_team"), "away_team": event.get("away_team"),
            "matchup": f"{event.get('away_team')} @ {event.get('home_team')}",
            "market": MARKET, "market_label": f"Strikeouts · Screen {play.screen}",
            "side": f"{play.candidate.name} {play.side.title()}",
            "player": play.candidate.name,
            "point": play.line, "price": int(play.odds),
            "book": book, "book_key": book_key,
            "fair_prob": round(fair, 5) if fair is not None else None,
            "fair_price": om.prob_to_american(fair) if fair is not None else None,
            "edge_pct": round(edge, 2) if edge is not None else 0.0,
            "books_counted": quote.get("books", 0),
            "stake": 1.0,
            "pick": f"{play.candidate.name} {play.side.lower()} "
                    f"{om._trim(play.line)} strikeouts",
            "reasons": [f"<b>Screen {play.screen}</b> — {r}" for r in play.reasons],
            "is_prop": True,
            "source": scfg.SOURCE_TAG,
            "screen": play.screen,
        })
    return out


def _int(value):
    return int(round(float(value))) if value is not None else None
