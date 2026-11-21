#!/usr/bin/env python3
"""Search college basketball spread and total angles over six seasons,
without fooling ourselves (research/history_ncaab, from fetch_cbbd_history).

Discipline, because a search this wide will always find something:

  * every feature is known before tip-off: season-to-date stats from earlier
    games (3+ boxed), game-day Elo rank among D-I, rest days, the closing line;
  * rules are chosen on 2021-2025 only. To qualify: 300+ games, 54%+ overall,
    and 52.4%+ (break-even at -110) in at least 4 of the 5 seasons;
  * only qualifiers are then shown on 2026, which chose nothing;
  * the number of rules tried is printed, so a lucky one can be weighed.

    python research/search_ncaab_angles.py [--hist DIR]
Stdlib only.
"""
from __future__ import annotations

import argparse
import gzip
import itertools
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEASONS = (2021, 2022, 2023, 2024, 2025, 2026)
BUILD, HOLDOUT = SEASONS[:-1], SEASONS[-1]
BE = 0.5238
MIN_N, MIN_RATE, MIN_SEASONS = 300, 0.54, 4


def _load(hist, s, k):
    with gzip.open(hist / f"{s}_{k}.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


STATS = ("pf", "pa", "stl", "rebm", "tpm", "tpp", "otpp", "tovf", "tov", "pace", "efg", "oefg", "ats")


def rows_for(hist: Path, season: int) -> list[dict]:
    """One row per lined D-I game, with each side's season-to-date profile."""
    lines = {g["gameId"]: g for g in _load(hist, season, "lines")}
    box = defaultdict(dict)
    for t in _load(hist, season, "teams"):
        ts, os_ = t.get("teamStats") or {}, t.get("opponentStats") or {}
        def g(d, *ks):
            for k in ks:
                d = (d or {}).get(k)
            return d
        box[t["gameId"]][t["teamId"]] = {
            "stl": g(ts, "steals"), "reb": g(ts, "rebounds", "total"), "oreb": g(os_, "rebounds", "total"),
            "tpm": g(ts, "threePointFieldGoals", "made"), "tpa": g(ts, "threePointFieldGoals", "attempted"),
            "otpm": g(os_, "threePointFieldGoals", "made"), "otpa": g(os_, "threePointFieldGoals", "attempted"),
            "tov": g(ts, "turnovers", "total"), "tovf": g(os_, "turnovers", "total"),
            "pace": g(ts, "possessions"),
            "efg": g(ts, "fourFactors", "effectiveFieldGoalPct"),
            "oefg": g(os_, "fourFactors", "effectiveFieldGoalPct")}
    games = sorted((g for g in _load(hist, season, "games")
                    if g.get("status") == "final" and g.get("homePoints") is not None),
                   key=lambda g: (g["startDate"], g["id"]))
    acc = defaultdict(lambda: defaultdict(float))
    last_day: dict[int, datetime] = {}
    elo: dict[int, float] = {}
    d1: set[int] = set()
    out = []
    i = 0
    while i < len(games):
        day = games[i]["startDate"][:10]
        j = i
        while j < len(games) and games[j]["startDate"][:10] == day:
            j += 1
        batch = games[i:j]
        for gm in batch:
            for side in ("home", "away"):
                e = gm.get(f"{side}TeamEloStart")
                if e is not None and gm.get(f"{side}Conference") is not None:
                    d1.add(gm[f"{side}TeamId"])
                    elo[gm[f"{side}TeamId"]] = e
        ranks = {t: k + 1 for k, t in enumerate(sorted((t for t in d1 if t in elo), key=lambda t: -elo[t]))}

        def prof(t):
            a = acc.get(t)
            if not a or a["bx"] < 3:
                return None
            n, bx = a["n"], a["bx"]
            return {"pf": a["pf"] / n, "pa": a["pa"] / n, "stl": a["stl"] / bx, "rebm": a["rebm"] / bx,
                    "tpm": a["tpm"] / bx, "tpp": a["tpm"] / a["tpa"] if a["tpa"] else 0,
                    "otpp": a["otpm"] / a["otpa"] if a["otpa"] else 0, "tovf": a["tovf"] / bx,
                    "tov": a["tov"] / bx, "pace": a["pace"] / bx, "efg": a["efg"] / bx, "oefg": a["oefg"] / bx,
                    "ats": (a["atsw"] / (a["atsw"] + a["atsl"])) if a["atsw"] + a["atsl"] >= 3 else None}
        for gm in batch:
            h, a_ = gm["homeTeamId"], gm["awayTeamId"]
            if gm.get("homeConference") is None or gm.get("awayConference") is None:
                continue
            ln = (lines.get(gm["id"]) or {}).get("lines") or []
            sp = [x["spread"] for x in ln if x.get("spread") is not None]
            tot = [x["overUnder"] for x in ln if x.get("overUnder") is not None]
            ph, pa = prof(h), prof(a_)
            if not sp or not ph or not pa:
                continue
            sp = statistics.median(sp)
            start = datetime.fromisoformat(gm["startDate"].replace("Z", "+00:00"))
            local = start - timedelta(hours=5)
            rest = {t: (start - last_day[t]).days if t in last_day else None for t in (h, a_)}
            out.append({
                "season": season, "month": local.month, "wd": local.weekday(),
                "neutral": bool(gm.get("neutralSite")), "conf": bool(gm.get("conferenceGame")),
                "sp": sp, "tot": statistics.median(tot) if tot else None,
                "hs": gm["homePoints"], "as": gm["awayPoints"],
                "rk": {"home": ranks.get(h), "away": ranks.get(a_)},
                "rest": {"home": rest[h], "away": rest[a_]},
                "p": {"home": ph, "away": pa}})
        for gm in batch:
            margin = gm["homePoints"] - gm["awayPoints"]
            ln = (lines.get(gm["id"]) or {}).get("lines") or []
            sp = [x["spread"] for x in ln if x.get("spread") is not None]
            spm = statistics.median(sp) if sp else None
            for side, opp, mine, theirs in (("home", "away", gm["homePoints"], gm["awayPoints"]),
                                            ("away", "home", gm["awayPoints"], gm["homePoints"])):
                t = gm[f"{side}TeamId"]
                A = acc[t]
                A["n"] += 1
                A["pf"] += mine
                A["pa"] += theirs
                if spm is not None:
                    e = margin + spm if side == "home" else -(margin + spm)
                    A["atsw"] += e > 0
                    A["atsl"] += e < 0
                b = (box.get(gm["id"]) or {}).get(t) or {}
                if all(b.get(k) is not None for k in ("stl", "reb", "oreb", "tpm", "tpa", "otpm", "otpa",
                                                       "tov", "tovf", "pace", "efg", "oefg")):
                    A["bx"] += 1
                    A["stl"] += b["stl"]
                    A["rebm"] += b["reb"] - b["oreb"]
                    for k in ("tpm", "tpa", "otpm", "otpa", "tov", "tovf", "pace", "efg", "oefg"):
                        A[k] += b[k]
                last_day[t] = datetime.fromisoformat(gm["startDate"].replace("Z", "+00:00"))
        i = j
    return out


# ------------------------------------------------------------------ rules
def _cmp(stat, better_high=True):
    def f(me, op):
        a, b = me[stat], op[stat]
        if a is None or b is None:
            return None
        return a > b if better_high else a < b
    return f


EDGES = {   # "me" (the side we would bet) has the better ...
    "defense (pts allowed)": _cmp("pa", False), "offense (pts scored)": _cmp("pf"),
    "steals": _cmp("stl"), "rebound margin": _cmp("rebm"), "3PT made": _cmp("tpm"),
    "3PT%": _cmp("tpp"), "3PT% allowed": _cmp("otpp", False), "turnovers forced": _cmp("tovf"),
    "ball security": _cmp("tov", False), "eFG%": _cmp("efg"), "eFG% allowed": _cmp("oefg", False),
    "faster pace": _cmp("pace"), "slower pace": _cmp("pace", False), "ATS record": _cmp("ats"),
}
CONTEXT = {
    "Nov-Dec": lambda r, s: r["month"] in (11, 12), "Jan-Apr": lambda r, s: r["month"] in (1, 2, 3, 4),
    "home": lambda r, s: not r["neutral"] and s == "home", "away": lambda r, s: not r["neutral"] and s == "away",
    "neutral": lambda r, s: r["neutral"], "conference game": lambda r, s: r["conf"],
    "non-conference": lambda r, s: not r["conf"],
    "spread 1-5": lambda r, s: abs(r["sp"]) <= 5, "spread 5.5-9.5": lambda r, s: 5 < abs(r["sp"]) < 10,
    "spread 10+": lambda r, s: abs(r["sp"]) >= 10,
    "rank gap <50": lambda r, s: _gap(r) is not None and _gap(r) < 50,
    "rank gap 100+": lambda r, s: _gap(r) is not None and _gap(r) >= 100,
    "more rest": lambda r, s: _rest(r, s) is not None and _rest(r, s) > 0,
    "less rest": lambda r, s: _rest(r, s) is not None and _rest(r, s) < 0,
    "Thu-Sat": lambda r, s: r["wd"] in (3, 4, 5),
}


def _gap(r):
    a, b = r["rk"]["home"], r["rk"]["away"]
    return abs(a - b) if a and b else None


def _rest(r, s):
    o = "away" if s == "home" else "home"
    a, b = r["rest"][s], r["rest"][o]
    return None if a is None or b is None else a - b


def spread_result(r, side):
    e = r["hs"] - r["as"] + r["sp"]
    if side == "away":
        e = -e
    return None if e == 0 else e > 0


def candidates():
    """(name, side picker, filter) for every rule tried."""
    roles = {"underdog": lambda r: "home" if r["sp"] > 0 else "away",
             "favorite": lambda r: "home" if r["sp"] < 0 else "away"}
    edges = list(EDGES.items())
    for role, pick in roles.items():
        for ctx in [None] + list(CONTEXT):
            for k in (1, 2):
                for combo in itertools.combinations(edges, k):
                    name = f"{role} with better {' + '.join(n for n, _ in combo)}" + (f", {ctx}" if ctx else "")
                    def flt(r, side, combo=combo, ctx=ctx):
                        o = "away" if side == "home" else "home"
                        me, op = r["p"][side], r["p"][o]
                        for _, f in combo:
                            v = f(me, op)
                            if not v:
                                return False
                        return ctx is None or CONTEXT[ctx](r, side)
                    yield name, pick, flt


def evaluate(rows):
    by_season = defaultdict(list)
    for r in rows:
        by_season[r["season"]].append(r)
    tried = 0
    keep = []
    for name, pick, flt in candidates():
        tried += 1
        per = {}
        for s in SEASONS:
            w = l = 0
            for r in by_season[s]:
                side = pick(r)
                if not flt(r, side):
                    continue
                res = spread_result(r, side)
                if res is None:
                    continue
                w += res
                l += not res
            per[s] = (w, l)
        bw = sum(per[s][0] for s in BUILD)
        bl = sum(per[s][1] for s in BUILD)
        if bw + bl < MIN_N or bw / (bw + bl) < MIN_RATE:
            continue
        good = sum(1 for s in BUILD if sum(per[s]) and per[s][0] / sum(per[s]) >= BE)
        if good < MIN_SEASONS:
            continue
        keep.append((bw / (bw + bl), name, per))
    return tried, sorted(keep, reverse=True)


def fmt(w, l):
    return f"{w}-{l} ({100 * w / (w + l):.1f}%)" if w + l else "-"


def main(hist: Path) -> None:
    rows = [r for s in SEASONS for r in rows_for(hist, s)]
    print(f"{len(rows)} lined D-I games with season-to-date stats, {SEASONS[0]}-{SEASONS[-1]}")
    tried, keep = evaluate(rows)
    print(f"{tried} spread rules tried; {len(keep)} qualified on {BUILD[0]}-{BUILD[-1]} "
          f"({MIN_N}+ games, {MIN_RATE:.0%}+, break-even in {MIN_SEASONS}+ of {len(BUILD)} seasons)\n")
    print(f"{'rule':74}{'2021-2025':20}{'2026 held out':18}by season")
    for rate, name, per in keep:
        bw = sum(per[s][0] for s in BUILD)
        bl = sum(per[s][1] for s in BUILD)
        seasons = " ".join(f"{100 * w / (w + l):.0f}" if w + l else "-" for w, l in (per[s] for s in SEASONS))
        print(f"{name:74}{fmt(bw, bl):20}{fmt(*per[HOLDOUT]):18}{seasons}")
    print("\n52.4% breaks even at -110.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hist", default=str(ROOT / "research" / "history_ncaab"))
    main(Path(ap.parse_args().hist))
