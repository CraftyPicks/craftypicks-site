#!/usr/bin/env python3
"""Search college basketball over/under angles over six seasons, with the
same discipline as search_ncaab_angles.py (rules chosen on 2021-2025 only,
300+ games, 54%+, break-even in 4 of 5 seasons; then shown on 2026).

Game-level conditions from both teams' season-to-date profiles: pace,
defense, offense, three-point volume and accuracy, both sides' 3PT
defense, and a projected total from season scoring averages against the
closing total. "High"/"low" means above/below that season's median team.

    python research/search_ncaab_totals.py [--hist DIR]
Stdlib only.
"""
from __future__ import annotations

import argparse
import itertools
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import search_ncaab_angles as A  # noqa: E402

KEYS = ("pace", "pa", "pf", "tpm", "tpp", "otpp", "efg", "oefg")


def medians(rows):
    """Per season, the median team on each stat (thresholds only)."""
    out = {}
    for s in A.SEASONS:
        vals = defaultdict(list)
        for r in rows:
            if r["season"] == s:
                for side in ("home", "away"):
                    for k in KEYS:
                        vals[k].append(r["p"][side][k])
        out[s] = {k: statistics.median(v) for k, v in vals.items()}
    return out


def proj_total(r):
    h, a = r["p"]["home"], r["p"]["away"]
    return (h["pf"] + a["pa"]) / 2 + (a["pf"] + h["pa"]) / 2


def conditions(med):
    def both(k, hi):
        return lambda r: all((r["p"][s][k] > med[r["season"]][k]) == hi for s in ("home", "away"))
    c = {
        "both fast pace": both("pace", True), "both slow pace": both("pace", False),
        "both good defense": both("pa", False), "both bad defense": both("pa", True),
        "both good offense": both("pf", True), "both bad offense": both("pf", False),
        "both make many 3s": both("tpm", True), "both make few 3s": both("tpm", False),
        "both shoot 3s well": both("tpp", True), "both shoot 3s poorly": both("tpp", False),
        "both defend 3s well": both("otpp", False), "both defend 3s poorly": both("otpp", True),
        "both efficient (eFG)": both("efg", True), "both inefficient (eFG)": both("efg", False),
        "both allow low eFG": both("oefg", False), "both allow high eFG": both("oefg", True),
        "projection 5+ over line": lambda r: proj_total(r) - r["tot"] >= 5,
        "projection 5+ under line": lambda r: r["tot"] - proj_total(r) >= 5,
        "projection 10+ over line": lambda r: proj_total(r) - r["tot"] >= 10,
        "projection 10+ under line": lambda r: r["tot"] - proj_total(r) >= 10,
    }
    ctx = {
        "Nov-Dec": lambda r: r["month"] in (11, 12), "Jan-Apr": lambda r: r["month"] in (1, 2, 3, 4),
        "neutral": lambda r: r["neutral"], "conference game": lambda r: r["conf"],
        "non-conference": lambda r: not r["conf"],
        "total under 135": lambda r: r["tot"] < 135, "total 135-149.5": lambda r: 135 <= r["tot"] < 150,
        "total 150+": lambda r: r["tot"] >= 150,
        "spread 10+": lambda r: abs(r["sp"]) >= 10, "spread under 5": lambda r: abs(r["sp"]) < 5,
        "Thu-Sat": lambda r: r["wd"] in (3, 4, 5),
    }
    return c, ctx


def result(r, side):
    t = r["hs"] + r["as"] - r["tot"]
    if t == 0:
        return None
    return (t > 0) if side == "over" else (t < 0)


def main(hist: Path) -> None:
    rows = [r for s in A.SEASONS for r in A.rows_for(hist, s) if r["tot"]]
    med = medians(rows)
    conds, ctx = conditions(med)
    by_s = defaultdict(list)
    for r in rows:
        by_s[r["season"]].append(r)
    base = {side: sum(bool(result(r, side)) for r in rows) / len(rows) for side in ("over", "under")}
    print(f"{len(rows)} lined D-I games with a total; overs hit {base['over']:.1%}, unders {base['under']:.1%}")
    tried, keep = 0, []
    names = list(conds)
    for side in ("over", "under"):
        for k in (1, 2):
            for combo in itertools.combinations(names, k):
                for cx in [None] + list(ctx):
                    tried += 1
                    per = {}
                    for s in A.SEASONS:
                        w = l = 0
                        for r in by_s[s]:
                            if not all(conds[c](r) for c in combo) or (cx and not ctx[cx](r)):
                                continue
                            res = result(r, side)
                            if res is None:
                                continue
                            w += res
                            l += not res
                        per[s] = (w, l)
                    bw = sum(per[s][0] for s in A.BUILD)
                    bl = sum(per[s][1] for s in A.BUILD)
                    if bw + bl < A.MIN_N or bw / (bw + bl) < A.MIN_RATE:
                        continue
                    good = sum(1 for s in A.BUILD if sum(per[s]) and per[s][0] / sum(per[s]) >= A.BE)
                    if good < A.MIN_SEASONS:
                        continue
                    name = f"{side.upper()}: {' + '.join(combo)}" + (f", {cx}" if cx else "")
                    keep.append((bw / (bw + bl), name, per))
    keep.sort(reverse=True)
    print(f"{tried} total rules tried; {len(keep)} qualified on {A.BUILD[0]}-{A.BUILD[-1]}\n")
    print(f"{'rule':72}{'2021-2025':20}{'2026 held out':18}by season")
    for rate, name, per in keep:
        bw = sum(per[s][0] for s in A.BUILD)
        bl = sum(per[s][1] for s in A.BUILD)
        seasons = " ".join(f"{100 * w / (w + l):.0f}" if w + l else "-" for w, l in (per[s] for s in A.SEASONS))
        print(f"{name:72}{A.fmt(bw, bl):20}{A.fmt(*per[A.HOLDOUT]):18}{seasons}")
    print("\n52.4% breaks even at -110.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hist", default=str(HERE / "history_ncaab"))
    main(Path(ap.parse_args().hist))
