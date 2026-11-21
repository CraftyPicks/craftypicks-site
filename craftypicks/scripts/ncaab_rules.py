#!/usr/bin/env python3
"""The college basketball System: two rules that passed a six-season test.

Chosen on 2020-21 through 2024-25 and checked on 2025-26, which chose
nothing (research/search_ncaab_angles.py, search_ncaab_totals.py, on
CollegeBasketballData history; every stat as of the game, closing lines):

  BIGDOG  The underdog getting 10 or more, when it allows fewer points per
          game than the favourite, or has more steals AND forces more
          turnovers. 1656-1351 (55.1%), break-even or better in all six
          seasons, 57% in the held-out one. All season.
  UNDER   The under in a non-conference game when both teams defend shots
          poorly: both allow an above-median effective FG% and 3PT%.
          449-330 (57.6%), 55%+ in every season. Non-conference games are
          nearly all November-December; where the flag is unknown, those
          months stand in (56.6% over the same seasons).

They replace the Nov 2026 rules (small dog, defense dog, road dog, favourite
vs 300+), which looked like 61-69% on two weeks but went 50.3% over six
seasons once graded without hindsight. The bar for -110 is 52.4%.

Every number a play uses comes from games that started BEFORE it, so a
page rebuilt after the game cannot leak the result into its own pick.
Stdlib only.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta

BIG_DOG = 10.0       # BIGDOG: the underdog gets at least this many
MIN_BOX = 3          # box scores a team needs before its stats are used
UNDER_MONTHS = (11, 12)   # UNDER's window when the conference flag is unknown

BACKTEST = {"spread": [1656, 1351, 0], "total": [449, 330, 0],
            "through": "2026-04-06", "seasons": "2020-21 to 2025-26",
            "by_reason": {"bigdog": [1656, 1351], "under": [449, 330]}}


def _ts(stamp) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def team_forms(store: dict, before) -> dict:
    """{team id: form} from finals that started before `before` (a timestamp):
    n and pa (points allowed) from every final; stl and tovf (turnovers
    forced) from box scores (`box`); oefg and otpp (opponents' effective
    FG% and 3PT%) from box scores carrying three-pointers (`shot`)."""
    acc: dict[str, dict] = {}
    for g in (store or {}).get("games", {}).values():
        t = _ts(g.get("commence_time"))
        if (not g.get("completed") or g.get("home_score") is None or t is None
                or before is None or t >= before):
            continue
        box = g.get("box") or {}
        for me, ot in (("home", "away"), ("away", "home")):
            tid, oid = str(g[me]["id"]), str(g[ot]["id"])
            a = acc.setdefault(tid, {"n": 0, "pa": 0.0, "box": 0, "stl": 0.0, "tovf": 0.0,
                                     "shot": 0, "ofgm": 0, "ofga": 0, "otpm": 0, "otpa": 0})
            a["n"] += 1
            a["pa"] += g[f"{ot}_score"]
            mb, ob = box.get(tid) or {}, box.get(oid) or {}
            if mb.get("stl") is not None and ob.get("tov") is not None:
                a["box"] += 1
                a["stl"] += mb["stl"]
                a["tovf"] += ob["tov"]
            if all(ob.get(k) is not None for k in ("fgm", "fga", "tpm", "tpa")) and ob["fga"]:
                a["shot"] += 1
                for k in ("fgm", "fga", "tpm", "tpa"):
                    a[f"o{k}"] += ob[k]
    out = {}
    for tid, a in acc.items():
        out[tid] = {
            "n": a["n"], "pa": a["pa"] / a["n"], "box": a["box"],
            "stl": a["stl"] / a["box"] if a["box"] else None,
            "tovf": a["tovf"] / a["box"] if a["box"] else None,
            "shot": a["shot"],
            "oefg": (a["ofgm"] + 0.5 * a["otpm"]) / a["ofga"] if a["ofga"] else None,
            "otpp": a["otpm"] / a["otpa"] if a["otpa"] else None}
    return out


def medians(forms: dict) -> dict:
    """The median team's oefg and otpp, over teams with MIN_BOX shot boxes."""
    pool = [f for f in forms.values() if f["shot"] >= MIN_BOX]
    return {k: statistics.median(f[k] for f in pool) if pool else None for k in ("oefg", "otpp")}


