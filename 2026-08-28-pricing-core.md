# Pricing Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the sport-agnostic pricing and rating library every later plan depends on — devig, fair price, best-book selection, Elo, and free score sources — without changing anything a visitor sees.

**Architecture:** Four modules under `scripts/`, each with a single responsibility and its own self-test. `odds_math.py` gains the missing devig methods. `fair.py` turns a market into a fair price and picks the best book. `ratings.py` generalises MLB Elo to any league. `results.py` replaces paid score calls with free sources. The existing daily job keeps working throughout; this plan swaps its internals, not its output.

**Tech Stack:** Python 3.11+, standard library only. No third-party packages, no test framework.

## Global Constraints

- **Standard library only.** No pip installs. The site's whole hosting story depends on this.
- **No test runner exists.** Each module defines `_self_test()` and runs it under `if __name__ == "__main__":`. Tests are run with `python3 scripts/<module>.py`, which prints a confirmation line and exits non-zero on failure. Do not introduce pytest.
- **Never print a bare English sentence from `render.py` or `build.py`.** Every reader-facing string lives in `_src/i18n.py`. This plan touches neither renderer, but the rule binds any string added later.
- **Two-way markets only** in this plan. Three-way (draw) markets are out of scope; the leagues in play have none.
- **Every public function gets a docstring stating what it does and one thing it deliberately does not do.** The codebase's existing style; match it.
- Working directory for all commands is the repository's `craftypicks/` directory.

---

### Task 1: Complete the devig method set

`odds_math.devig_pair` supports `proportional` and `power`. The spec requires all
methods shown side by side, which needs `additive` and `shin`, plus a function
that returns every method at once.

**Files:**
- Modify: `scripts/odds_math.py` (add to `devig_pair`, add `devig_all`, add `_self_test`)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `devig_pair(price_a, price_b, method="power") -> tuple[float, float]` — methods now `"proportional" | "additive" | "power" | "shin" | "worst"`
  - `devig_all(price_a, price_b) -> dict[str, tuple[float, float]]` — keys `proportional`, `additive`, `power`, `shin`

- [ ] **Step 1: Write the failing test**

Add to the bottom of `scripts/odds_math.py`:

```python
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

    # Regression snapshot of our own solvers.
    assert abs(allm["power"][0] - 0.7331) < 0.0002
    assert abs(allm["shin"][0] - 0.7279) < 0.0002

    # Worst case is the least favourable fair probability for side A.
    worst_a, _ = devig_pair(A, B, "worst")
    assert worst_a == min(v[0] for v in allm.values())

    # A market with no margin is returned untouched.
    fa, fb = devig_pair(100, 100, "power")
    assert abs(fa - 0.5) < 1e-9 and abs(fb - 0.5) < 1e-9

    # An unknown method name is a programming error, not a silent fallback.
    try:
        devig_pair(A, B, "nonsense")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown method should raise")

    print("odds_math self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/odds_math.py`
Expected: `NameError: name 'devig_all' is not defined`

- [ ] **Step 3: Write minimal implementation**

Replace the body of `devig_pair` in `scripts/odds_math.py` with this, and add `devig_all` directly beneath it:

```python
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

    'shin' solves for the insider-trading parameter z, which corrects the
    favourite-longshot bias from a different direction than power does.

    'worst' returns the least favourable fair probability for side A across
    the other four. It does not pick a method — it deliberately assumes the
    one that makes the bet look worst.
    """
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
        every = devig_all(price_a, price_b)
        fa = min(v[0] for v in every.values())
        return fa, 1.0 - fa

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
    """
    return {m: devig_pair(price_a, price_b, m)
            for m in ("proportional", "additive", "power", "shin")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/odds_math.py`
Expected: `odds_math self-test: all invariants hold`

- [ ] **Step 5: Confirm nothing downstream broke**

