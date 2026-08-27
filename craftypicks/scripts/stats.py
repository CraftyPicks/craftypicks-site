"""Roll the graded log up into the numbers the site displays."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

# Two-sided normal quantiles. 95% is what the interval is drawn at; 99% is the
# bar the "how many more plays" counter is asked to clear, because a 1-in-20
# result is not evidence of anything in a field this noisy.
Z_95 = 1.96
Z_99 = 2.576

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_key(play: dict) -> str:
    stamp = play.get("posted_date") or (play.get("commence_time") or "")[:10]
    return stamp[:7] if stamp else ""


def roi_interval(profits: list[float], risked: float) -> dict:
    """A confidence interval on ROI, and how many more plays it needs.

    Every figure a betting site publishes is a sample mean, and a sample mean
    without a spread is a number pretending to be a fact. This computes the
    ordinary standard error of the mean profit per play and reports the range
    the record is actually consistent with.

    The normal approximation is doing real work here: a single play's profit
    is roughly two-valued (lose the stake, or win it times the price), which
    is nothing like a bell curve. The mean of many of them converges to one
    regardless, but under about 30 plays the interval below is indicative
    rather than exact, and `approximate` says so rather than leaving a reader
    to assume a precision that isn't there.
    """
    n = len(profits)
    if n < 2 or risked <= 0:
        return {"n": n, "roi": 0.0, "lo": None, "hi": None,
                "needed": None, "approximate": True}

    mean = sum(profits) / n
    # Sample standard deviation, n-1 in the denominator: with a handful of
    # plays the population form understates the spread, which is the exact
    # direction that would flatter the record.
    var = sum((x - mean) ** 2 for x in profits) / (n - 1)
    sd = math.sqrt(var)
    stake_avg = risked / n
    if stake_avg <= 0:
        return {"n": n, "roi": 0.0, "lo": None, "hi": None,
                "needed": None, "approximate": True}

    # ROI is profit over money risked, so convert the interval on mean profit
    # per play into the same units the headline is printed in.
    se = sd / math.sqrt(n)
    roi = mean / stake_avg * 100
    half = Z_95 * se / stake_avg * 100

    # How many plays until a 99% interval would clear zero, holding the
    # observed edge and spread. n* = (z*sd/mean)^2 falls straight out of
    # requiring mean > z*sd/sqrt(n).
    needed = None
    if mean > 0 and sd > 0:
        target = (Z_99 * sd / mean) ** 2
        needed = max(0, math.ceil(target) - n)

    return {
        "n": n,
        "roi": round(roi, 1),
        "lo": round(roi - half, 1),
        "hi": round(roi + half, 1),
        "needed": needed,
        "approximate": n < 30,
    }


def clv_significance(beat: int, n: int) -> float | None:
    """How many standard deviations the beat-the-close rate sits from chance.

    A coin has no edge, so the null is 50%. The standard error of a proportion
    under that null is sqrt(0.25/n), and the whole argument for reporting CLV
    ahead of profit is that this figure grows far faster than the equivalent
    on win/loss — tens of plays rather than thousands.
    """
    if not n:
        return None
    se = math.sqrt(0.25 / n)
    return round(((beat / n) - 0.5) / se, 1)


def compute(history: list[dict]) -> dict:
    graded = [p for p in history if p.get("result")]
    pending = [p for p in history if not p.get("result")]

    wins = sum(1 for p in graded if p["result"] == "win")
    losses = sum(1 for p in graded if p["result"] == "loss")
    pushes = sum(1 for p in graded if p["result"] == "push")
    units = round(sum(p.get("profit", 0.0) for p in graded), 2)
    risked = round(sum(p.get("stake", 1.0) for p in graded), 2)
    decided = wins + losses

    by_league = defaultdict(lambda: {"plays": 0, "w": 0, "l": 0, "p": 0, "units": 0.0, "risked": 0.0})
    for p in graded:
        row = by_league[p.get("league", "—")]
        row["plays"] += 1
        row["units"] += p.get("profit", 0.0)
        row["risked"] += p.get("stake", 1.0)
        row["w" if p["result"] == "win" else "l" if p["result"] == "loss" else "p"] += 1
    league_rows = []
    for name, row in by_league.items():
        dec = row["w"] + row["l"]
        league_rows.append({
            "league": name,
            "plays": row["plays"],
            "record": f"{row['w']}–{row['l']}–{row['p']}",
            "win_pct": round(row["w"] / dec * 100, 1) if dec else 0.0,
            "units": round(row["units"], 2),
            "roi": round(row["units"] / row["risked"] * 100, 1) if row["risked"] else 0.0,
        })
    league_rows.sort(key=lambda r: r["units"], reverse=True)

    monthly = defaultdict(float)
    monthly_counts = defaultdict(int)
    for p in graded:
        key = _month_key(p)
        if key:
            monthly[key] += p.get("profit", 0.0)
            monthly_counts[key] += 1
    months = []
    for key in sorted(monthly):
        year, mon = key.split("-")
        months.append({
            "key": key,
            "label": MONTH_ABBR[int(mon) - 1],
            "year": year,
            "units": round(monthly[key], 2),
            "plays": monthly_counts[key],
        })
    months = months[-12:]

    # Worst peak-to-trough run through the graded log, in order.
    ordered = sorted(graded, key=lambda p: (p.get("posted_date") or "", p.get("graded_at") or ""))
    peak = running = 0.0
    drawdown = 0.0
    for p in ordered:
        running += p.get("profit", 0.0)
        peak = max(peak, running)
        drawdown = min(drawdown, running - peak)

    recent = list(reversed(ordered))[:20]

    # Closing line value — measured on every play with a late line, graded or
    # not. This converges far faster than win/loss, so it is the first honest
    # read on whether the method is finding real prices.
    clv_plays = [p for p in history
                 if p.get("clv_ev") is not None
                 and (p.get("close_minutes_before") or 0) <= 240]
    clv_n = len(clv_plays)
    clv_beat = sum(1 for p in clv_plays if p["clv_ev"] > 0)

    # Split every measure by where the play came from. This is the entire
    # reason both systems run: after a few hundred plays the "vs close"
    # column says which approach is finding real prices, and neither of us
    # gets to argue with it.
    by_source = {}
    for src in sorted({p.get("source", "value") for p in history}):
        rows = [p for p in history if p.get("source", "value") == src]
        r_graded = [p for p in rows if p.get("result")]
        r_clv = [p for p in rows if p.get("clv_ev") is not None
                 and (p.get("close_minutes_before") or 0) <= 240]
        w = sum(1 for p in r_graded if p["result"] == "win")
        l = sum(1 for p in r_graded if p["result"] == "loss")
        pu = sum(1 for p in r_graded if p["result"] == "push")
        # Deliberately not named `units`/`risked`: those hold the whole-record
        # totals computed above, and this loop used to overwrite them, so the
        # headline figures were silently reporting whichever source sorted
        # last instead of the full log.
        src_units = round(sum(p.get("profit", 0.0) for p in r_graded), 2)
        src_risked = sum(p.get("stake", 1.0) for p in r_graded)
        by_source[src] = {
            "source": src,
            "posted": len(rows),
            "graded": len(r_graded),
            "record": f"{w}–{l}–{pu}",
            "units": src_units,
            "roi": round(src_units / src_risked * 100, 1) if src_risked else 0.0,
            "clv_n": len(r_clv),
            "clv_beat_pct": round(sum(1 for p in r_clv if p["clv_ev"] > 0)
                                  / len(r_clv) * 100, 1) if r_clv else 0.0,
            "clv_avg": round(sum(p["clv_ev"] for p in r_clv) / len(r_clv), 2)
                       if r_clv else 0.0,
        }

    return {
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "graded": len(graded),
        "pending": len(pending),
        "wins": wins, "losses": losses, "pushes": pushes,
        "record": f"{wins}–{losses}–{pushes}",
        "win_pct": round(wins / decided * 100, 1) if decided else 0.0,
        "units": units,
        "risked": risked,
        "roi": round(units / risked * 100, 1) if risked else 0.0,
        "drawdown": round(drawdown, 2),
        "losing_months": sum(1 for m in months if m["units"] < 0),
        "total_months": len(months),
        "by_league": league_rows,
        "months": months,
        "recent": recent,
        "clv_n": clv_n,
        "clv_beat": clv_beat,
        "clv_beat_pct": round(clv_beat / clv_n * 100, 1) if clv_n else 0.0,
        "clv_avg": round(sum(p["clv_ev"] for p in clv_plays) / clv_n, 2) if clv_n else 0.0,
        "clv_sigma": clv_significance(clv_beat, clv_n),
        "roi_interval": roi_interval(
            [p.get("profit", 0.0) for p in graded], risked),
        "by_source": list(by_source.values()),
    }


def _self_test() -> None:
    """Invariants that a rename or a stray loop variable would break.

    Kept in the module rather than a test directory because there is no test
    runner in this project — `python scripts/stats.py` is the whole harness.
    """
    log = [
        {"result": "win",  "profit": 0.91, "stake": 1.0, "source": "value",
         "clv_ev": 1.2, "close_minutes_before": 30, "posted_date": "2026-06-01"},
        {"result": "loss", "profit": -1.0, "stake": 1.0, "source": "value",
         "clv_ev": -0.4, "close_minutes_before": 30, "posted_date": "2026-06-01"},
        {"result": "win",  "profit": 1.10, "stake": 1.0, "source": "screen",
         "clv_ev": 2.0, "close_minutes_before": 30, "posted_date": "2026-06-02"},
        {"result": "win",  "profit": 0.87, "stake": 1.0, "source": "screen",
         "clv_ev": 0.3, "close_minutes_before": 30, "posted_date": "2026-06-02"},
        {"source": "value", "posted_date": "2026-06-03"},          # ungraded
    ]
    s = compute(log)

    assert s["graded"] == 4 and s["pending"] == 1, s
    assert abs(s["risked"] - 4.0) < 1e-9, f"risked={s['risked']} (source loop shadowing?)"
    assert abs(s["units"] - 1.88) < 1e-9, f"units={s['units']} (source loop shadowing?)"
    assert abs(sum(r["units"] for r in s["by_source"]) - s["units"]) < 1e-9

    ci = s["roi_interval"]
    assert abs(ci["roi"] - s["roi"]) < 0.05, "headline ROI and its interval disagree"
    assert abs((ci["hi"] - ci["roi"]) - (ci["roi"] - ci["lo"])) < 0.05, "interval not symmetric"
    assert ci["approximate"] is True, "4 plays should be flagged approximate"

    # A losing record has no path to significance and must not offer one.
    losing = compute([{"result": "loss", "profit": -1.0, "stake": 1.0,
                       "posted_date": "2026-06-01"} for _ in range(10)])
    assert losing["roi_interval"]["needed"] is None

    # An empty log must not raise.
    empty = compute([])
    assert empty["graded"] == 0 and empty["roi_interval"]["lo"] is None
    assert empty["clv_sigma"] is None

    # A coin-flip beat rate is zero sigma; nothing measured is None.
    assert clv_significance(25, 50) == 0.0
    assert clv_significance(0, 0) is None
    print("stats self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
