#!/usr/bin/env python3
"""The college basketball System: plays chosen by rules, not by the rating.

Rules (Nov 2026), tested on every game with a line from Nov 1 to Nov 17.
Each was found on Nov 1-11 and checked on Nov 12-17, which it had never
seen; both held up in both halves:

  DEFENSE  The underdog is the better defensive team: fewer points allowed,
           a better rebound margin and more steals, combined into one score.
           70-43 (62%) against the spread.
  SMALL    The underdog gets 6 points or fewer on a true home court
           (neutral sites left out). 99-63 (61%).

A dog meeting DEFENSE or SMALL is a spread play (143-90, 61%); with the
rank-gap rules below (Nov 18) it is 98-46 (68%), 69% and 67% in the two
halves -- the gaps were chosen on these games, so that is the best case. The bar for
a -110 bet is 52.4%. (An under-at-145+ rule went 276-216 but was dropped,
Nov 18, at the owner's call: the System is spreads only.)

Every number a play uses comes from games that started BEFORE it, so a
page rebuilt after the game cannot leak the result into its own pick.
Teams need MIN_GAMES finals before DEFENSE applies. Stdlib only.
"""
from __future__ import annotations

from datetime import datetime

MIN_GAMES = 2
SMALL_DOG = 6.0
# Power-rank (BPI) gap, Nov 18: the System went 19-28 when the teams were
# 100+ spots apart, so those are skipped; SMALL went 61-27 within 50 spots
# and 38-36 beyond, so it needs the teams within 50.
MAX_GAP = 100
SMALL_GAP = 50
# The spread of each defensive stat across teams this season, used to put
# points allowed (about 11 points), steals (2.5) and rebound margin (8.6)
# on one scale. Measured Nov 2026; they only weigh the three stats.
PA_SD, STL_SD, REB_SD = 10.8, 2.54, 8.6

# The backtest, for the page. Not the record: that is counted forward.
BACKTEST = {"spread": [98, 46, 0], "through": "2026-11-17",
            # Tracked, not played: when DEFENSE fires, the favourite's team
            # total (total/2 + spread/2) going under.
            "tt": [55, 25, 0]}


def _ts(stamp) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def team_forms(store: dict, before) -> dict:
    """{team id: {"n", "pa", "stl", "reb"}} per game, from finals that
    started before `before` (a timestamp). `reb` is the rebound margin."""
    acc: dict[str, list] = {}
    for g in (store or {}).get("games", {}).values():
        t = _ts(g.get("commence_time"))
        if (not g.get("completed") or g.get("home_score") is None or t is None
                or before is None or t >= before):
            continue
        box = g.get("box") or {}
        for me, ot in (("home", "away"), ("away", "home")):
            tid, oid = str(g[me]["id"]), str(g[ot]["id"])
            a = acc.setdefault(tid, [0, 0.0, 0.0, 0.0, 0])  # n, pa, stl, reb margin, boxed
            a[0] += 1
            a[1] += g[f"{ot}_score"]
            mb, ob = box.get(tid) or {}, box.get(oid) or {}
            if mb.get("stl") is not None and mb.get("reb") is not None and ob.get("reb") is not None:
                a[2] += mb["stl"]
                a[3] += mb["reb"] - ob["reb"]
                a[4] += 1
    return {tid: {"n": n, "pa": pa / n, "stl": stl / bx if bx else 0.0,
                  "reb": reb / bx if bx else 0.0}
            for tid, (n, pa, stl, reb, bx) in acc.items() if n}


def defense(form: dict) -> float:
    """One defensive score: higher is better."""
    return -form["pa"] / PA_SD + form["stl"] / STL_SD + form["reb"] / REB_SD


def plays(spread_home, neutral: bool, home_form: dict | None,
          away_form: dict | None, ranks=(None, None)) -> dict:
    """The System's play for one game: {"side": "home"/"away" or None,
    "reasons": [...]}. The side is always the underdog. `ranks` is the
    (home, away) power rank; when either is missing the gap rules are off."""
    out = {"side": None, "reasons": []}
    if spread_home in (None, 0):
        return out
    rh, ra = ranks or (None, None)
    gap = abs(rh - ra) if rh is not None and ra is not None else None
    if gap is not None and gap >= MAX_GAP:
        return out
    dog = "home" if spread_home > 0 else "away"
    if abs(spread_home) <= SMALL_DOG and not neutral and (gap is None or gap < SMALL_GAP):
        out["reasons"].append("small")
    forms = {"home": home_form, "away": away_form}
    if all(f and f["n"] >= MIN_GAMES for f in forms.values()):
        other = "away" if dog == "home" else "home"
        if defense(forms[dog]) > defense(forms[other]):
            out["reasons"].append("defense")
    if out["reasons"]:
        out["side"] = dog
    return out