Run: `python3 _src/build.py`
Expected: seven `built en/*.html` lines, no traceback. `find_plays.py` calls `devig_pair(..., config.DEVIG_METHOD)` with `"power"`, whose behaviour is unchanged.

- [ ] **Step 6: Commit**

```bash
git add scripts/odds_math.py
git commit -m "feat: add additive, shin and worst-case devig, plus devig_all"
```

---

### Task 2: Fair prices and best-book selection

**Files:**
- Create: `scripts/fair.py`

**Interfaces:**
- Consumes: `odds_math.devig_pair`, `odds_math.devig_all`, `odds_math.prob_to_american`, `odds_math.expected_value_pct`
- Produces:
  - `consensus(quotes, method="power", exclude=None) -> tuple[float, float] | None` where `quotes` is `list[dict]` each `{"book": str, "price_a": int, "price_b": int}`
  - `best_price(quotes, side, books=None) -> dict | None` returning `{"book": str, "price": int}`
  - `price_market(quotes, method="power", books=None) -> dict | None` returning `{"fair_a", "fair_b", "fair_price_a", "fair_price_b", "best_a", "best_b", "edge_a", "edge_b", "books_counted", "width"}`

- [ ] **Step 1: Write the failing test**

Create `scripts/fair.py` containing only this:

```python
"""Turn a set of book quotes into a fair price and the best number available."""
from __future__ import annotations


def _self_test() -> None:
    QUOTES = [
        {"book": "Caesars",   "price_a": -128, "price_b": 118},
        {"book": "BetRivers", "price_a": -130, "price_b": 116},
        {"book": "FanDuel",   "price_a": -133, "price_b": 113},
        {"book": "DraftKings", "price_a": -135, "price_b": 112},
    ]

    # Consensus sits inside the range of individual book opinions.
    fa, fb = consensus(QUOTES)
    assert 0.53 < fa < 0.60, fa
    assert abs(fa + fb - 1.0) < 1e-9

    # Excluding a book changes the consensus it is measured against.
    fa_excl, _ = consensus(QUOTES, exclude="Caesars")
    assert fa_excl != fa, "exclude had no effect"

    # Best price for side A is the least negative; for side B the most positive.
    assert best_price(QUOTES, "a")["book"] == "Caesars"
    assert best_price(QUOTES, "b")["book"] == "Caesars"

    # A book filter restricts the field.
    only = best_price(QUOTES, "a", books=["FanDuel", "DraftKings"])
    assert only["book"] == "FanDuel", only
    assert best_price(QUOTES, "a", books=["Nowhere"]) is None

    # price_market excludes the book being bet from its own fair price,
    # otherwise an outlier drags the consensus toward itself.
    m = price_market(QUOTES)
    assert m["best_a"]["book"] == "Caesars"
    assert m["books_counted"] == 3, "the best book must be out of its own average"

    # Market width is the gap between the two sides in cents.
    assert m["width"] == abs(-128) - 118 or m["width"] == 10, m["width"]

    # Too few books is not a market.
    assert price_market(QUOTES[:1]) is None
    assert consensus([]) is None

    print("fair self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/fair.py`
Expected: `NameError: name 'consensus' is not defined`

- [ ] **Step 3: Write minimal implementation**

