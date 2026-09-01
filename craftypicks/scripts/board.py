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
import leagues   # noqa: E402

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

    print("board self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
