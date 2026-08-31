"""Turn a set of book quotes into a fair price and the best number available."""
from __future__ import annotations


import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config           # noqa: E402
import odds_math as om   # noqa: E402

# Thresholds live in config, not here. Two separate answers to "is this a real
# market" (this module said 3 books and "power"; config says MIN_BOOKS and
# DEVIG_METHOD, which find_plays.py reads at four sites) would drift apart the
# first time one of them was tuned.
MIN_BOOKS = config.MIN_BOOKS
DEFAULT_METHOD = config.DEVIG_METHOD


def consensus(quotes: list[dict], method: str = DEFAULT_METHOD,
              exclude: str | None = None) -> tuple[float, float] | None:
    """Average every book's vig-free opinion into one fair probability pair.

    Does not weight books by reputation. Every book counts once — weighting
    would be a model of which books are sharp, and this project does not have
    the evidence to build one.
    """
    # q["book"], not q.get("book"): best_price() already raises on a quote
    # with no book, and a quote silently dropped here but fatal there is the
    # worse of the two behaviours. Malformed input should be loud in both.
    rows = [q for q in quotes if q["book"] != exclude]
    if not rows:
        return None
    fa_sum = fb_sum = 0.0
    for q in rows:
        fa, fb = om.devig_pair(q["price_a"], q["price_b"], method)
        fa_sum += fa
        fb_sum += fb
    n = len(rows)
    fa, fb = fa_sum / n, fb_sum / n
    total = fa + fb
    return (fa / total, fb / total) if total else None


def best_price(quotes: list[dict], side: str,
               books: list[str] | None = None) -> dict | None:
    """The best available number for one side, optionally among chosen books.

    Does not check whether the price is still live — that is the refresh job's
    problem, and the card carries the timestamp it was last confirmed.

    Ties broken by input order: if two books quote the same decimal odds,
    max() returns whichever one appears first in `quotes`.
    """
    key = "price_a" if side == "a" else "price_b"
    rows = quotes if books is None else [q for q in quotes if q["book"] in books]
    if not rows:
        return None
    best = max(rows, key=lambda q: om.american_to_decimal(q[key]))
    return {"book": best["book"], "price": best[key]}


def market_width(price_a: int, price_b: int) -> int:
    """Distance between the two sides in cents. Wide means the books disagree.

    OddsJam publish 20-25 cents as the widest worth considering; beyond that
    the consensus an edge is measured against is too soft to trust.

    Both prices are first mapped onto one continuous line through pick'em:
    m(p) = p - 100 for a positive price, p + 100 for a negative one, so that
    -100 and +100 both land on 0. The width is then abs(m(a) + m(b)).

    The old form, abs(abs(a) - abs(b)), is only right when the two prices have
    opposite signs. It returned 0 for -110/-110 (truly 20 cents) and 0 for
    -105/-105 (truly 10) — and both sides negative is how every near-pick'em
    two-way market is quoted, so the widest, softest markets read as perfectly
    tight and the 20-25 cent gate above never fired on any of them.
    """
    def m(p: int | float) -> float:
        p = float(p)
        return p - 100.0 if p > 0 else p + 100.0
    return int(round(abs(m(price_a) + m(price_b))))