def for_game(store: dict, home_id, away_id, commence, spread_home,
             neutral: bool, ranks=(None, None)) -> dict:
    """plays() for a game, with each team's form as of its start."""
    forms = team_forms(store, _ts(commence))
    return plays(spread_home, neutral, forms.get(str(home_id)), forms.get(str(away_id)), ranks)


def grade(play: dict, spread_home, home_score, away_score) -> dict:
    """{"spread": "W"/"L"/"P" or None} for a finished game."""
    out = {"spread": None}
    if play.get("side") and spread_home is not None:
        e = home_score - away_score + spread_home
        if play["side"] == "away":
            e = -e
        out["spread"] = "W" if e > 0 else "L" if e < 0 else "P"
    return out


def _self_test() -> None:
    def g(eid, when, h, a, hs, as_, box=None):
        return {"event_id": eid, "commence_time": when, "completed": True,
                "home": {"id": h}, "away": {"id": a}, "home_score": hs, "away_score": as_,
                "box": box or {}}
    def bx(h, a, hreb, areb, hstl, astl):
        return {h: {"reb": hreb, "stl": hstl}, a: {"reb": areb, "stl": astl}}
    store = {"games": {
        "1": g("1", "2026-11-03T23:00Z", "D", "x", 60, 50, bx("D", "x", 40, 30, 10, 4)),
        "2": g("2", "2026-11-06T23:00Z", "y", "D", 55, 65, bx("y", "D", 28, 38, 5, 9)),
        "3": g("3", "2026-11-04T23:00Z", "O", "x", 90, 85, bx("O", "x", 30, 35, 3, 6)),
        "4": g("4", "2026-11-07T23:00Z", "O", "y", 95, 92, bx("O", "y", 31, 36, 4, 7)),
        "5": g("5", "2026-11-20T23:00Z", "D", "O", 70, 60, bx("D", "O", 40, 30, 10, 2)),
    }}
    before = _ts("2026-11-10T00:00Z")
    f = team_forms(store, before)
    assert f["D"] == {"n": 2, "pa": 52.5, "stl": 9.5, "reb": 10.0}, f["D"]
    assert f["O"]["n"] == 2 and f["O"]["pa"] == 88.5 and f["O"]["reb"] == -5.0
    assert team_forms(store, _ts("2026-11-21T00:00Z"))["D"]["n"] == 3, "later cutoff sees game 5"
    assert defense(f["D"]) > defense(f["O"])
    # D is the better defense and the underdog by 8 at home: DEFENSE only.
    p = plays(8.0, False, f["D"], f["O"])
    assert p == {"side": "home", "reasons": ["defense"]}, p
    # Small dog with the worse defense: SMALL only. No total play any more.
    p = plays(-4.5, False, f["D"], f["O"])
    assert p == {"side": "away", "reasons": ["small"]}, p
    # Both rules.
    assert plays(4.0, False, f["D"], f["O"])["reasons"] == ["small", "defense"]
    # A neutral site is not a small-dog play; too few games is not a defense play.
    assert plays(-4.5, True, f["D"], f["O"])["side"] is None
    thin = dict(f["D"], n=1)
    assert plays(8.0, False, thin, f["O"])["side"] is None
    assert plays(0, False, f["D"], f["O"]) == {"side": None, "reasons": []}
    # No leak: a game's own result never feeds its play.
    assert for_game(store, "D", "O", "2026-11-20T23:00Z", 8.0, False)["side"] == "home"
    # Rank gap (BPI): 100+ apart, no play at all; SMALL needs under 50.
    assert plays(4.0, False, f["D"], f["O"], ranks=(30, 60))["reasons"] == ["small", "defense"]
    assert plays(4.0, False, f["D"], f["O"], ranks=(30, 90))["reasons"] == ["defense"], "gap 60: no SMALL"
    assert plays(4.0, False, f["D"], f["O"], ranks=(30, 130))["side"] is None, "gap 100: no play"
    assert plays(-4.5, False, f["D"], f["O"], ranks=(10, 70))["side"] is None, "SMALL only, gap 60"
    assert plays(4.0, False, f["D"], f["O"], ranks=(None, 60))["reasons"] == ["small", "defense"], \
        "a missing rank leaves the gap rules out"
    assert for_game(store, "D", "O", "2026-11-20T23:00Z", 8.0, False, ranks=(5, 200))["side"] is None
    # Grading.
    assert grade({"side": "home"}, 8.0, 60, 65) == {"spread": "W"}
    assert grade({"side": "away"}, -4.5, 70, 60) == {"spread": "L"}
    assert grade({"side": "away"}, -4.0, 70, 66) == {"spread": "P"}
    assert grade({"side": None}, -4.0, 70, 66) == {"spread": None}
    print("ncaab_rules self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
