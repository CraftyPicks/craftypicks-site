#!/usr/bin/env python3
"""Our side against the spread, for the college boards.

Given our expected margin for the home team (BPI for basketball, FPI for
football) and the market's spread for the home team, the side we like is the
one our line says beats the number, and its chance to cover is the normal
CDF of the gap between the two lines over the sport's margin spread:

    gap = margin_home + spread_home      (> 0: home covers, < 0: away covers)
    cover = Phi(|gap| / sd)

Shown as the card's headline with the point gap as the edge. The point gap
is the honest number; the cover % assumes our line is right on average,
which only the record can confirm.

Calibrated (Nov 2026) after the first week showed our raw line beside the
market's: 47 of 56 basketball picks were underdogs and the "Best bets"
were nearly all 20-to-35-point dogs. Three corrections, in order:

  1. Stretch. Ratings squeeze blowouts: the market's spread ran about 1.24x
     BPI's margin (and 0.83x FPI's). fit_stretch measures that ratio on
     the day's own games and scales our margin by it.
  2. Blend. Once both teams have MIN_GAMES finals, part of the margin comes
     from this season's scoring margins (blend).
  3. Shrink. The market is the better line on average, so the gap is
     halved (SHRINK) and the spread of outcomes widens with the spread
     (SD_PER_POINT). A gap still huge after all that is flagged "check":
     the rating is far more likely missing news than the market wrong.
"""
from __future__ import annotations

import math

SD = {"ncaab": 11.0, "ncaaf": 14.0}


# Tiers by the point gap between our line and the market's. Starting
# values; the tier records on the page say whether bigger gaps really win
# more often, and these move if they do not.
# On the shrunk gap: Best 4+ is 8+ points of raw disagreement.
BEST, LEAN = 4.0, 2.0
TIERS = ("best", "lean", "check", "pass")

SHRINK = 0.5                  # weight on our line against the market's
SD_PER_POINT = 0.15           # extra margin SD per point of spread
CHECK_RAW = 15.0              # raw gap flagged on any spread ...
CHECK_RAW_BIG, BIG_SPREAD = 8.0, 20.0   # ... or this much on a big one
STRETCH_MIN, STRETCH_MAX, STRETCH_GAMES = 0.7, 1.5, 12
STRETCH_DEFAULT = {"ncaab": 1.24, "ncaaf": 0.83}
MIN_GAMES, FULL_GAMES, SEASON_WEIGHT = 5, 10, 0.5


def tier(gap, check: bool = False) -> str | None:
    """"check" when flagged, else "best" (4+ points), "lean" (2-4),
    "pass" (under 2); None without a gap."""
    if gap is None:
        return None
    if check:
        return "check"
    return "best" if gap >= BEST else "lean" if gap >= LEAN else "pass"


def fit_stretch(pairs, default: float) -> float:
    """Market margin over our margin, least squares through the origin,
    from (our_margin_home, market_margin_home) pairs. The default when
    there are fewer than STRETCH_GAMES; clamped so a strange day cannot
    turn the model inside out."""
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    sxx = sum(x * x for x, _ in pairs)
    if len(pairs) < STRETCH_GAMES or sxx == 0:
        return default
    k = sum(x * y for x, y in pairs) / sxx
    return round(max(STRETCH_MIN, min(STRETCH_MAX, k)), 2)


def blend(margin: float, home, away, edge: float) -> float:
    """Mix this season's scoring margins into the rating's margin.

    home/away: (games, points-for-minus-against per game) or None. Nothing
    changes until both have MIN_GAMES; the season's weight then grows to
    SEASON_WEIGHT at FULL_GAMES. Season margins are halved: early
    schedules are lopsided and raw margins overstate both ends."""
    if not home or not away:
        return margin
    n = min(home[0], away[0])
    if n < MIN_GAMES:
        return margin
    w = SEASON_WEIGHT * min(n, FULL_GAMES) / FULL_GAMES
    season = (home[1] - away[1]) / 2 + edge
    return round((1 - w) * margin + w * season, 1)


