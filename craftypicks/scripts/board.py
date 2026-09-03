#!/usr/bin/env python3
"""Price every game on the board, not only the ones worth betting."""
from __future__ import annotations

import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config    # noqa: E402
import fair      # noqa: E402
import form_store # noqa: E402
import leagues   # noqa: E402
import rate_mlb  # noqa: E402
import ratings   # noqa: E402

# Which outcome is side "a" for each market:
#   h2h/spreads — a is the home team, b is the away team
#   totals      — a is the over, b is the under
# Side A is NOT the home team everywhere: on a total it is the over, and the
# fair_home/fair_away keys below are named for the h2h/spreads case only.
# Every market entry therefore carries an explicit "side_a" so a consumer can
# read the orientation off the data instead of guessing from the key names.
SIDE_A = {"h2h": "home", "spreads": "home", "totals": "over"}

# The play-picker's book floor is a betting gate. A visitor-facing board
# cannot inherit the six-book floor or half the slate would vanish, but it
# cannot go below three either: each side's consensus excludes the book
# holding that side's best price, so two quotes leave a one-book "consensus"
# on a card that still says "2 books". Three is the smallest floor that puts
# at least two books behind every benchmark.
BOARD_MIN_BOOKS = 3


def _outcomes(game: dict, book: dict, market: str) -> list[dict] | None:
    for m in book.get("markets") or []:
        if m.get("key") == market:
            return m.get("outcomes") or []
    return None


def _modal_point(points: list[float]) -> float:
    """The line most books hang, chosen the same way on every run.

    Counter.most_common breaks a tie by insertion order, which here is the
    API's bookmaker order — so four books at 8.5/9.5/9.5/8.5 returned 8.5 or
    9.5 depending on how the feed happened to be sorted, and the whole board
    flipped between runs. A 2-2 tie on totals is common. Ties go to the line
    closest to the median of every quoted point, and to the lower point if
    that is still tied.
    """
    counts = Counter(points)
    top = max(counts.values())
    tied = [p for p in counts if counts[p] == top]
    if len(tied) == 1:
        return tied[0]
    median = statistics.median(points)
    return min(tied, key=lambda p: (abs(p - median), p))