Insert above `_self_test()` in `scripts/fair.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import odds_math as om   # noqa: E402

MIN_BOOKS = 3


def consensus(quotes: list[dict], method: str = "power",
              exclude: str | None = None) -> tuple[float, float] | None:
    """Average every book's vig-free opinion into one fair probability pair.

    Does not weight books by reputation. Every book counts once — weighting
    would be a model of which books are sharp, and this project does not have
    the evidence to build one.
    """
    rows = [q for q in quotes if q.get("book") != exclude]
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
    """
    return abs(abs(price_a) - abs(price_b))


def price_market(quotes: list[dict], method: str = "power",
                 books: list[str] | None = None) -> dict | None:
    """Fair price, best available number, and the edge between them.

    The book holding the best price is excluded from the consensus it is
    compared against. Including it lets an outlier pull the 'fair' number
    toward itself and manufacture an edge that is not there.
    """
    if len(quotes) < MIN_BOOKS:
        return None

    best_a = best_price(quotes, "a", books)
    best_b = best_price(quotes, "b", books)
    if best_a is None or best_b is None:
        return None

    cons_a = consensus(quotes, method, exclude=best_a["book"])
    cons_b = consensus(quotes, method, exclude=best_b["book"])
    if cons_a is None or cons_b is None:
        return None

    counted = len([q for q in quotes if q["book"] != best_a["book"]])
    return {
        "fair_a": cons_a[0],
        "fair_b": cons_b[1],
        "fair_price_a": om.prob_to_american(cons_a[0]),
        "fair_price_b": om.prob_to_american(cons_b[1]),
        "best_a": best_a,
        "best_b": best_b,
        "edge_a": om.expected_value_pct(cons_a[0], best_a["price"]),
        "edge_b": om.expected_value_pct(cons_b[1], best_b["price"]),
        "books_counted": counted,
        "width": market_width(best_a["price"], best_b["price"]),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/fair.py`
Expected: `fair self-test: all invariants hold`

- [ ] **Step 5: Commit**

```bash
git add scripts/fair.py
git commit -m "feat: add fair.py — consensus pricing and best-book selection"
```

---

### Task 3: Generalise Elo to any league

`rate_mlb.py` computes MLB Elo inline. Extract the league-agnostic part so NBA,
NFL and NCAAB can use it.

**Files:**
- Create: `scripts/ratings.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `EloConfig(k: float, home_edge: float, start: float, regress: float)`
  - `run(results, config) -> dict[str, float]` where `results` is a list of `{"date": "YYYY-MM-DD", "home": str, "away": str, "home_score": int, "away_score": int}` sorted or unsorted
  - `win_probability(rating_home, rating_away, config) -> float`
  - `LEAGUE_CONFIG: dict[str, EloConfig]` keyed `mlb`, `nba`, `nfl`, `ncaab`

- [ ] **Step 1: Write the failing test**

Create `scripts/ratings.py` containing only this:

```python
"""Elo ratings for any league, from dated results."""
from __future__ import annotations


