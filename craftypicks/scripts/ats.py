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
"""
from __future__ import annotations

import math

SD = {"ncaab": 11.0, "ncaaf": 14.0}


# Tiers by the point gap between our line and the market's. Starting
# values; the tier records on the page say whether bigger gaps really win
# more often, and these move if they do not.
BEST, LEAN = 6.0, 3.0


def tier(gap) -> str | None:
    """"best" (6+ points), "lean" (3-6), "pass" (under 3), or None."""
    if gap is None:
        return None
    return "best" if gap >= BEST else "lean" if gap >= LEAN else "pass"


def pick(margin_home, spread_home, sd: float, home: str, away: str) -> dict | None:
    """{"side", "team", "line" (that side's spread), "cover", "gap"} or None
    when either number is missing or our line sits exactly on the market's."""
    if margin_home is None or spread_home is None:
        return None
    gap = round(margin_home + spread_home, 1)
    if gap == 0:
        return None
    side = "home" if gap > 0 else "away"
    cover = 0.5 * (1 + math.erf(abs(gap) / sd / math.sqrt(2)))
    return {"side": side, "team": home if side == "home" else away,
            "line": spread_home if side == "home" else -spread_home,
            "cover": round(cover, 4), "gap": abs(gap)}


def _self_test() -> None:
    # BPI Ohio State by 21 against -25.5: Marshall +25.5, 4.5 points.
    p = pick(21.0, -25.5, 11.0, "Ohio State Buckeyes", "Marshall Thundering Herd")
    assert p["side"] == "away" and p["team"] == "Marshall Thundering Herd"
    assert p["line"] == 25.5 and p["gap"] == 4.5
    assert p["cover"] == round(0.5 * (1 + math.erf(4.5 / 11 / math.sqrt(2))), 4) == 0.6588
    # FPI Alabama by 11 against -6.5: Alabama -6.5.
    q = pick(11.0, -6.5, 14.0, "Alabama Crimson Tide", "LSU Tigers")
    assert q["side"] == "home" and q["line"] == -6.5 and q["gap"] == 4.5
    # Underdog at home liked: home +3 when our line says home by 1.
    r = pick(1.0, 3.0, 11.0, "H", "A")
    assert r["side"] == "home" and r["line"] == 3.0 and r["gap"] == 4.0
    # Exactly on the number: no side.
    assert pick(6.5, -6.5, 11.0, "H", "A") is None
    assert pick(None, -3.0, 11.0, "H", "A") is None
    assert pick(3.0, None, 11.0, "H", "A") is None
    # Tiers by edge in points.
    assert (tier(6.0), tier(5.9), tier(3.0), tier(2.9)) == ("best", "lean", "lean", "pass")
    assert tier(None) is None
    print("ats self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