def _points_agree(market: str, a_point, b_point) -> bool:
    """Do the two sides of this book's quote describe the same line?"""
    if a_point is None or b_point is None:
        return False
    if market == "totals":
        return b_point == a_point
    return b_point == -a_point


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
        if not home or not away:
            return [], None
        want_a, want_b = home, away

    raw = []
    for book in game.get("bookmakers") or []:
        outcomes = _outcomes(game, book, market)
        if not outcomes:
            continue
        by_name = {}
        duplicate = False
        for o in outcomes:
            name = (o.get("name") or "")
            key = name.lower() if market == "totals" else name
            if key in by_name:
                # The same outcome name twice means this payload carries
                # alternate lines. An alternate line is a different market,
                # and keeping the last pair silently discards the book's
                # honest main line — enough to swing the modal line and drop
                # the market entirely. Skip the book instead.
                duplicate = True
                break
            by_name[key] = o
        if duplicate:
            continue
        # A market that is not two-way is not this market. A three-outcome
        # h2h (a draw league) devigged as if the two remaining sides summed
        # to the book's margin fabricates an edge out of the side that was
        # dropped; the reviewer's probe produced +34.7% that way.
        if len(by_name) != 2:
            continue
        a = by_name.get(want_a.lower() if market == "totals" else want_a)
        b = by_name.get(want_b.lower() if market == "totals" else want_b)
        if not a or not b:
            continue
        if a.get("price") is None or b.get("price") is None:
            continue
        if market != "h2h" and not _points_agree(market, a.get("point"),
                                                 b.get("point")):
            # A book quoting home -1.5 / away +2.5 is quoting two different
            # markets. Mixing it into the -1.5 group would devig it against
            # books that are not offering what it is offering, which is
            # exactly what this function promises never to do.
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
    modal = _modal_point(points)
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
    # A game missing either team name cannot be labelled. h2h and spreads
    # bail on their own, but totals would still price and emit a row with
    # "home": null, which every consumer downstream has to special-case.
    if not game.get("home_team") or not game.get("away_team"):
        return None

    markets: dict[str, dict] = {}
    for market in config.MARKETS:
        quotes, point = quotes_for(game, market)
        priced = _price_market(quotes)
        if not priced:
            continue
        entry = {
            "point": point,
            # Which outcome fair_a/best_a/edge_a were reported for. "home"
            # for h2h and spreads, "over" for totals — the *_home/*_away key
            # names below are the h2h/spreads reading of side A and side B.
            "side_a": SIDE_A[market],
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

    One malformed game does not take the league with it. run_daily.py wraps
    the whole build() call in a single try/except, so before this guard a
    price of 0, a string where an outcome dict belongs, or a non-numeric
    price dropped all fifteen games and the 9am job committed the truncated
    file with nothing visibly wrong. The failure is logged to stderr with the
    event id rather than swallowed: an unattended job that hides its own data
    loss is the thing this guard exists to prevent.
    """
    rows = []
    for game in games:
        try:
            row = price_game(game, short)
        except Exception as e:                              # noqa: BLE001
            print(f"!! board: skipped {short} game "
                  f"{game.get('id') if isinstance(game, dict) else game!r}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            continue
        if row:
            rows.append(row)
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


def _book(key: str, title: str, h2h: tuple[int, int],
          spread: tuple[int, int, float] | None = None,
          total: tuple[int, int, float] | None = None,
          home: str = "Milwaukee Brewers",
          away: str = "Chicago Cubs") -> dict:
    """One bookmaker payload, for the fixtures below."""
    markets = [{"key": "h2h", "outcomes": [
        {"name": home, "price": h2h[0]}, {"name": away, "price": h2h[1]}]}]
    if spread:
        markets.append({"key": "spreads", "outcomes": [
            {"name": home, "price": spread[0], "point": spread[2]},
            {"name": away, "price": spread[1], "point": -spread[2]}]})
    if total:
        markets.append({"key": "totals", "outcomes": [
            {"name": "Over", "price": total[0], "point": total[2]},
            {"name": "Under", "price": total[1], "point": total[2]}]})
    return {"key": key, "title": title, "markets": markets}


# The sport-specific extras a card may show beneath a club's name. Kept apart
# from `model` on purpose: every league has a win probability, only baseball
# has a starting pitcher, and mixing them would make the general path carry
# baseball's vocabulary into leagues that have no use for it.
DETAIL_KEYS = (
    "home_record", "away_record",
    "home_form", "away_form",
    "series",
    "home_starter", "away_starter",
    "home_starter_era", "away_starter_era",
    "home_hand", "away_hand",
    "home_vs_opp", "away_vs_opp",
)


def merge_model(rows: list[dict], rated: list[dict], source: str) -> int:
    """Attach a rating to each board row that has one, by event id.

    Returns the number of rows matched. A rated game missing from the board is
    ignored rather than appended — the board is the list of games we could
    price, and a game with no price has nothing to compare a number against.

    Deliberately does not invent a rating for an unmatched row. A card with no
    percentage is honest; a card showing the market's number in our colour, or
    a neighbour's number, is not.

    market_home_prob comes from the rating when the rating supplies one — the
    slate devigs its own book set and that number wins. When it does not (the
    Elo path knows nothing about prices) it is filled from the row's own h2h
    fair price, which is already on the row. Without it the card draws a bare
    fill with no tick and no footer, and the comparison between the two
    numbers is the entire point of the card.
    """
    by_id = {}
    for r in rated:
        eid = r.get("event_id")
        if eid:
            by_id[eid] = r

    matched = 0
    for row in rows:
        rating = by_id.get(row.get("event_id"))
        if not rating:
            continue

        hp, ap = rating.get("home_win_prob"), rating.get("away_win_prob")
        if hp is None or ap is None:
            continue
        # A pair that does not sum to 1 means something upstream went wrong.
        # Better to show no number than a number we cannot explain. Logged,
        # not merely skipped: this gate is the only thing standing between a
        # genuine upstream bug and a board that is quietly one card short.
        if abs(hp + ap - 1.0) > 1e-6:
            print(f"!! {source} rating for {row.get('event_id')} does not sum "
                  f"to 1 ({hp} + {ap}); no number on that card",
                  file=sys.stderr)
            continue

        market = rating.get("market_home_prob")
        if market is None:
            market = ((row.get("markets") or {}).get("h2h") or {}).get("fair_home")

        row["model"] = {
            "home_win_prob": hp,
            "away_win_prob": ap,
            "market_home_prob": market,
            "disagreement": rating.get("disagreement"),
            "suspect": bool(rating.get("suspect")),
            "source": source,
        }
        detail = {k: rating[k] for k in DETAIL_KEYS if rating.get(k) is not None}
        if detail:
            row["detail"] = detail
        matched += 1
    return matched


def merge_form(rows: list[dict], games: list[dict]) -> int:
    """Attach record, streak, last ten and the season series to each row.

    For the three leagues MLB's free API does not cover. ESPN answers a
    GitHub runner with 403 and the paid scores endpoint reaches back three
    days, not a season, so these come from the finals this project stores for
    itself -- which costs nothing further and depends on no outside party
    staying friendly.

    A club we have stored no finished games for is left alone entirely: an
    empty form block renders as a panel with three blank rows, which reads as
    a broken page rather than as a young season.
    """
    if not games:
        return 0
    form = form_store.table(games)
    matched = 0
    for row in rows:
        home, away = row.get("home"), row.get("away")
        if home not in form or away not in form:
            continue
        detail = row.setdefault("detail", {})
        detail["home_form"] = form[home]
        detail["away_form"] = form[away]
        detail["series"] = form_store.series(games, home, away)
        matched += 1
    return matched


# A club needs this many games of its own before its rating means anything.
# The league-wide min_games gate cannot stand in for it: one day of ESPN's
# college-basketball scoreboard is 100+ rows, so a 100-row store is satisfied
# on its very first morning while every club in it has played exactly once —
# and ratings.run() calls setdefault on both clubs before the tie check, so
# even a club whose only appearance was a draw sits in the table at the 1500
# starting value with zero information behind it. Ten games is where a K of
# 20-24 has moved a rating far enough from 1500 to be saying something.
MIN_CLUB_GAMES = 10


def elo_model(rows: list[dict], history: list[dict], short: str,
              min_games: int = 100) -> tuple[list[dict], int]:
    """Rate a league's upcoming games from its stored results.

    Returns (rating rows shaped for merge_model, rows skipped for want of
    history). A league with fewer than min_games of history is not rated at
    all: Elo needs a season to say anything, and a number built on a handful
    of games is noise wearing a percentage sign. A game is skipped unless
    BOTH clubs appear in at least MIN_CLUB_GAMES stored games — presence in
    the rating table is not evidence, only participation is.

    The skip count is returned rather than swallowed because the most likely
    cause is not a thin store but a name mismatch: the store is filled from
    ESPN and the board from the Odds API, and results.py's own docstring
    flags that spelling question as unresolved. A total mismatch makes the
    feature silently absent and a partial one rates half a board, so the
    caller gets a number it can print.

    Probabilities are clamped to rate_mlb's floor and ceiling. An Elo with no
    regression, no margin of victory and no backtest behind it is not
    trustworthy at the tails: the gap that produces 95% is a handful of
    results away from the gap that produces 80%, and printing the extreme
    number states a confidence this model has not earned.

    Deliberately carries no market comparison. merge_model fills
    market_home_prob from whatever rated the game, falling back to the row's
    own h2h fair price; Elo alone does not know what the market thinks.
    """
    cfg = ratings.LEAGUE_CONFIG.get(short)
    if not cfg or len(history) < min_games:
        return [], 0

    played: Counter = Counter()
    for g in history:
        played[g.get("home")] += 1
        played[g.get("away")] += 1

    table = ratings.run(history, cfg)
    out, skipped = [], 0
    for row in rows:
        home, away = row.get("home"), row.get("away")
        if (home not in table or away not in table
                or played[home] < MIN_CLUB_GAMES
                or played[away] < MIN_CLUB_GAMES):
            skipped += 1
            continue
        hp = ratings.win_probability(table[home], table[away], cfg)
        hp = max(rate_mlb.PROB_FLOOR, min(rate_mlb.PROB_CEIL, hp))
        # Rounded to the same 4dp the slate path uses: full-precision floats
        # would rewrite board.json every morning on noise in the last digit.
        hp = round(hp, 4)
        out.append({
            "event_id": row.get("event_id"),
            "home_win_prob": hp,
            "away_win_prob": round(1.0 - hp, 4),
        })
    return out, skipped


def _self_test() -> None:
    import io                        # noqa: PLC0415
    import contextlib                # noqa: PLC0415
    import odds_math as om           # noqa: PLC0415

    # A four-book game. Caesars is best on both moneyline sides and hangs a
    # different total from everyone else.
    game = {
        "id": "evt1", "sport_key": "baseball_mlb",
        "commence_time": "2026-08-31T23:05:00Z",
        "home_team": "Milwaukee Brewers", "away_team": "Chicago Cubs",
        "bookmakers": [
            _book("fanduel", "FanDuel", (-130, 110),
                  spread=(130, -155, -1.5), total=(-105, -115, 8.5)),
            _book("draftkings", "DraftKings", (-128, 108),
                  spread=(134, -160, -1.5), total=(-108, -112, 8.5)),
            _book("betmgm", "BetMGM", (-132, 112),
                  spread=(128, -152, -1.5), total=(-112, -108, 8.5)),
            # Caesars hangs a different total. It must not be devigged
            # against the other three — that would price a market nobody
            # is offering.
            _book("caesars", "Caesars", (-125, 114), total=(-110, -110, 9.5)),
        ],
    }

    quotes, point = quotes_for(game, "h2h")
    assert point is None, "a moneyline has no line to hang"
    assert len(quotes) == 4, quotes
    assert quotes[0]["book"] == "FanDuel", "the display title, not the key"
    assert quotes[0]["price_a"] == -130 and quotes[0]["price_b"] == 110, \
        "side a is the home team"

    # The modal total is 8.5 (three books); Caesars' 9.5 is excluded.
    tq, tpoint = quotes_for(game, "totals")
    assert tpoint == 8.5, tpoint
    assert len(tq) == 3, "only the books hanging the modal line are priced"
    assert tq[0]["price_a"] == -105, "side a is the over"

    # Three books post a spread, and all hang -1.5.
    sq, spoint = quotes_for(game, "spreads")
    assert spoint == -1.5, "the line is quoted from the home team's side"
    assert len(sq) == 3

    # A market no book posts yields nothing rather than raising.
    bare = {"id": "e", "home_team": "A", "away_team": "B", "bookmakers": []}
    assert quotes_for(bare, "h2h") == ([], None)

    row = price_game(game, "mlb")
    assert row is not None
    assert row["event_id"] == "evt1"
    assert row["league"] == "mlb"
    assert row["home"] == "Milwaukee Brewers"
    assert set(row["markets"]) <= {"h2h", "spreads", "totals"}

    # The monkeypatch in _price_market must put config.MIN_BOOKS back. The
    # daily job runs find_plays in this same process; a lost restore would
    # silently drop the betting card's floor to the board's.
    assert config.MIN_BOOKS == 6, \
        "_price_market must restore the play picker's book floor"

    ml = row["markets"]["h2h"]
    assert ml["side_a"] == "home" and row["markets"]["totals"]["side_a"] == "over", \
        "side A is the over on a total, not the home team"
    assert ml["best_home"]["book"] == "Caesars", \
        "-125 is the best price on the home side"
    assert ml["best_away"]["book"] == "Caesars" and ml["best_away"]["price"] == 114, \
        "+114 is the best price on the away side"
    assert 0.0 < ml["fair_home"] < 1.0
    assert 0.0 < ml["fair_away"] < 1.0
    # The away side's edge is measured against the away side's own fair
    # number and the away side's own best price. Reporting edge_a here would
    # go unnoticed without this.
    assert abs(ml["edge_away"]
               - om.expected_value_pct(ml["fair_away"], 114)) < 1e-9
    assert ml["edge_away"] != ml["edge_home"]
    assert ml["books"] == 4

    tot = row["markets"]["totals"]
    assert tot["point"] == 8.5
    assert tot["books"] == 3, "Caesars hung 9.5 and is not counted"
    assert tot["model"] is None, \
        "there is no scoring model; a total must never carry our own number"
    # Every quoted total here is 20 cents wide, so the median width is 20.
    # width is the typical single book's width, not the best-of-market pair's.
    assert tot["width"] == 20, tot["width"]

    # --- the two sides are NOT a probability distribution -----------------
    # Each side's consensus deliberately excludes the book holding THAT
    # side's best price, so with different books best on the two sides the
    # two numbers come from different samples and do not sum to 1. They are
    # two independent per-side benchmarks. NEVER normalise them: dividing
    # them by their sum would silently undo the leave-one-out exclusion,
    # which is the whole point of the estimator.
    split = {
        "id": "evt3", "commence_time": "2026-08-31T23:05:00Z",
        "home_team": "Milwaukee Brewers", "away_team": "Chicago Cubs",
        "bookmakers": [
            _book("alpha", "Alpha", (-125, 105)),     # best on the home side
            _book("bravo", "Bravo", (-140, 130)),     # best on the away side
            _book("charlie", "Charlie", (-134, 114)),
        ],
    }
    sml = price_game(split, "mlb")["markets"]["h2h"]
    assert sml["best_home"]["book"] == "Alpha"
    assert sml["best_away"]["book"] == "Bravo"
    assert sml["best_home"]["book"] != sml["best_away"]["book"], \
        "the two sides must come from different exclusions here"
    total = sml["fair_home"] + sml["fair_away"]
    assert total > 1.0 + 1e-9, total
    assert 1.0 <= total < 1.10, total

    # --- BOARD_MIN_BOOKS --------------------------------------------------
    # Pinned, because at 2 each side's "consensus" is one book's opinion on
    # a card that says "2 books".
    assert BOARD_MIN_BOOKS == 3, BOARD_MIN_BOOKS
    two = dict(game, id="evt4", bookmakers=game["bookmakers"][:2])
    assert price_game(two, "mlb") is None, \
        "two quotes leave a one-book consensus per side"
    three = dict(game, id="evt5", bookmakers=game["bookmakers"][:3])
    assert price_game(three, "mlb") is not None, "three quotes are enough"

    # --- one-sided books --------------------------------------------------
    # A book posting only the over is not half a quote; it is no quote.
    one_sided = {"key": "onesided", "title": "OneSided", "markets": [
        {"key": "totals", "outcomes": [{"name": "Over", "price": -110,
                                        "point": 8.5}]}]}
    lopsided = dict(game, id="evt6",
                    bookmakers=game["bookmakers"] + [one_sided])
    lq, _lp = quotes_for(lopsided, "totals")
    assert len(lq) == 3, "a book quoting one side is not counted"

    # --- duplicate outcome names (alternate lines) ------------------------
    # Four books send one payload carrying both -1.5 and -2.5; three send
    # only the honest -1.5. Keeping the last pair per name turns those four
    # into -2.5 quotes, which outvotes the main line, discards the -1.5 the
    # same books actually posted, and can push the market under the floor.
    def _alt(key, title, main, alt):
        return {"key": key, "title": title, "markets": [
            {"key": "spreads", "outcomes": [
                {"name": "Milwaukee Brewers", "price": main[0], "point": -1.5},
                {"name": "Chicago Cubs", "price": main[1], "point": 1.5},
                {"name": "Milwaukee Brewers", "price": alt[0], "point": -2.5},
                {"name": "Chicago Cubs", "price": alt[1], "point": 2.5}]}]}

    alts = [_alt(f"alt{i}", f"Alt{i}", (130 + i, -155 - i), (210 + i, -260 - i))
            for i in range(4)]
    dup = dict(game, id="evt7", bookmakers=game["bookmakers"] + alts)
    dq, dpoint = quotes_for(dup, "spreads")
    assert dpoint == -1.5, \
        "an alternate-line payload must not outvote the main line"
    names = [q["book"] for q in dq]
    assert len(dq) == 3 and not any(n.startswith("Alt") for n in names), \
        "a book repeating an outcome name is skipped, not last-one-wins"

    # --- deterministic modal line ----------------------------------------
    # Four books, 8.5/9.5/9.5/8.5: a 2-2 tie. Insertion order must not
    # decide it, so both permutations answer the same.
    def tie(order):
        books = {
            "a": _book("a", "A", (-110, -110), total=(-110, -110, 8.5)),
            "b": _book("b", "B", (-110, -110), total=(-110, -110, 9.5)),
            "c": _book("c", "C", (-110, -110), total=(-110, -110, 9.5)),
            "d": _book("d", "D", (-110, -110), total=(-110, -110, 8.5)),
        }
        return quotes_for({"home_team": "Milwaukee Brewers",
                           "away_team": "Chicago Cubs",
                           "bookmakers": [books[k] for k in order]},
                          "totals")[1]
    assert tie("abcd") == tie("bcda") == tie("dcba") == 8.5, \
        "the modal line must not depend on bookmaker order"

    # --- both sides must describe the same line ---------------------------
    mixed = {"key": "mix", "title": "Mixed", "markets": [
        {"key": "spreads", "outcomes": [
            {"name": "Milwaukee Brewers", "price": 130, "point": -1.5},
            {"name": "Chicago Cubs", "price": -155, "point": 2.5}]}]}
    mx = dict(game, id="evt8", bookmakers=game["bookmakers"] + [mixed])
    mq, _mp = quotes_for(mx, "spreads")
    assert "Mixed" not in [q["book"] for q in mq], \
        "home -1.5 / away +2.5 is two markets, not one quote"

    # --- a three-way market is not this market ----------------------------
    draw = {"key": "three", "title": "Three", "markets": [
        {"key": "h2h", "outcomes": [
            {"name": "Milwaukee Brewers", "price": -125},
            {"name": "Chicago Cubs", "price": 114},
            {"name": "Draw", "price": 260}]}]}
    tw = dict(game, id="evt9", bookmakers=game["bookmakers"] + [draw])
    twq, _twp = quotes_for(tw, "h2h")
    assert "Three" not in [q["book"] for q in twq], \
        "dropping the draw and devigging the rest fabricates an edge"

    # A game with too few books to price at all is dropped from the board
    # rather than shown with an invented number.
    thin = dict(game, id="evt2", bookmakers=game["bookmakers"][:1])
    assert price_game(thin, "mlb") is None

    # A game missing a team name is skipped outright — totals would
    # otherwise price and emit a row with "home": null.
    nameless = dict(game, id="evt10", home_team=None)
    assert price_game(nameless, "mlb") is None
    assert quotes_for(nameless, "totals")[0], "totals alone would still price"

    rows = build([game, thin], "mlb")
    assert len(rows) == 1, "only the priceable game reaches the board"

    # Sorted by start time, not by input order.
    early = dict(game, id="early", commence_time="2026-08-31T17:05:00Z")
    late = dict(game, id="late", commence_time="2026-08-31T23:05:00Z")
    assert [r["event_id"] for r in build([late, early], "mlb")] \
        == ["early", "late"], "the board is in start-time order"

    # --- one bad game must not take the league with it --------------------
    broken = [
        dict(game, id="bad-zero", bookmakers=[
            _book("x", "X", (0, 110)), _book("y", "Y", (-128, 108)),
            _book("z", "Z", (-132, 112))]),
        dict(game, id="bad-string-outcome", bookmakers=[
            {"key": "s", "title": "S", "markets": [
                {"key": "h2h", "outcomes": ["Milwaukee Brewers", "Chicago Cubs"]}]},
            _book("y", "Y", (-128, 108)), _book("z", "Z", (-132, 112))]),
        dict(game, id="bad-price", bookmakers=[
            _book("x", "X", ("even", 110)), _book("y", "Y", (-128, 108)),
            _book("z", "Z", (-132, 112))]),
    ]
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        survivors = build(broken + [game], "mlb")
    assert [r["event_id"] for r in survivors] == ["evt1"], \
        "a malformed game must not delete the rest of the league"
    logged = err.getvalue()
    for bad in ("bad-zero", "bad-string-outcome", "bad-price"):
        assert bad in logged, f"{bad} was swallowed silently: {logged!r}"

    doc = document({"mlb": rows}, "2026-08-31T13:00:00", "2026-08-31")
    assert doc["date"] == "2026-08-31"
    assert doc["leagues"]["mlb"]["label"] == "MLB"
    assert doc["leagues"]["mlb"]["games"][0]["event_id"] == "evt1"
    assert doc["counts"]["mlb"] == 1

    # An empty league is absent, not present-and-empty: the pages ask
    # "is this league on tonight?" by asking whether the key exists.
    nba_rows = [dict(r, league="nba") for r in rows]
    empty = document({"mlb": [], "nba": nba_rows}, "2026-08-31T13:00:00",
                     "2026-08-31")
    assert "mlb" not in empty["leagues"] and "mlb" not in empty["counts"], \
        "a league with no games must be omitted, not written empty"
    assert empty["counts"] == {"nba": 1}

    # --- merging a rating onto a priced board -------------------------------
    board_rows = [
        {"event_id": "e1", "league": "mlb", "home": "H", "away": "A",
         "commence_time": "2026-09-01T23:00:00Z", "markets": {}, "model": None},
        {"event_id": "e2", "league": "mlb", "home": "H2", "away": "A2",
         "commence_time": "2026-09-01T23:00:00Z", "markets": {}, "model": None},
    ]
    rated = [
        {"event_id": "e1", "home_win_prob": 0.4425, "away_win_prob": 0.5575,
         "market_home_prob": 0.4376, "disagreement": 0.5, "suspect": False,
         "home_record": {"w": 70, "l": 60}, "away_record": {"w": 65, "l": 65},
         "home_starter": "Hunter Greene", "home_starter_era": 3.11,
         "home_hand": "R", "away_starter": "Yu Darvish",
         "away_starter_era": 4.02, "away_hand": "R",
         "home_vs_opp": None, "away_vs_opp": None},
        # A rated game that is not on the board at all — a postponement, or a
        # game the pricing dropped for want of books. It must be ignored, not
        # appended: the board is the list of games we can price.
        {"event_id": "gone", "home_win_prob": 0.5, "away_win_prob": 0.5},
    ]

    matched = merge_model(board_rows, rated, "slate")
    assert matched == 1, matched
    assert len(board_rows) == 2, "merging must not add or drop rows"

    m = board_rows[0]["model"]
    assert m["home_win_prob"] == 0.4425 and m["away_win_prob"] == 0.5575
    assert m["market_home_prob"] == 0.4376
    assert m["disagreement"] == 0.5
    assert m["suspect"] is False
    assert m["source"] == "slate", "the card has to say where the number came from"

    d = board_rows[0]["detail"]
    assert d["home_starter"] == "Hunter Greene"
    assert d["home_record"] == {"w": 70, "l": 60}
    assert "home_win_prob" not in d, \
        "the general numbers live in model; detail is the sport-specific extra"

    # An unmatched game keeps its empty model rather than inheriting a
    # neighbour's. Showing one game's number on another is worse than none.
    assert board_rows[1]["model"] is None
    assert board_rows[1].get("detail") is None

    # A rating with no probability is not a rating.
    half = [{"event_id": "e2", "market_home_prob": 0.5}]
    assert merge_model(board_rows, half, "slate") == 0
    assert board_rows[1]["model"] is None

    # The probabilities must be a coherent pair; a rating that does not sum
    # to 1 is a bug upstream and must not reach a card — and must say so,
    # because a silently short board looks exactly like a quiet day.
    bad = [{"event_id": "e2", "home_win_prob": 0.6, "away_win_prob": 0.6}]
    sum_err = io.StringIO()
    with contextlib.redirect_stderr(sum_err):
        assert merge_model(board_rows, half + bad, "slate") == 0
    assert board_rows[1]["model"] is None
    assert "e2" in sum_err.getvalue(), \
        "a rejected rating must name the event it dropped"

    # The market's tick comes off the row itself when the rating has no
    # opinion about prices, which is every Elo-rated card.
    priced = [{"event_id": "e3", "league": "nba", "home": "H3", "away": "A3",
               "markets": {"h2h": {"fair_home": 0.62, "fair_away": 0.38}},
               "model": None}]
    assert merge_model(priced, [{"event_id": "e3", "home_win_prob": 0.55,
                                 "away_win_prob": 0.45}], "elo") == 1
    assert priced[0]["model"]["market_home_prob"] == 0.62, \
        "an Elo card must still get the market's tick from its own h2h price"

    # And the rating's own number wins when it has one: the slate devigs its
    # own book set and that is the number its card is about.
    priced[0]["model"] = None
    assert merge_model(priced, [{"event_id": "e3", "home_win_prob": 0.55,
                                 "away_win_prob": 0.45,
                                 "market_home_prob": 0.5}], "slate") == 1
    assert priced[0]["model"]["market_home_prob"] == 0.5

    # --- rating a league from its stored results ---------------------------
    # Built through results_store.merge rather than by hand, so the fixture is
    # a shape the store could actually hold: merge dedups on
    # (date, home, away), and the old fixture repeated one pairing on one date
    # sixty times — a history this module can never be handed in production.
    import results_store                                     # noqa: PLC0415

    raw = []
    for i in range(60):
        day = f"2026-{i // 28 + 4:02d}-{i % 28 + 1:02d}"
        # Alpha beats Bravo consistently; Charlie and Delta split.
        raw.append({"date": day, "home": "Alpha", "away": "Bravo",
                    "home_score": 5, "away_score": 3, "completed": True})
        raw.append({"date": day, "home": "Charlie", "away": "Delta",
                    "home_score": 4 + i % 2, "away_score": 5 - i % 2,
                    "completed": True})
    history = results_store.merge([], raw)
    assert len(history) == 120, "the fixture must survive the store's own rules"

    upcoming = [{"event_id": "n1", "league": "nba", "home": "Alpha",
                 "away": "Bravo", "markets": {}, "model": None}]

    rated, skipped = elo_model(upcoming, history, "nba", min_games=100)
    assert len(rated) == 1 and skipped == 0, (rated, skipped)
    r = rated[0]
    assert r["event_id"] == "n1"
    assert r["home_win_prob"] > 0.5, "Alpha has beaten Bravo sixty times"

    # The number is clamped. An unregressed Elo with no backtest behind it
    # runs past 92% on a fixture like this one, and printing that states a
    # confidence the model has not earned. (Asserting 0 < p < 1 could not
    # fail — the logistic is always in (0, 1) — and neither could a
    # sum-to-one check on a pair built as p and 1 - p.)
    assert r["home_win_prob"] == rate_mlb.PROB_CEIL, \
        "a sixty-game sweep must be clamped, not published at its raw value"
    assert rate_mlb.PROB_FLOOR <= r["away_win_prob"] <= rate_mlb.PROB_CEIL
    assert r["home_win_prob"] == round(r["home_win_prob"], 4), \
        "full-precision floats rewrite board.json every morning"

    # The direction survives the clamp: reverse the fixture's home and away
    # and it is the away side that sits at the ceiling.
    flipped = [{"event_id": "n1b", "league": "nba", "home": "Bravo",
                "away": "Alpha", "markets": {}, "model": None}]
    flip_rated, _flip_skipped = elo_model(flipped, history, "nba",
                                          min_games=100)
    fr = flip_rated[0]
    assert fr["away_win_prob"] > fr["home_win_prob"], fr
    assert fr["away_win_prob"] > 0.8, \
        "Alpha is still the strong club when it plays on the road"
    assert fr["away_win_prob"] <= rate_mlb.PROB_CEIL

    # The row gate is a boundary, so test it AT the boundary: min_games - 1
    # rows rate nothing, min_games rows rate.
    assert elo_model(upcoming, history[:99], "nba", min_games=100) == ([], 0)
    assert elo_model(upcoming, history[:100], "nba", min_games=100)[0] != []

    # A club can clear the row gate and still have played almost nothing.
    # One day of ESPN's college board is 100+ games with every club at a
    # single appearance, which is exactly the case that must NOT publish.
    one_each = results_store.merge(history, [
        {"date": "2026-11-10", "home": f"C{i}", "away": f"D{i}",
         "home_score": 70, "away_score": 65, "completed": True}
        for i in range(60)])
    assert len(one_each) >= 100, "the thin fixture must clear the row gate"
    single = [{"event_id": "n3", "league": "nba", "home": "C0",
               "away": "D0", "markets": {}, "model": None}]
    assert elo_model(single, one_each, "nba", min_games=100) == ([], 1), \
        "a club with one game must not be published at 1500"

    # Including a club whose only appearance was a tie: ratings.run puts it
    # in the table via setdefault before the tie check, so membership in the
    # table is not evidence that anything is known about it.
    drawn = results_store.merge(history, [
        {"date": "2026-11-11", "home": "Golf", "away": "Hotel",
         "home_score": 80, "away_score": 80, "completed": True}])
    tie_row = [{"event_id": "n4", "league": "nba", "home": "Golf",
                "away": "Hotel", "markets": {}, "model": None}]
    assert elo_model(tie_row, drawn, "nba", min_games=100) == ([], 1)

    # A game whose clubs are absent from the history is skipped, and the skip
    # is COUNTED: the likeliest cause is ESPN and the Odds API spelling the
    # clubs differently, and without a count that failure is invisible.
    stranger = [{"event_id": "n2", "league": "nba", "home": "Echo",
                 "away": "Foxtrot", "markets": {}, "model": None}]
    assert elo_model(stranger, history, "nba", min_games=100) == ([], 1)

    # An unknown league has no Elo settings and must not borrow another's.
    assert elo_model(upcoming, history, "cricket", min_games=1) == ([], 0)

    # And the output slots straight into merge_model.
    assert merge_model(upcoming, rated, "elo") == 1
    assert upcoming[0]["model"]["source"] == "elo"

    # The detail block has to carry the form and the series, or the panel
    # renders an empty section on a card whose rating merged fine.
    for key in ("home_form", "away_form", "series"):
        assert key in DETAIL_KEYS, f"{key} missing from DETAIL_KEYS"
    rows = [{"event_id": "e1", "league": "mlb",
             "markets": {"h2h": {"fair_home": 0.5}}}]
    rated = [{"event_id": "e1", "home_win_prob": 0.6, "away_win_prob": 0.4,
              "home_form": {"w": 73, "l": 65, "streak": "W1",
                            "l10_w": 5, "l10_l": 5},
              "away_form": {"w": 65, "l": 73, "streak": "L1",
                            "l10_w": 4, "l10_l": 6},
              "series": [{"date": "2026-06-08",
                          "away": "Cincinnati Reds", "away_runs": 2,
                          "home": "San Diego Padres", "home_runs": 6}]}]
    assert merge_model(rows, rated, "slate") == 1
    detail = rows[0]["detail"]
    assert detail["home_form"]["streak"] == "W1", detail
    assert detail["series"][0]["home"] == "San Diego Padres", detail["series"]

    # Leagues with no free standings source take their form from the finals
    # the daily job stores. A league we have stored nothing for leaves the
    # rows untouched rather than attaching an empty block.
    nfl = [{"event_id": "n1", "league": "nfl",
            "home": "Chicago Bears", "away": "Green Bay Packers",
            "markets": {"h2h": {"fair_home": 0.5}}}]
    stored = [
        {"date": "2026-09-06", "away": "Chicago Bears", "away_score": 10,
         "home": "Green Bay Packers", "home_score": 24, "completed": True},
        {"date": "2026-09-13", "away": "Green Bay Packers", "away_score": 13,
         "home": "Chicago Bears", "home_score": 20, "completed": True},
    ]
    assert merge_form(nfl, stored) == 1
    d = nfl[0]["detail"]
    assert d["home_form"]["streak"] == "W1", d["home_form"]
    assert d["away_form"]["w"] == 1
    assert len(d["series"]) == 2
    assert d["series"][0]["home"] == "Green Bay Packers", d["series"]

    empty = [{"event_id": "n2", "league": "nfl", "home": "A", "away": "B",
              "markets": {}}]
    assert merge_form(empty, []) == 0
    assert "detail" not in empty[0], \
        "an empty store attaches nothing rather than an empty panel"

    print("board self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
