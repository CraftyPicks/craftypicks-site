"""Roll the graded log up into the numbers the site displays."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_key(play: dict) -> str:
    stamp = play.get("posted_date") or (play.get("commence_time") or "")[:10]
    return stamp[:7] if stamp else ""


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
    }
