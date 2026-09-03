"""Is tonight's lineup a good one to strike out?

The judgement is deliberately made against the hand the starter actually
throws with, not against the club's overall rate. Washington is 18th in
baseball at striking out, which reads as ordinary -- but 10th against
left-handers and 24th against right-handers. A right-hander facing them is in
the 24th-place matchup, and the overall rank hides that.

Nothing here feeds a projection. It is a label for a reader, and on the
evidence so far it should stay one: scripts/study_matchup.py measured this
signal against 86 finished starts and found no detectable edge over the
posted line.
"""
from __future__ import annotations

import statistics

# How far from the league average a club has to sit before the matchup is
# worth naming. Half a standard deviation, which is the band the rest of the
# site already uses for its neutral zones. Wider and nothing is ever notable;
# narrower and every card shouts.
BAND_SD = 0.5

HANDS = ("vL", "vR")

# The combined rate is summed from the two splits rather than averaged: a club
# faces roughly two and a half times as many right-handers as left-handers, so
# a straight mean of the two percentages is not the club's actual rate.
ALL = "all"


def key_for(hand: str) -> str:
    """The column a pitcher of this hand is measured against."""
    return "vL" if hand == "L" else "vR" if hand == "R" else ""


def combined(club: dict) -> float | None:
    """A club's strikeout rate against everybody, from its two splits."""
    if "vL" not in club or "vR" not in club:
        return None
    k = club["vL"]["k"] + club["vR"]["k"]
    pa = club["vL"]["pa"] + club["vR"]["pa"]
    return 100.0 * k / pa if pa else None


def summarise(table: dict[int, dict]) -> dict:
    """League mean, spread and rank for each hand, and for both combined.

    Rank 1 is the club that strikes out most, because a high rank should mean
    a good matchup for the pitcher.
    """
    out = {}
    for hand_key in HANDS + (ALL,):
        if hand_key == ALL:
            values = {tid: c for tid, c in
                      ((tid, combined(v)) for tid, v in table.items())
                      if c is not None}
        else:
            values = {tid: v[hand_key]["k_pct"] for tid, v in table.items()
                      if hand_key in v}
        if not values:
            out[hand_key] = {"mean": 0.0, "sd": 0.0, "rank": {}, "n": 0}
            continue
        order = sorted(values, key=lambda tid: -values[tid])
        out[hand_key] = {
            "mean": statistics.mean(values.values()),
            "sd": statistics.pstdev(values.values()),
            "rank": {tid: i + 1 for i, tid in enumerate(order)},
            "n": len(values),
        }
    return out


def verdict(table: dict[int, dict], summary: dict,
            team_id: int, hand: str) -> str:
    """"favourable", "tough" or "neutral" -- never an exception.

    An unknown club, a club missing that split, or a starter whose hand we
    could not read all come back neutral. A missing input is not a tough
    matchup, and drawing one would be a lie told in colour.
    """
    hand_key = key_for(hand)
    if not hand_key:
        return "neutral"
    club = (table or {}).get(team_id) or {}
    stats = (summary or {}).get(hand_key) or {}
    if hand_key not in club or not stats.get("sd"):
        return "neutral"
    delta = club[hand_key]["k_pct"] - stats["mean"]
    if delta >= stats["sd"] * BAND_SD:
        return "favourable"
    if delta <= -stats["sd"] * BAND_SD:
        return "tough"
    return "neutral"


def _self_test() -> None:
    table = {
        1: {"vR": {"k_pct": 25.0, "k": 1000, "pa": 4000},
            "vL": {"k_pct": 25.0, "k": 375, "pa": 1500}},
        2: {"vR": {"k_pct": 22.0, "k": 880, "pa": 4000},
            "vL": {"k_pct": 22.0, "k": 330, "pa": 1500}},
        3: {"vR": {"k_pct": 19.0, "k": 760, "pa": 4000},
            "vL": {"k_pct": 19.0, "k": 285, "pa": 1500}},
    }
    s = summarise(table)
    assert round(s["vR"]["mean"], 2) == 22.0, s["vR"]["mean"]
    assert s["vR"]["rank"] == {1: 1, 2: 2, 3: 3}, s["vR"]["rank"]

    # Combined is summed, not averaged. Club 1 splits evenly so it lands on
    # 25.0 either way; the arithmetic is checked on a lopsided club below.
    assert round(combined(table[1]), 2) == 25.0, combined(table[1])
    assert s["all"]["rank"] == {1: 1, 2: 2, 3: 3}, s["all"]["rank"]
    lopsided = {"vR": {"k_pct": 20.0, "k": 800, "pa": 4000},
                "vL": {"k_pct": 30.0, "k": 300, "pa": 1000}}
    # (800 + 300) / (4000 + 1000) = 22.0, not the 25.0 a plain mean would give.
    assert round(combined(lopsided), 2) == 22.0, combined(lopsided)

    assert verdict(table, s, 1, "R") == "favourable"
    assert verdict(table, s, 3, "R") == "tough"
    assert verdict(table, s, 2, "R") == "neutral"

    # The hand selects the column. Give club 2 a big platoon gap and it
    # changes verdict for a lefty without moving for a righty.
    table[2]["vL"] = {"k_pct": 27.0, "k": 405, "pa": 1500}
    s2 = summarise(table)
    assert verdict(table, s2, 2, "R") == "neutral"
    assert verdict(table, s2, 2, "L") == "favourable"

    # An unknown club or a missing hand is neutral, never a crash.
    assert verdict(table, s, 404, "R") == "neutral"
    assert verdict(table, s, 1, "") == "neutral"
    print("matchup self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
