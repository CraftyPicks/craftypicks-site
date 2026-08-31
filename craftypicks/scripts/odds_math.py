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


METHODS = ("proportional", "additive", "power", "shin", "worst")


def devig_pair(price_a: int | float, price_b: int | float,
               method: str = "power") -> tuple[float, float]:
    """Strip the margin from a two-way market.

    'proportional' scales both implied probabilities down by the same factor.
    It's the textbook method and it is wrong in a specific, costly direction:
    books load more margin onto longshots than favorites, so scaling evenly
    leaves the longshot's fair probability too high.

    'additive' removes an equal slice of the overround from each side. It can
    drive a heavy longshot negative, which is why the result is clamped and
    renormalised rather than returned raw.

    'power' solves for the exponent k where p_a^k + p_b^k = 1.

    'shin' solves for the insider-trading parameter z. For a TWO-outcome
    market Shin coincides exactly with 'additive' — that is an analytic
    identity for n=2, not a quirk of this solver, and it holds to floating
    point (agreement to ~4e-16 over thousands of random two-way markets).
    Shin only diverges from additive from three outcomes onward. The solver
    is kept because this branch is two-way-only today and a later plan may
    add three-way markets, where it does earn its place.

    'worst' returns the least favourable fair probability for EACH side
    independently, taken across the other four methods. It does not pick a
    method — it deliberately assumes the one that makes the bet look worst,
    and it does that for side A and side B separately.

    The 'worst' pair deliberately DOES NOT sum to 1. Taking the minimum of
    each side at once is not a probability distribution; normalising it back
    to 1 would hand back to one side exactly the conservatism just taken from
    the other, which is what the old `(fa, 1 - fa)` form did — `1 - min(fa)`
    is the MAXIMUM fair probability for B, so the setting advertised as the
    conservative one made side B look as good as possible. Slightly
    sub-unity totals are the honest result and callers must not renormalise.
    """
    if method not in METHODS:
        # Validated before any computation: the no-margin short-circuit below
        # used to return (0.5, 0.5) for a bogus method name, which is exactly
        # the silent fallback this is documented not to be.
        raise ValueError(f"unknown devig method: {method!r}")

    pa, pb = american_to_prob(price_a), american_to_prob(price_b)
    total = pa + pb
    if total <= 0:
        return 0.5, 0.5
    if total <= 1.0:                      # no margin to remove
        return pa / total, pb / total

    if method == "proportional":
        return pa / total, pb / total

    if method == "additive":
        excess = (total - 1.0) / 2.0
        fa, fb = max(pa - excess, 1e-6), max(pb - excess, 1e-6)
        t = fa + fb
        return fa / t, fb / t

    if method == "power":
        lo, hi = 1.0, 6.0
        for _ in range(80):
            k = (lo + hi) / 2
            if pa ** k + pb ** k > 1.0:
                lo = k
            else:
                hi = k
        k = (lo + hi) / 2
        fa, fb = pa ** k, pb ** k
        t = fa + fb
        return (pa / total, pb / total) if t <= 0 else (fa / t, fb / t)

    if method == "shin":
        # Bisection on z in [0, 0.9). Larger z removes more from the longshot.
        lo, hi = 0.0, 0.9
        for _ in range(200):
            z = (lo + hi) / 2
            pis = [_shin_prob(q, z, total) for q in (pa, pb)]
            if sum(pis) > 1.0:
                lo = z
            else:
                hi = z
        z = (lo + hi) / 2
        fa, fb = (_shin_prob(q, z, total) for q in (pa, pb))
        t = fa + fb
        return (pa / total, pb / total) if t <= 0 else (fa / t, fb / t)

    if method == "worst":
        # Re-runs the power and Shin bisections via devig_all. Acceptable at
        # this call volume; not worth caching.
        every = devig_all(price_a, price_b)
        fa = min(v[0] for v in every.values())
        fb = min(v[1] for v in every.values())
        return fa, fb           # unnormalised on purpose — see the docstring

    raise ValueError(f"unknown devig method: {method!r}")


def _shin_prob(q: float, z: float, total: float) -> float:
    """One outcome's Shin-adjusted probability, before renormalising."""
    if z >= 1.0:
        return q / total
    inner = z * z + 4.0 * (1.0 - z) * q * q / total
    return ((inner ** 0.5) - z) / (2.0 * (1.0 - z))


