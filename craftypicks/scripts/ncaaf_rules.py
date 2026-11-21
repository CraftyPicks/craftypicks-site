#!/usr/bin/env python3
"""The college football System: the basketball System's rules, scaled to
football (ncaab_rules.py has the originals and why they exist).

Football ranks 136 FBS teams by FPI where basketball ranks 362, and its
spreads bunch at 3 and 7, so each threshold is scaled, not re-fitted:

  SMALL    The underdog gets 7 or fewer on a true home field, with the
           teams within 19 FPI spots (basketball: 6, 50 spots).
  ROAD     An away underdog getting 7.5 to 10.5 (basketball: 6.5 to 9.5).
  DEFENSE  The underdog is the better defense: fewer points allowed, fewer
           yards per play allowed and more takeaways, on one scale.
  FAVBOTTOM  The favourite when a team ranked 113th or better is favoured
           by under 10 against one ranked worse (basketball: 300 of 362).
           It takes the favourite over any underdog rule, at any gap.
  Skip     No underdog play when the teams are 38+ FPI spots apart.
  Wait     The underdog rules need both teams to have played MIN_GAMES:
           with one or two games of stats they lost in September.

Backtest, Aug 29 to Nov 19 (today's FPI ranks, so it flatters): the
favourite rule 57-32 (64%) and steady by month; the underdog rules lost in
September and won in October and November. Football favourites covered 53%
overall, unlike basketball. Every number a play uses comes from games that
started before it. Stdlib only.
"""
from __future__ import annotations

from datetime import datetime

MIN_GAMES = 3
SMALL_DOG, SMALL_GAP = 7.0, 19
ROAD_MIN, ROAD_MAX = 7.0, 10.5
MAX_GAP = 38
LOW_RANK, FAV_MAX = 113, 10.0
# Spread of each stat across FBS teams (Nov 2026), to weigh them evenly.
PA_SD, YPP_SD, TAKE_SD = 6.64, 0.701, 0.412

BACKTEST = {"spread": [155, 103, 0], "through": "2026-11-19",
            "by_reason": {"favbottom": [39, 22], "small": [44, 29], "small+defense": [28, 24],
                          "defense": [23, 13], "road": [15, 10], "road+defense": [6, 5]}}


def _ts(stamp) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def team_forms(store: dict, before) -> dict:
    """{team id: {"n", "pa", "ypp", "take"}} from finals that started before
    `before`: points and yards per play allowed, takeaways per game."""
    acc: dict[str, list] = {}
    for g in (store or {}).get("games", {}).values():
        t = _ts(g.get("commence_time"))
        if (not g.get("completed") or g.get("home_score") is None or t is None
                or before is None or t >= before):
            continue
        box = g.get("box") or {}
        for me, ot in (("home", "away"), ("away", "home")):
            tid, oid = str(g[me]["id"]), str(g[ot]["id"])
            a = acc.setdefault(tid, [0, 0.0, 0.0, 0.0, 0.0])  # n, pa, yds, plays, take
            a[0] += 1
            a[1] += g[f"{ot}_score"]
            ob = box.get(oid) or {}
            if ob.get("yds") is not None and ob.get("plays"):
                a[2] += ob["yds"]
                a[3] += ob["plays"]
            if ob.get("tov") is not None:
                a[4] += ob["tov"]
    return {tid: {"n": n, "pa": pa / n, "ypp": yds / plays if plays else None, "take": tk / n}
            for tid, (n, pa, yds, plays, tk) in acc.items() if n}


def defense(form: dict) -> float:
    """One defensive score: higher is better."""
    return -form["pa"] / PA_SD - form["ypp"] / YPP_SD + form["take"] / TAKE_SD


def _ready(form) -> bool:
    return bool(form) and form["n"] >= MIN_GAMES and form["ypp"] is not None


def plays(spread_home, neutral: bool, home_form: dict | None,
          away_form: dict | None, ranks=(None, None)) -> dict:
    """The System's play for one game: {"side", "reasons"}, as ncaab_rules."""
    out = {"side": None, "reasons": []}
    if spread_home in (None, 0):
        return out
    rh, ra = ranks or (None, None)
    fav, dog = ("home", "away") if spread_home < 0 else ("away", "home")
    if rh is not None and ra is not None and abs(spread_home) < FAV_MAX:
        fr, dr = (rh, ra) if fav == "home" else (ra, rh)
        if fr <= LOW_RANK < dr:
            return {"side": fav, "reasons": ["favbottom"]}
    forms = {"home": home_form, "away": away_form}
    if not all(_ready(f) for f in forms.values()):
        return out
    gap = abs(rh - ra) if rh is not None and ra is not None else None
    if gap is not None and gap >= MAX_GAP:
        return out
    if abs(spread_home) <= SMALL_DOG and not neutral and (gap is None or gap < SMALL_GAP):
        out["reasons"].append("small")
    if dog == "away" and not neutral and ROAD_MIN < abs(spread_home) <= ROAD_MAX:
        out["reasons"].append("road")
    if defense(forms[dog]) > defense(forms[fav]):
        out["reasons"].append("defense")
    if out["reasons"]:
        out["side"] = dog
    return out