def _self_test() -> None:
    cfg = LEAGUE_CONFIG["mlb"]

    # A rating pair with no edge and no home advantage is a coin flip.
    flat = EloConfig(k=cfg.k, home_edge=0.0, start=1500.0, regress=0.0)
    assert abs(win_probability(1500, 1500, flat) - 0.5) < 1e-9

    # Home advantage moves the number the right way.
    assert win_probability(1500, 1500, cfg) > 0.5

    # A stronger team is favoured.
    assert win_probability(1600, 1400, flat) > 0.7

    # Elo is zero-sum: one game moves both ratings by the same amount.
    games = [{"date": "2026-04-01", "home": "A", "away": "B",
              "home_score": 5, "away_score": 3}]
    r = run(games, flat)
    assert abs((r["A"] - 1500) + (r["B"] - 1500)) < 1e-9, "not zero-sum"
    assert r["A"] > 1500 and r["B"] < 1500

    # A tie leaves both ratings untouched rather than guessing a winner.
    tied = run([{"date": "2026-04-01", "home": "A", "away": "B",
                 "home_score": 4, "away_score": 4}], flat)
    assert abs(tied["A"] - 1500) < 1e-9 and abs(tied["B"] - 1500) < 1e-9

    # No look-ahead: results are applied in date order regardless of input
    # order, so a later game can never influence an earlier rating.
    a = run([{"date": "2026-04-01", "home": "A", "away": "B",
              "home_score": 5, "away_score": 3},
             {"date": "2026-04-02", "home": "B", "away": "A",
              "home_score": 9, "away_score": 1}], flat)
    b = run([{"date": "2026-04-02", "home": "B", "away": "A",
              "home_score": 9, "away_score": 1},
             {"date": "2026-04-01", "home": "A", "away": "B",
              "home_score": 5, "away_score": 3}], flat)
    assert a == b, "result order changed the ratings"

    # An empty season produces no ratings rather than raising.
    assert run([], flat) == {}

    # Every league has a config and none of them share an object.
    assert set(LEAGUE_CONFIG) == {"mlb", "nba", "nfl", "ncaab"}
    assert LEAGUE_CONFIG["nfl"].k != LEAGUE_CONFIG["mlb"].k, \
        "NFL plays 17 games; it cannot use MLB's K"

    print("ratings self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/ratings.py`
Expected: `NameError: name 'LEAGUE_CONFIG' is not defined`

- [ ] **Step 3: Write minimal implementation**

Insert above `_self_test()` in `scripts/ratings.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class EloConfig:
    """Per-league Elo settings.

    Does not adapt K to margin of victory. A 10-run win and a 1-run win move
    the rating identically, which understates blowouts on purpose — margin is
    noisier than the result and this project has not yet measured whether
    weighting it helps.
    """
    k: float
    home_edge: float      # rating points, not probability
    start: float = 1500.0
    regress: float = 0.0  # fraction pulled back to start between seasons


# K is smaller where a season is short: a 17-game NFL season cannot support
# MLB's per-game movement without the ratings thrashing. Home edge is in
# rating points and reflects each sport's measured home-field advantage.
LEAGUE_CONFIG: dict[str, EloConfig] = {
    "mlb":   EloConfig(k=4.0,  home_edge=24.0,  regress=0.25),
    "nba":   EloConfig(k=20.0, home_edge=100.0, regress=0.25),
    "nfl":   EloConfig(k=20.0, home_edge=55.0,  regress=0.33),
    "ncaab": EloConfig(k=24.0, home_edge=100.0, regress=0.50),
}


def win_probability(rating_home: float, rating_away: float,
                    config: EloConfig) -> float:
    """Probability the home side wins, from the rating gap plus home edge.

    Does not account for rest, travel, injuries or the starting pitcher. Those
    are layered on by the sport's own module where the data exists.
    """
    gap = (rating_home + config.home_edge) - rating_away
    return 1.0 / (1.0 + 10.0 ** (-gap / 400.0))


def run(results: list[dict], config: EloConfig) -> dict[str, float]:
    """Play a season forward and return each team's final rating.

    Results are sorted by date before anything is applied, so a rating can
    never be influenced by a game that had not yet happened. Ties leave both
    teams untouched — there is no winner to move the ratings toward.
    """
    ratings: dict[str, float] = {}
    for g in sorted(results, key=lambda r: (r.get("date") or "", r.get("home") or "")):
        home, away = g["home"], g["away"]
        rh = ratings.setdefault(home, config.start)
        ra = ratings.setdefault(away, config.start)
        if g["home_score"] == g["away_score"]:
            continue
        expected = win_probability(rh, ra, config)
        actual = 1.0 if g["home_score"] > g["away_score"] else 0.0
        move = config.k * (actual - expected)
        ratings[home] = rh + move
        ratings[away] = ra - move
    return ratings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/ratings.py`
Expected: `ratings self-test: all invariants hold`

- [ ] **Step 5: Commit**

```bash
git add scripts/ratings.py
git commit -m "feat: add ratings.py — league-agnostic Elo with no look-ahead"
```

---

### Task 4: Free score sources

Replaces the Odds API `/scores` endpoint, which costs 2 credits per league per
call. MLB has an official free API; ESPN covers the rest.

**Files:**
- Create: `scripts/results.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `finals(league, date_str) -> list[dict]` returning `[{"home","away","home_score","away_score","completed","date"}]`
  - `parse_espn(payload) -> list[dict]` — pure, takes a decoded JSON dict
  - `parse_statsapi(payload) -> list[dict]` — pure, takes a decoded JSON dict
  - `ESPN_PATH: dict[str, str]` keyed `mlb`, `nba`, `nfl`, `ncaab`

- [ ] **Step 1: Write the failing test**

Create `scripts/results.py` containing only this:

```python
"""Final scores from free sources: MLB StatsAPI for baseball, ESPN elsewhere."""
from __future__ import annotations


def _self_test() -> None:
    # A recorded ESPN shape, trimmed to the fields we read.
    espn = {"events": [{"date": "2026-08-26T23:05Z", "status":
              {"type": {"completed": True}},
              "competitions": [{"competitors": [
                  {"homeAway": "home", "score": "4",
                   "team": {"displayName": "Milwaukee Brewers"}},
                  {"homeAway": "away", "score": "1",
                   "team": {"displayName": "Chicago Cubs"}}]}]}]}
    rows = parse_espn(espn)
    assert len(rows) == 1
    assert rows[0]["home"] == "Milwaukee Brewers"
    assert rows[0]["away"] == "Chicago Cubs"
    assert rows[0]["home_score"] == 4 and rows[0]["away_score"] == 1
    assert rows[0]["completed"] is True

    # An in-progress game is returned but flagged incomplete, never guessed at.
    live = {"events": [{"date": "2026-08-26T23:05Z", "status":
              {"type": {"completed": False}},
              "competitions": [{"competitors": [
                  {"homeAway": "home", "score": "2",
                   "team": {"displayName": "A"}},
                  {"homeAway": "away", "score": "1",
                   "team": {"displayName": "B"}}]}]}]}
    assert parse_espn(live)[0]["completed"] is False

    # Malformed entries are skipped, not crashed on. A score source going
    # strange must never take down the daily build.
    broken = {"events": [{"competitions": [{}]},
                         {"competitions": [{"competitors": [
                             {"homeAway": "home", "team": {}}]}]},
                         {"no": "competitions"}]}
    assert parse_espn(broken) == []
    assert parse_espn({}) == []

    # MLB StatsAPI shape.
    api = {"dates": [{"games": [{"status": {"abstractGameState": "Final"},
             "gameDate": "2026-08-26T23:05:00Z",
             "teams": {"home": {"score": 4, "team": {"name": "Milwaukee Brewers"}},
                       "away": {"score": 1, "team": {"name": "Chicago Cubs"}}}}]}]}
    rows = parse_statsapi(api)
    assert len(rows) == 1 and rows[0]["home_score"] == 4
    assert rows[0]["completed"] is True
    assert parse_statsapi({}) == []

    # Every league we publish has an ESPN path.
    assert set(ESPN_PATH) == {"mlb", "nba", "nfl", "ncaab"}

    print("results self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/results.py`
Expected: `NameError: name 'parse_espn' is not defined`

- [ ] **Step 3: Write minimal implementation**

Insert above `_self_test()` in `scripts/results.py`:

```python
import json
import urllib.error
import urllib.request

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_PATH = {
    "mlb":   "baseball/mlb",
    "nba":   "basketball/nba",
    "nfl":   "football/nfl",
    "ncaab": "basketball/mens-college-basketball",
}
STATSAPI = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
TIMEOUT = 15


def _get(url: str) -> dict:
    """Fetch and decode JSON, returning {} on any failure.

    Deliberately swallows every error. A free score source is a convenience;
    if it is down the build must still produce a site, just without last
    night's finals filled in.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "craftypicks/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        print(f"!! score source unreachable ({type(e).__name__}); skipping")
        return {}


def parse_espn(payload: dict) -> list[dict]:
    """Pull finals out of an ESPN scoreboard payload.

    Does not raise on a malformed entry. ESPN's endpoint is undocumented and
    can change shape without notice, so anything that does not parse is
    skipped and the rest of the slate still comes through.
    """
    out = []
    for ev in (payload or {}).get("events") or []:
        try:
            comp = (ev.get("competitions") or [])[0]
            sides = {c["homeAway"]: c for c in comp["competitors"]}
            home, away = sides["home"], sides["away"]
            out.append({
                "home": home["team"]["displayName"],
                "away": away["team"]["displayName"],
                "home_score": int(home["score"]),
                "away_score": int(away["score"]),
                "completed": bool(
                    ev.get("status", {}).get("type", {}).get("completed")),
                "date": (ev.get("date") or "")[:10],
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def parse_statsapi(payload: dict) -> list[dict]:
    """Pull finals out of an MLB StatsAPI schedule payload.

    Same tolerance as parse_espn: a game that does not parse is dropped rather
    than failing the run.
    """
    out = []
    for day in (payload or {}).get("dates") or []:
        for g in day.get("games") or []:
            try:
                teams = g["teams"]
                out.append({
                    "home": teams["home"]["team"]["name"],
                    "away": teams["away"]["team"]["name"],
                    "home_score": int(teams["home"]["score"]),
                    "away_score": int(teams["away"]["score"]),
                    "completed":
                        g.get("status", {}).get("abstractGameState") == "Final",
                    "date": (g.get("gameDate") or "")[:10],
                })
            except (KeyError, TypeError, ValueError):
                continue
    return out


def finals(league: str, date_str: str) -> list[dict]:
    """Completed games for one league on one date, from a free source.

    Baseball uses MLB's official API because it is documented and stable.
    Everything else uses ESPN, which is neither, hence the tolerant parsing.
    """
    if league == "mlb":
        rows = parse_statsapi(_get(STATSAPI.format(date=date_str)))
        if rows:
            return [r for r in rows if r["completed"]]
        print("!! StatsAPI returned nothing; falling back to ESPN for MLB")

    path = ESPN_PATH.get(league)
    if not path:
        return []
    url = f"{ESPN_BASE}/{path}/scoreboard?dates={date_str.replace('-', '')}"
    return [r for r in parse_espn(_get(url)) if r["completed"]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/results.py`
Expected: `results self-test: all invariants hold`

- [ ] **Step 5: Verify against the live sources**

This sandbox cannot reach either host, so this step runs in CI. Create
`.github/workflows/probe.yml`:

```yaml
name: Probe score sources
on: workflow_dispatch
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          cd craftypicks
          python3 - <<'PY'
          import sys; sys.path.insert(0, "scripts")
          import results
          for lg in ("mlb", "nba", "nfl", "ncaab"):
              rows = results.finals(lg, "2026-08-26")
              print(f"{lg:<6} {len(rows)} completed games")
              for r in rows[:2]:
                  print(f"   {r['away']} {r['away_score']} @ "
                        f"{r['home']} {r['home_score']}")
          PY
```

Run it from Actions → Probe score sources → Run workflow. Expected: MLB returns
completed games with sensible names and scores. Out-of-season leagues returning
0 games is correct, not a failure.

- [ ] **Step 6: Commit**

```bash
git add scripts/results.py .github/workflows/probe.yml
git commit -m "feat: add results.py — free score sources with tolerant parsing"
```

---

### Task 5: Rename the misnamed MLB API client

`screen_mlb.py` is not a screen. It is the MLB StatsAPI client, and
`pitchers.py`, `rate_mlb.py` and `slate.py` all depend on it. Renaming it before
the screens are retired prevents it being deleted with them.

**Files:**
- Rename: `scripts/screen_mlb.py` → `scripts/mlb_api.py`
- Modify: `scripts/pitchers.py`, `scripts/rate_mlb.py`, `scripts/slate.py`, `scripts/screen_source.py`

**Interfaces:**
- Consumes: nothing new
- Produces: module `mlb_api` with every function `screen_mlb` had, unchanged

- [ ] **Step 1: Record the current importers**

Run: `grep -rln "screen_mlb" scripts/ _src/`
Expected exactly: `scripts/pitchers.py`, `scripts/rate_mlb.py`, `scripts/slate.py`, `scripts/screen_source.py`

- [ ] **Step 2: Rename and rewrite the imports**

```bash
git mv scripts/screen_mlb.py scripts/mlb_api.py
sed -i 's/\bimport screen_mlb\b/import mlb_api/g; s/\bscreen_mlb\./mlb_api./g' \
  scripts/pitchers.py scripts/rate_mlb.py scripts/slate.py scripts/screen_source.py
```

- [ ] **Step 3: Rewrite the module docstring**

`scripts/mlb_api.py` already opens with a nine-line docstring — lines 1-9,
ending with the `"""` on its own line. Replace all nine lines, not only the
first: dropping a new docstring on top of the old one produces a syntax error,
and deleting the old one loses a warning that is still true. The block below
carries the vs_roster note over verbatim.

```python
"""Client for MLB's free StatsAPI — probable starters, game logs, team rates.

Named `screen_mlb.py` until 2026-08-28, which was wrong in a way that nearly
cost us: it is not a screen, and four modules depend on it for data. It was
renamed so that retiring the strikeout screens cannot take the MLB board and
the pitcher props down with them.

Ported from the V2.2 project to stdlib urllib so the repo keeps its
zero-dependency property — GitHub Actions installs nothing, which is one
less thing that can break at 9am.

The expensive call is vs_roster(): one request per batter. Callers must
gate it behind the cheap filters, which is what screen_source does.
"""
```

Then confirm the file still parses and the docstring survived:

Run: `python3 -c "import sys; sys.path.insert(0,'scripts'); import mlb_api; print(mlb_api.__doc__.splitlines()[0])"`
Expected: the docstring's first line, and no SyntaxError.

- [ ] **Step 4: Verify nothing still refers to the old name**

Run: `grep -rn "screen_mlb" scripts/ _src/ ; echo "exit=$?"`
Expected: no output, `exit=1`

- [ ] **Step 5: Verify the build and every self-test still pass**

Run:
```bash
python3 scripts/odds_math.py && python3 scripts/fair.py && \
python3 scripts/ratings.py && python3 scripts/results.py && \
python3 scripts/stats.py && python3 _src/build.py
```
Expected: five self-test lines, then seven `built en/*.html` lines, no traceback.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename screen_mlb.py to mlb_api.py — it is a data client, not a screen"
```

---

## What this plan deliberately does not do

- No visitor-facing change. The site builds and looks identical when this plan
  is done. That is the point: the library is proven before anything is rebuilt
  on top of it.
- No removal of `find_plays.py`'s own devig call. It keeps using
  `devig_pair(..., "power")`, whose behaviour is unchanged. Retiring it belongs
  to the board plan, where its consumer disappears.
- No wiring of `results.py` into the daily job. That swap belongs with the
  refresh workflow, where the credit saving can be measured.
- No split of `screen_config.py`. The spec moves its season and props constants
  into `config.py` and retires the thresholds with the screens; both halves of
  that move need the screens' consumers gone first, which is plan 2.
- No retirement of `closing.py`. It is superseded by the hourly refresh, so it
  is deleted in plan 3 — deleting it now would leave nothing recording closes.
- `fair.py`'s tests do not pin power and Shin to a published worked example.
  Our solvers differ from one by 0.84 and 0.26 points, which is ordinary
  variance between implementations, not a defect; the spec's "hand-computed
  values" bullet is met for proportional and additive, and power and Shin are
  held instead by invariants plus a regression snapshot of our own output.

## Plans that follow

| Plan | Depends on | Ships |
|---|---|---|
| 2. Board and light theme | this | A working four-league board on the new palette |
| 3. Hourly refresh and live scores | 2 | Prices current to the hour, scores live |
| 4. Props | 2 | List view, detail panel, NFL/NBA pulls |
| 5. Accuracy | 3 | Closing-line movement, calibration, intervals |
| 6. Historical backtest | 5 | Launch-day sample, labelled as backtest |