def price_market(quotes: list[dict], method: str = DEFAULT_METHOD,
                 books: list[str] | None = None) -> dict | None:
    """Fair price, best available number, and the edge between them.

    The book holding the best price is excluded from the consensus it is
    compared against. Including it lets an outlier pull the 'fair' number
    toward itself and manufacture an edge that is not there.

    `books` restricts only the best-price search, not the consensus. This
    is intentional, not an oversight: the fair price must be drawn from the
    whole market, since a two- or three-book consensus is too noisy to call
    a consensus at all, while `books` exists only to limit which book may be
    reported as "the best I can actually get." The resulting edge means
    "what I can get at my book versus what the whole market says it is
    worth" — so `books_counted_a` (the size of the consensus, i.e. every
    quote except the best book's own) and the number of books in `books` are
    expected to differ; they are not the same count and neither is wrong.

    Returned keys worth spelling out:

    `books_counted_a` / `books_counted_b` — the size of the consensus behind
    each side. They are separate numbers because each side excludes its own
    best book, and those can be different books. A single `books_counted`
    was previously computed from side A's exclusion alone and returned as
    though it described the whole result.

    `width` — the MEDIAN of each individual quote's own two-sided width, i.e.
    what a typical single book is charging. It is NOT the width of
    best_a/best_b, because those two prices can come from different books:
    that pair is a synthetic best-of-market line no one actually quotes, and
    its width collapses toward zero exactly when the books disagree most
    (three books at 30/10/20 cents reported 10). Width exists to measure how
    much the books disagree, so it has to be measured per book.
    """
    if len(quotes) < config.MIN_BOOKS:
        return None

    best_a = best_price(quotes, "a", books)
    best_b = best_price(quotes, "b", books)
    if best_a is None or best_b is None:
        return None

    cons_a = consensus(quotes, method, exclude=best_a["book"])
    cons_b = consensus(quotes, method, exclude=best_b["book"])
    if cons_a is None or cons_b is None:
        return None

    counted_a = len([q for q in quotes if q["book"] != best_a["book"]])
    counted_b = len([q for q in quotes if q["book"] != best_b["book"]])
    widths = [market_width(q["price_a"], q["price_b"]) for q in quotes]
    return {
        "fair_a": cons_a[0],
        "fair_b": cons_b[1],
        "fair_price_a": om.prob_to_american(cons_a[0]),
        "fair_price_b": om.prob_to_american(cons_b[1]),
        "best_a": best_a,
        "best_b": best_b,
        "edge_a": om.expected_value_pct(cons_a[0], best_a["price"]),
        "edge_b": om.expected_value_pct(cons_b[1], best_b["price"]),
        "books_counted_a": counted_a,
        "books_counted_b": counted_b,
        "width": statistics.median(widths),
    }