def for_game(store: dict, home_id, away_id, commence, spread_home,
             neutral: bool, ranks=(None, None), total=None, conf=None) -> dict:
    """(total and conf are basketball's; football has no total rule.)"""
    forms = team_forms(store, _ts(commence))
    return plays(spread_home, neutral, forms.get(str(home_id)), forms.get(str(away_id)), ranks)


def grade(play: dict, spread_home, home_score, away_score) -> dict:
    out = {"spread": None}
    if play.get("side") and spread_home is not None:
        e = home_score - away_score + spread_home
        if play["side"] == "away":
            e = -e
        out["spread"] = "W" if e > 0 else "L" if e < 0 else "P"
    return out


def _self_test() -> None:
    def g(eid, when, h, a, hs, as_, hbox, abox):
        return {"event_id": eid, "commence_time": when, "completed": True,
                "home": {"id": h}, "away": {"id": a}, "home_score": hs, "away_score": as_,
                "box": {h: hbox, a: abox}}
    def bx(yds, plays, tov):
        return {"yds": yds, "plays": plays, "tov": tov}
    store = {"games": {}}
    # D: three games allowing 10, 4.0 yds/play, forcing 2 turnovers a game.
    # O: three games allowing 35, 7.0 yds/play, forcing none.
    for i in range(3):
        store["games"][f"d{i}"] = g(f"d{i}", f"2026-09-0{i + 1}T23:00Z", "D", f"x{i}", 30, 10,
                                    bx(400, 70, 0), bx(240, 60, 2))
        store["games"][f"o{i}"] = g(f"o{i}", f"2026-09-0{i + 1}T23:00Z", "O", f"y{i}", 38, 35,
                                    bx(450, 70, 1), bx(420, 60, 0))
    f = team_forms(store, _ts("2026-09-10T00:00Z"))
    assert f["D"] == {"n": 3, "pa": 10.0, "ypp": 4.0, "take": 2.0}, f["D"]
    assert f["O"]["pa"] == 35.0 and f["O"]["ypp"] == 7.0 and f["O"]["take"] == 0.0
    assert defense(f["D"]) > defense(f["O"])
    # Home dog by 6.5, better defense: SMALL and DEFENSE.
    assert plays(6.5, False, f["D"], f["O"]) == {"side": "home", "reasons": ["small", "defense"]}
    # Away dog by 9.5, worse defense: ROAD.
    assert plays(-9.5, False, f["D"], f["O"]) == {"side": "away", "reasons": ["road"]}
    assert plays(-11.0, False, f["D"], f["O"])["side"] is None, "past 10.5, worse defense"
    # Wait: a team with two games gets no underdog play; the favourite rule still works.
    two = dict(f["D"], n=2)
    assert plays(6.5, False, two, f["O"])["side"] is None
    assert plays(6.5, False, two, f["O"], ranks=(120, 40)) == {"side": "away", "reasons": ["favbottom"]}
    # Ranks: 38+ apart, no underdog play; SMALL needs under 19.
    assert plays(6.5, False, f["D"], f["O"], ranks=(60, 20))["side"] is None
    assert plays(6.5, False, f["D"], f["O"], ranks=(40, 20))["reasons"] == ["defense"]
    # FAVBOTTOM: favourite 113th or better, dog worse, spread under 10.
    assert plays(-9.5, False, f["O"], f["D"], ranks=(30, 114))["reasons"] == ["favbottom"]
    assert plays(-10.0, False, f["O"], f["D"], ranks=(30, 114))["reasons"] != ["favbottom"]
    assert plays(-3.0, False, f["O"], f["D"], ranks=(114, 120))["reasons"] != ["favbottom"]
    # No leak, and grading.
    assert for_game(store, "D", "O", "2026-09-02T23:00Z", 6.5, False)["side"] is None, \
        "on Sep 2 each has one game"
    assert grade({"side": "home"}, 6.5, 20, 24) == {"spread": "W"}
    assert grade({"side": "away"}, -9.5, 30, 20) == {"spread": "L"}
    print("ncaaf_rules self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