def _bigdog(dog: dict | None, fav: dict | None) -> bool:
    if not dog or not fav or min(dog["box"], fav["box"]) < MIN_BOX:
        return False
    if dog["pa"] < fav["pa"]:
        return True
    return dog["stl"] > fav["stl"] and dog["tovf"] > fav["tovf"]


def _poor_shot_defense(f: dict | None, med: dict) -> bool:
    return (bool(f) and f["shot"] >= MIN_BOX and med.get("oefg") is not None
            and f["oefg"] > med["oefg"] and f["otpp"] > med["otpp"])


def plays(spread_home, neutral: bool, home_form: dict | None, away_form: dict | None,
          ranks=(None, None), total=None, conf=None, month=None, med=None) -> dict:
    """The System's plays for one game: {"side": the underdog or None,
    "reasons": ["bigdog"] or [], "under": bool}. `conf` is whether it is a
    conference game (None when unknown); `month` the game's month."""
    out = {"side": None, "reasons": [], "under": False}
    if spread_home not in (None, 0) and abs(spread_home) >= BIG_DOG:
        dog, fav = ("home", "away") if spread_home > 0 else ("away", "home")
        forms = {"home": home_form, "away": away_form}
        if _bigdog(forms[dog], forms[fav]):
            out["side"], out["reasons"] = dog, ["bigdog"]
    window = (conf is False) if conf is not None else (month in UNDER_MONTHS)
    if (total is not None and window and med
            and _poor_shot_defense(home_form, med) and _poor_shot_defense(away_form, med)):
        out["under"] = True
    return out


def for_game(store: dict, home_id, away_id, commence, spread_home, neutral: bool,
             ranks=(None, None), total=None, conf=None) -> dict:
    """plays() for a game, with each team's form as of its start."""
    t = _ts(commence)
    forms = team_forms(store, t)
    month = (datetime.fromtimestamp(t) - timedelta(hours=5)).month if t is not None else None
    return plays(spread_home, neutral, forms.get(str(home_id)), forms.get(str(away_id)),
                 ranks, total, conf, month, medians(forms))


def grade(play: dict, spread_home, home_score, away_score, total=None) -> dict:
    """{"spread": "W"/"L"/"P" or None, "total": ...} for a finished game."""
    out = {"spread": None, "total": None}
    if play.get("side") and spread_home is not None:
        e = home_score - away_score + spread_home
        if play["side"] == "away":
            e = -e
        out["spread"] = "W" if e > 0 else "L" if e < 0 else "P"
    if play.get("under") and total is not None:
        d = home_score + away_score - total
        out["total"] = "W" if d < 0 else "L" if d > 0 else "P"
    return out