def _self_test() -> None:
    # Six books, because config.MIN_BOOKS is the gate now and a thin
    # consensus is not a consensus. Caesars is best on BOTH sides here.
    QUOTES = [
        {"book": "Caesars",    "price_a": -128, "price_b": 118},   # width 10
        {"book": "BetRivers",  "price_a": -130, "price_b": 116},   # width 14
        {"book": "BetMGM",     "price_a": -132, "price_b": 114},   # width 18
        {"book": "FanDuel",    "price_a": -133, "price_b": 113},   # width 20
        {"book": "DraftKings", "price_a": -135, "price_b": 112},   # width 23
        {"book": "ESPNBet",    "price_a": -136, "price_b": 110},   # width 26
    ]

    # Consensus sits inside the range of individual book opinions.
    fa, fb = consensus(QUOTES)
    assert 0.53 < fa < 0.60, fa
    assert abs(fa + fb - 1.0) < 1e-9

    # Excluding a book changes the consensus it is measured against.
    fa_excl, _ = consensus(QUOTES, exclude="Caesars")
    assert fa_excl != fa, "exclude had no effect"

    # A quote with no "book" key is malformed input and must be loud in both
    # consensus() and best_price(), never silently dropped by one of them.
    for fn in (lambda: consensus(QUOTES + [{"price_a": -110, "price_b": -110}]),
               lambda: best_price(QUOTES + [{"price_a": -110, "price_b": -110}], "a")):
        try:
            fn()
        except KeyError:
            pass
        else:
            raise AssertionError("a quote with no book must raise, not vanish")

    # Best price for side A is the least negative; for side B the most positive.
    assert best_price(QUOTES, "a")["book"] == "Caesars"
    assert best_price(QUOTES, "b")["book"] == "Caesars"

    # A book filter restricts the field.
    only = best_price(QUOTES, "a", books=["FanDuel", "DraftKings"])
    assert only["book"] == "FanDuel", only
    assert best_price(QUOTES, "a", books=["Nowhere"]) is None

    # --- market_width -----------------------------------------------------
    # Opposite signs: the case the old abs(abs(a)-abs(b)) form got right.
    assert market_width(-128, 118) == 10, market_width(-128, 118)
    assert market_width(118, -128) == 10, "width is symmetric"
    # Both negative: the common near-pick'em quote, which the old form scored
    # as a perfectly tight 0 no matter how wide it actually was.
    assert market_width(-110, -110) == 20, market_width(-110, -110)
    assert market_width(-105, -105) == 10, market_width(-105, -105)
    assert market_width(-120, -102) == 22, market_width(-120, -102)
    # Both positive: also 0 under the old form when the prices matched.
    assert market_width(120, 110) == 30, market_width(120, 110)
    assert market_width(105, 105) == 10, market_width(105, 105)
    # Pick'em is zero width, and +100/-100 are the same point on the line.
    assert market_width(100, -100) == 0, market_width(100, -100)

    # price_market excludes the book being bet from its own fair price,
    # otherwise an outlier drags the consensus toward itself.
    m = price_market(QUOTES)
    assert m["best_a"]["book"] == "Caesars"
    assert m["books_counted_a"] == 5, "the best book must be out of its own average"
    assert m["books_counted_b"] == 5

    # width is the MEDIAN single-book width, not the best-of-market width.
    # Per-book widths here are 10/14/18/20/23/26, so the median is 19.
    assert m["width"] == 19, m["width"]

    # Different books hold the two best prices — the shape the old
    # best_a/best_b width hid. Alpha is best on A (-125), Bravo on B (+130).
    SPLIT = [
        {"book": "Alpha",   "price_a": -125, "price_b": 105},   # width 20
        {"book": "Bravo",   "price_a": -140, "price_b": 130},   # width 10
        {"book": "Charlie", "price_a": -134, "price_b": 114},   # width 20
        {"book": "Delta",   "price_a": -136, "price_b": 112},   # width 24
        {"book": "Echo",    "price_a": -133, "price_b": 115},   # width 18
        {"book": "Foxtrot", "price_a": -135, "price_b": 113},   # width 22
    ]
    sm = price_market(SPLIT)
    assert sm["best_a"]["book"] == "Alpha" and sm["best_b"]["book"] == "Bravo", \
        "fixture must have the two best prices at different books"
    # The synthetic best-of-market pair (-125/+130) is 5 cents wide — a line
    # no book quotes, and narrower than every real quote in the market.
    synthetic = market_width(sm["best_a"]["price"], sm["best_b"]["price"])
    assert synthetic == 5, synthetic
    assert sm["width"] != synthetic, "width is still the synthetic best-of-market"
    assert sm["width"] == 20, sm["width"]
    assert min(market_width(q["price_a"], q["price_b"]) for q in SPLIT) \
        <= sm["width"] <= max(market_width(q["price_a"], q["price_b"]) for q in SPLIT)

    # Each side excludes its own best book, and those are different books
    # here. With unique book names the two counts are necessarily equal
    # (n - 1 either way); what was wrong before was the NAME — one number
    # computed from side A's exclusion and returned as though it described
    # the whole result. So the invariant worth pinning is that no
    # side-agnostic key survives to be misread.
    assert sm["books_counted_a"] == 5 and sm["books_counted_b"] == 5
    assert "books_counted" not in sm and "books_counted" not in m, \
        "a side-agnostic books_counted cannot describe a two-sided result"

    # Thresholds come from config, not from a second copy in this module.
    assert MIN_BOOKS == config.MIN_BOOKS
    assert DEFAULT_METHOD == config.DEVIG_METHOD

    # Too few books is not a market — and the bar is config's, not 3.
    assert price_market(QUOTES[:1]) is None
    assert price_market(QUOTES[:config.MIN_BOOKS - 1]) is None
    assert price_market(QUOTES[:config.MIN_BOOKS]) is not None
    assert consensus([]) is None

    print("fair self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