def devig_all(price_a: int | float,
              price_b: int | float) -> dict[str, tuple[float, float]]:
    """Every method at once, for showing the spread between them.

    Does not include 'worst', which is derived from these rather than being a
    method in its own right.

    NOTE: four keys, three distinct numbers. For a two-way market 'shin' is
    analytically identical to 'additive' (see devig_pair), so a "methods side
    by side" UI built on this dict would ship a duplicated column. Collapse
    or label the pair until three-way markets exist.
    """
    return {m: devig_pair(price_a, price_b, m)
            for m in ("proportional", "additive", "power", "shin")}


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


def _self_test() -> None:
    """Invariants that hold for every devig method, plus two closed forms.

    Power and Shin are NOT asserted against published third-party figures.
    Different solvers give slightly different answers for both (ours differ
    from one published worked example by 0.84 and 0.26 points), so pinning
    borrowed constants would encode someone else's implementation. What is
    asserted is what must be true of any correct implementation, plus a
    regression snapshot of our own numbers.
    """
    A, B = -300, 240
    raw_a, raw_b = american_to_prob(A), american_to_prob(B)
    assert abs(raw_a + raw_b - 1.0441) < 0.0005, "test fixture drifted"

    allm = devig_all(A, B)
    assert set(allm) == {"proportional", "additive", "power", "shin"}

    for name, (fa, fb) in allm.items():
        assert abs(fa + fb - 1.0) < 1e-9, f"{name} does not sum to 1"
        assert 0.0 < fa < 1.0 and 0.0 < fb < 1.0, f"{name} out of range"
        assert fa < raw_a, f"{name} did not remove margin from the favourite"
        assert fb < raw_b, f"{name} did not remove margin from the longshot"

    # Closed forms, unambiguous across implementations.
    assert abs(allm["proportional"][0] - 0.7183) < 0.0002
    assert abs(allm["additive"][0] - 0.7279) < 0.0002

    # Regression snapshot of our own power solver.
    assert abs(allm["power"][0] - 0.7331) < 0.0002

    # Shin is not pinned to a constant, because the constant it would be
    # pinned to (0.7279) is also additive's closed form — such an assertion
    # passes just as happily against a Shin solver that has silently
    # degenerated into additive. Assert the identity itself instead: for two
    # outcomes Shin and additive are analytically the same number, so the
    # only meaningful check is that they agree to solver precision.
    for pair in ((-300, 240), (-110, -110), (150, -170), (-2000, 900)):
        sh = devig_pair(*pair, "shin")
        ad = devig_pair(*pair, "additive")
        assert abs(sh[0] - ad[0]) < 1e-12 and abs(sh[1] - ad[1]) < 1e-12, \
            f"shin/additive identity broken for n=2 at {pair}"

    # 'worst' takes the least favourable fair probability for EACH side
    # independently, so it is conservative on both. The pair therefore sums
    # to slightly LESS than 1 and must not be renormalised.
    worst_a, worst_b = devig_pair(A, B, "worst")
    assert worst_a == min(v[0] for v in allm.values()), "side A not worst-cased"
    assert worst_b == min(v[1] for v in allm.values()), "side B not worst-cased"
    assert worst_a + worst_b < 1.0, "worst-case pair must not sum to 1"
    assert worst_a + worst_b > 0.98, "worst-case pair drifted implausibly low"
    # And the edge it reports must be no better than any single method's.
    for name, (fa_m, fb_m) in allm.items():
        assert worst_b <= fb_m + 1e-12, f"'worst' beats {name} on side B"

    # A market with no margin is returned untouched.
    fa, fb = devig_pair(100, 100, "power")
    assert abs(fa - 0.5) < 1e-9 and abs(fb - 0.5) < 1e-9

    # An unknown method name is a programming error, not a silent fallback.
    # Checked on a market WITH margin and on one WITHOUT: the no-margin
    # short-circuit used to return (0.5, 0.5) before the method was ever
    # looked at, which is precisely the silent fallback this denies.
    for bogus_market in ((A, B), (100, 100), (200, -150)):
        try:
            devig_pair(*bogus_market, "nonsense")
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"unknown method should raise, even at {bogus_market}")

    print("odds_math self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