def _self_test() -> None:
    def g(eid, day, h, a, hs, as_, hbox, abox):
        return {"event_id": eid, "commence_time": f"2026-11-{day:02d}T23:00Z", "completed": True,
                "home": {"id": h}, "away": {"id": a}, "home_score": hs, "away_score": as_,
                "box": {h: hbox, a: abox}}

    def bx(stl, tov, fgm, fga, tpm, tpa):
        return {"stl": stl, "tov": tov, "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa}
    store = {"games": {}}
    # D: allows 60, 9 steals, forces 15; opponents shoot 20-60 (5-20 from 3).
    # B: allows 85, 5 steals, forces 10; opponents shoot 32-60 (10-25 from 3).
    # P: allows 80; opponents shoot 30-60 (9-24). Two more average teams set the median.
    for i in range(3):
        d = 2 + i
        store["games"][f"d{i}"] = g(f"d{i}", d, "D", f"x{i}", 75, 60, bx(9, 10, 28, 60, 7, 20), bx(4, 15, 20, 60, 5, 20))
        store["games"][f"b{i}"] = g(f"b{i}", d, "B", f"y{i}", 90, 85, bx(5, 10, 33, 60, 9, 22), bx(6, 10, 32, 60, 10, 25))
        store["games"][f"p{i}"] = g(f"p{i}", d, "P", f"z{i}", 82, 80, bx(6, 11, 31, 60, 8, 21), bx(6, 11, 30, 60, 9, 24))
        store["games"][f"m{i}"] = g(f"m{i}", d, "M", f"w{i}", 70, 70, bx(6, 11, 25, 60, 6, 20), bx(6, 11, 25, 60, 6, 20))
        store["games"][f"n{i}"] = g(f"n{i}", d, "N", f"v{i}", 70, 70, bx(6, 11, 26, 60, 6, 21), bx(6, 11, 26, 60, 6, 21))
    f = team_forms(store, _ts("2026-11-10T00:00Z"))
    assert f["D"]["n"] == 3 and f["D"]["pa"] == 60 and f["D"]["stl"] == 9 and f["D"]["tovf"] == 15
    assert abs(f["D"]["oefg"] - (20 + 2.5) / 60) < 1e-9 and f["D"]["otpp"] == 0.25
    med = medians(f)
    # BIGDOG: D getting 12 at B -- fewer points allowed.
    p = plays(-12.0, False, f["B"], f["D"], med=med, month=11)
    assert p["side"] == "away" and p["reasons"] == ["bigdog"], p
    assert plays(-9.5, False, f["B"], f["D"], med=med)["side"] is None, "under 10 points"
    assert plays(12.0, False, f["B"], f["D"], med=med)["side"] is None, "the dog B is worse"
    # Steals AND turnovers forced also qualify, either alone does not.
    dog = dict(f["B"], pa=99.0, stl=10.0, tovf=16.0)   # beats D's 9 and 15
    assert plays(12.0, False, dog, f["D"], med=med)["side"] == "home"
    assert plays(12.0, False, dict(dog, tovf=1.0), f["D"], med=med)["side"] is None
    thin = dict(f["D"], box=2)
    assert plays(-12.0, False, f["B"], thin, med=med)["side"] is None, "too few box scores"
    # UNDER: B and P both defend shots poorly; non-conference, total posted.
    assert plays(-3.0, False, f["B"], f["P"], total=150.0, conf=False, med=med)["under"]
    assert not plays(-3.0, False, f["B"], f["P"], total=150.0, conf=True, med=med)["under"], "conference game"
    assert not plays(-3.0, False, f["B"], f["D"], total=150.0, conf=False, med=med)["under"], "D defends well"
    assert not plays(-3.0, False, f["B"], f["P"], total=None, conf=False, med=med)["under"], "no total"
    assert plays(-3.0, False, f["B"], f["P"], total=150.0, month=12, med=med)["under"], "flag unknown: December"
    assert not plays(-3.0, False, f["B"], f["P"], total=150.0, month=1, med=med)["under"], "flag unknown: January"
    # for_game: forms as of the start; no leak from the game itself.
    store["games"]["late"] = g("late", 20, "B", "D", 90, 60, bx(5, 10, 33, 60, 9, 22), bx(4, 15, 20, 60, 5, 20))
    q = for_game(store, "B", "D", "2026-11-20T23:00Z", -12.0, False, total=150.0, conf=True)
    assert q["side"] == "away" and not q["under"]
    assert team_forms(store, _ts("2026-11-20T23:00Z"))["B"]["n"] == 3, "its own result is not in"
    # Grading both kinds.
    assert grade({"side": "away", "under": True}, -12.0, 80, 70, 155.0) == {"spread": "W", "total": "W"}
    assert grade({"side": "home", "under": False}, 12.0, 60, 75, 140.0) == {"spread": "L", "total": None}
    assert grade({"side": None, "under": True}, -3.0, 80, 70, 150.0) == {"spread": None, "total": "P"}
    print("ncaab_rules self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