def pick(margin_home, spread_home, sd: float, home: str, away: str) -> dict | None:
    """{"side", "team", "line" (that side's spread), "cover", "gap" (shrunk),
    "raw" (unshrunk), "check", "tier"} or None when either number is missing
    or our line sits exactly on the market's. margin_home is already
    stretched and blended."""
    if margin_home is None or spread_home is None:
        return None
    raw = round(margin_home + spread_home, 1)
    if raw == 0:
        return None
    side = "home" if raw > 0 else "away"
    gap = round(abs(raw) * SHRINK, 2)
    sd_eff = sd + SD_PER_POINT * abs(spread_home)
    cover = 0.5 * (1 + math.erf(gap / sd_eff / math.sqrt(2)))
    check = abs(raw) >= CHECK_RAW or (abs(spread_home) >= BIG_SPREAD
                                      and abs(raw) >= CHECK_RAW_BIG)
    return {"side": side, "team": home if side == "home" else away,
            "line": spread_home if side == "home" else -spread_home,
            "cover": round(cover, 4), "gap": round(gap, 1), "raw": abs(raw),
            "check": check, "tier": tier(gap, check)}


def _self_test() -> None:
    _test_calibrated()
    # BPI Ohio State by 21 against -25.5: Marshall +25.5, raw 4.5, gap 2.2.
    p = pick(21.0, -25.5, 11.0, "Ohio State Buckeyes", "Marshall Thundering Herd")
    assert p["side"] == "away" and p["team"] == "Marshall Thundering Herd"
    assert p["line"] == 25.5 and p["raw"] == 4.5 and p["gap"] == 2.2
    # FPI Alabama by 11 against -6.5: Alabama -6.5.
    q = pick(11.0, -6.5, 14.0, "Alabama Crimson Tide", "LSU Tigers")
    assert q["side"] == "home" and q["line"] == -6.5 and q["raw"] == 4.5
    # Underdog at home liked: home +3 when our line says home by 1.
    r = pick(1.0, 3.0, 11.0, "H", "A")
    assert r["side"] == "home" and r["line"] == 3.0 and r["raw"] == 4.0
    # Exactly on the number: no side.
    assert pick(6.5, -6.5, 11.0, "H", "A") is None
    assert pick(None, -3.0, 11.0, "H", "A") is None
    assert pick(3.0, None, 11.0, "H", "A") is None
    # Tiers by edge in points.
    assert (tier(4.0), tier(3.9), tier(2.0), tier(1.9)) == ("best", "lean", "lean", "pass")
    assert tier(9.0, check=True) == "check" and tier(None) is None
    print("ats self-test: all invariants hold")


def _test_calibrated() -> None:
    # Stretch: the market's spread over our margin, through the origin.
    pairs = [(10.0, 12.4), (20.0, 24.8), (-5.0, -6.2)] * 5
    assert fit_stretch(pairs, 1.0) == 1.24
    assert fit_stretch(pairs[:3], 1.1) == 1.1, "too few games: the default"
    assert fit_stretch([(10.0, 30.0)] * 20, 1.0) == STRETCH_MAX, "clamped"
    assert fit_stretch([(10.0, 1.0)] * 20, 1.0) == STRETCH_MIN
    # Blend: nothing under MIN_GAMES; a quarter at 5 games, half from 10.
    assert blend(20.0, (4, 30.0), (9, -20.0), 3.5) == 20.0
    assert blend(20.0, (5, 30.0), (9, -20.0), 3.5) == round(0.75 * 20 + 0.25 * (25 + 3.5), 1)
    assert blend(20.0, (12, 30.0), (10, -20.0), 3.5) == round(0.5 * 20 + 0.5 * 28.5, 1)
    assert blend(20.0, None, (10, 1.0), 3.5) == 20.0
    # Shrunk toward the market, wider SD on bigger spreads.
    p = pick(25.0, -30.0, 11.0, "H", "A")          # raw 5.0 for the dog
    assert p["side"] == "away" and p["raw"] == 5.0 and p["gap"] == 2.5
    sd = 11.0 + SD_PER_POINT * 30
    assert p["cover"] == round(0.5 * (1 + math.erf(2.5 / sd / math.sqrt(2))), 4)
    assert p["tier"] == "lean" and p["check"] is False
    # Check the line: 15+ raw anywhere, or 8+ raw on a 20+ spread.
    assert pick(24.8, -34.5, 11.0, "H", "A")["tier"] == "check"      # raw 9.7
    assert pick(20.0, -12.0, 11.0, "H", "A")["tier"] == "best"       # raw 8 -> 4
    assert pick(10.0, -17.5, 11.0, "H", "A")["tier"] == "lean"       # raw 7.5 -> 3.75
    assert pick(-11.3, 12.5, 14.0, "H", "A")["tier"] == "pass"
    assert pick(12.0, 11.5, 14.0, "H", "A")["tier"] == "check"       # raw 23.5


if __name__ == "__main__":
    _self_test()
