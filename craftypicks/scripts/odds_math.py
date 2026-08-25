"""Odds conversion and vig-removal helpers.

The whole method rests on three ideas:

1. An American price implies a probability, but that probability is inflated
   because it includes the book's margin (the vig).
2. Remove the vig from both sides of a market and you get the book's honest
   opinion of the true probability.
3. Average that honest opinion across many books and you have a consensus
   fair price. Any single book offering meaningfully better than consensus is
   the only kind of edge you can find with price data alone.
"""
from __future__ import annotations


def american_to_decimal(price: int | float) -> float:
    price = float(price)
    if price > 0:
        return 1.0 + price / 100.0
    return 1.0 + 100.0 / abs(price)


def decimal_to_american(dec: float) -> int:
    if dec >= 2.0:
        return int(round((dec - 1.0) * 100.0))
    return int(round(-100.0 / (dec - 1.0)))


def american_to_prob(price: int | float) -> float:
    """Implied probability, vig included."""
    return 1.0 / american_to_decimal(price)


def prob_to_american(prob: float) -> int:
    prob = min(0.999, max(0.001, prob))
    return decimal_to_american(1.0 / prob)


def devig_pair(price_a: int | float, price_b: int | float,
               method: str = "power") -> tuple[float, float]:
    """Strip the margin from a two-way market.

    'proportional' scales both implied probabilities down by the same factor.
    It's the textbook method and it is wrong in a specific, costly direction:
    books load more margin onto longshots than favorites, so scaling evenly
    leaves the longshot's fair probability too high — which makes underdogs
    look like value when they aren't.

    'power' (the default) solves for the exponent k where p_a^k + p_b^k = 1.
    It takes more margin off the longshot than the favorite, which is closer
    to how books actually price, and stops the card filling up with +300 dogs.
    """
    pa, pb = american_to_prob(price_a), american_to_prob(price_b)
    total = pa + pb
    if total <= 0:
        return 0.5, 0.5
    if method == "proportional" or total <= 1.0:
        return pa / total, pb / total

    # Bisection on k. f(k) = pa^k + pb^k - 1 decreases as k grows.
    lo, hi = 1.0, 6.0
    for _ in range(80):
        k = (lo + hi) / 2
        if pa ** k + pb ** k > 1.0:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    fa, fb = pa ** k, pb ** k
    total_k = fa + fb
    if total_k <= 0:
        return pa / total, pb / total
    return fa / total_k, fb / total_k


def expected_value_pct(fair_prob: float, price: int | float) -> float:
    """EV of a 1-unit bet at `price` when the true probability is `fair_prob`.

    Returned as a percentage of the stake.
    """
    dec = american_to_decimal(price)
    return (fair_prob * (dec - 1.0) - (1.0 - fair_prob)) * 100.0


def profit_units(price: int | float, stake: float, result: str) -> float:
    """Units won or lost on a graded play."""
    if result == "win":
        return round(stake * (american_to_decimal(price) - 1.0), 4)
    if result == "loss":
        return round(-stake, 4)
    return 0.0  # push / void


def format_american(price: int | float) -> str:
    """Display form, using a real minus sign so it reads properly on the page."""
    price = int(round(float(price)))
    return f"+{price}" if price > 0 else f"−{abs(price)}"


def format_point(point: float | None) -> str:
    if point is None:
        return ""
    if float(point) > 0:
        return f"+{_trim(point)}"
    return f"−{_trim(abs(float(point)))}"


def _trim(value: float) -> str:
    value = float(value)
    return str(int(value)) if value == int(value) else f"{value:g}"
