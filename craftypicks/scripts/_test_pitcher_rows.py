"""The shape pitchers.build() puts on a row, checked without the network."""
import sys
sys.path.insert(0, "scripts")

import matchup
from pitchers import opponent_split

# Real 2026 figures, so these assertions are checkable against the site.
TABLE = {
    113: {"vR": {"k_pct": 25.4, "k": 1015, "pa": 3989},
          "vL": {"k_pct": 25.0, "k": 307, "pa": 1230}},
    141: {"vR": {"k_pct": 18.9, "k": 693, "pa": 3665},
          "vL": {"k_pct": 20.6, "k": 311, "pa": 1510}},
    120: {"vR": {"k_pct": 20.6, "k": 798, "pa": 3865},
          "vL": {"k_pct": 23.9, "k": 374, "pa": 1563}},
}


def main() -> int:
    summary = matchup.summarise(TABLE)

    # A right-hander facing Cincinnati looks at the vR column.
    row = opponent_split(TABLE, summary, 113, "R")
    assert round(row["k_pct"], 1) == 25.4, row
    assert row["pa"] == 3989
    assert row["rank"] == 1 and row["of"] == 3, row
    assert row["rank_all"] == 1, row

    # The same club, a left-hander, is a different number.
    assert round(opponent_split(TABLE, summary, 113, "L")["k_pct"], 1) == 25.0

    # Washington is the reordering case: better against lefties than righties,
    # so the hand decides which rank applies.
    wsh_l = opponent_split(TABLE, summary, 120, "L")
    wsh_r = opponent_split(TABLE, summary, 120, "R")
    assert wsh_l["k_pct"] > wsh_r["k_pct"], (wsh_l, wsh_r)

    # No hand, or an unknown club, yields nothing rather than a wrong number.
    assert opponent_split(TABLE, summary, 113, "") is None
    assert opponent_split(TABLE, summary, 404, "R") is None

    # And the verdict never raises on a missing input.
    assert matchup.verdict(TABLE, summary, 404, "R") == "neutral"
    assert matchup.verdict(TABLE, summary, 113, "") == "neutral"

    print("pitcher row self-test: all invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
