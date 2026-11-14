#!/usr/bin/env python3
"""The NCAAF board: every FBS game in the next week, ESPN only.

Our number is ESPN FPI: points better than an average FBS team on a neutral
field. Expected margin = FPI(home) - FPI(away) + HOME_EDGE (zero at a neutral
site, which is every bowl and playoff game); win probability is the normal
CDF of that margin over MARGIN_SD. It is shown against the market's own
probability (ESPN's moneyline, vig removed) and graded every morning, so the
record says whether it is worth anything.

NCAAF is deliberately not in leagues.LEAGUES or config.LEAGUES: those decide
what the Odds API buys. Nothing here spends a credit.
"""
from __future__ import annotations

import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ncaab_system as nsys  # noqa: E402  -- store helpers, name_key, io

HOME_EDGE = 2.5
MARGIN_SD = 14.0
WINDOW_DAYS = 7
SEASON_MONTHS = (8, 9, 10, 11, 12, 1)
CATCH_UP_DAYS = 14
SUMMARY_CAP = 300
LINE_TRIES = 2
SEASON_START = (8, 20)     # month, day: before FBS week zero
ET = ZoneInfo("America/New_York")


def season_for(day: date) -> int:
    """ESPN names a college football season by the year it starts."""
    return day.year if day.month >= 7 else day.year - 1


def team_sheet(store: dict, power: dict) -> dict:
    """Season figures for the Team Stats panel, keyed by name_key.

    ATS counts every game with a line, neutral sites included. Turnovers are
    giveaways per game; takeaways are the opponent's turnovers per game.
    Yards per play is season yards over season plays, not a mean of games.
    """
    acc: dict[str, dict] = {}
    latest: dict[str, dict] = {}
    for g in nsys._finals(store):
        for role, other in (("home", "away"), ("away", "home")):
            tid, oid = g[role]["id"], g[other]["id"]
            latest[tid] = g[role]
            t = acc.setdefault(tid, {"w": 0, "l": 0, "ats": [0, 0, 0], "pts": [],
                                     "opp": [], "giv": [], "tak": [],
                                     "yds": 0, "plays": 0})
            mine, theirs = g[f"{role}_score"], g[f"{other}_score"]
            t["w" if mine > theirs else "l"] += 1
            t["pts"].append(mine)
            t["opp"].append(theirs)
            sp = g.get("spread_home")
            if sp is not None:
                edge = mine - theirs + (sp if role == "home" else -sp)
                t["ats"][0 if edge > 0 else 1 if edge < 0 else 2] += 1
            box = g.get("box") or {}
            if tid in box and oid in box:
                t["giv"].append(box[tid].get("tov"))
                t["tak"].append(box[oid].get("tov"))
                if box[tid].get("yds") is not None and box[tid].get("plays"):
                    t["yds"] += box[tid]["yds"]
                    t["plays"] += box[tid]["plays"]
    out = {}
    for tid, t in acc.items():
        club = latest[tid]
        rank = (power.get(tid) or {}).get("rank")
        out[nsys.name_key(club["name"])] = {
            "id": tid, "name": club["name"], "color": club.get("color", ""),
            "rank": club.get("rank"), "record": f"{t['w']}-{t['l']}",
            "games": t["w"] + t["l"], "fpi": rank, "power_rank": rank,
            "rank_label": "FPI",
            "stats": {"ats": t["ats"], "pts": nsys._mean(t["pts"]),
                      "opp": nsys._mean(t["opp"]), "giv": nsys._mean(t["giv"]),
                      "tak": nsys._mean(t["tak"]),
                      "ypp": round(t["yds"] / t["plays"], 1) if t["plays"] else None}}
    return out


def _margin(home: float, away: float, neutral: bool) -> float:
    return home - away + (0.0 if neutral else HOME_EDGE)


def win_prob(home: float, away: float, neutral: bool) -> float:
    """Home win probability from FPI: normal CDF of the expected margin."""
    m = _margin(home, away, neutral)
    return 0.5 * (1 + math.erf(m / MARGIN_SD / math.sqrt(2)))


def _implied(ml) -> float | None:
    try:
        ml = float(ml)
    except (TypeError, ValueError):
        return None
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def market_prob(ml_home, ml_away) -> float | None:
    """The market's home win probability with the vig removed."""
    h, a = _implied(ml_home), _implied(ml_away)
    if h is None or a is None or h + a <= 0:
        return None
    return h / (h + a)


def _line(v: float) -> str:
    return f"{-abs(v):g}"


def _et_day(when: str) -> date | None:
    try:
        t = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(ET).date()


def board_rows(store: dict, power: dict, day: date, sheet: dict) -> list[dict]:
    """The board: unplayed games from today through WINDOW_DAYS - 1 days out
    (Eastern dates), soonest first, in the shape board cards draw."""
    last = day + timedelta(days=WINDOW_DAYS - 1)
    rows = []
    for g in store.get("games", {}).values():
        d = _et_day(g.get("commence_time"))
        # Unplayed games through the week, plus today's games however far
        # along they are: a finished game stays up for its result.
        if d is None or not (day <= d <= last) or (g.get("completed") and d != day):
            continue
        home, away = g["home"]["name"], g["away"]["name"]
        notes = []
        sp = g.get("spread_home")
        if sp is not None:
            spread = ("Pick'em" if sp == 0 else
                      f"{home} {_line(sp)}" if sp < 0 else f"{away} {_line(sp)}")
            text = f"Spread: {spread}"
            if g.get("total") is not None:
                text += f" · Total {g['total']:g}"
            notes.append(text)
        ph, pa = power.get(g["home"]["id"]), power.get(g["away"]["id"])
        model, margin = {}, None
        if ph and pa:
            margin = _margin(ph["rating"], pa["rating"], g.get("neutral", False))
            p = win_prob(ph["rating"], pa["rating"], g.get("neutral", False))
            model = {"home_win_prob": p, "away_win_prob": 1 - p}
            mk = market_prob(g.get("ml_home"), g.get("ml_away"))
            if mk is not None:
                model["market_home_prob"] = mk
                model["disagreement"] = round((p - mk) * 100, 1)
            fav = home if margin > 0 else away
            notes.append("FPI line: Pick'em" if round(margin, 1) == 0
                         else f"FPI line: {fav} -{abs(margin):.1f}")
        row = {"event_id": g["event_id"], "league": "ncaaf",
               "commence_time": g.get("commence_time", ""), "date": d.isoformat(),
               "home": home, "away": away, "model": model, "line_note": notes,
               "spread_home": sp, "fpi_margin": margin, "total": g.get("total")}
        row["_edge"] = 0.0 if g.get("neutral", False) else HOME_EDGE
        a_t, h_t = sheet.get(nsys.name_key(away)), sheet.get(nsys.name_key(home))
        if a_t and h_t:
            row["team_stats"] = {"away": a_t, "home": h_t}
        rows.append(row)
    _price(rows, sheet)
    rows.sort(key=lambda r: (r["commence_time"], r["home"]))
    return rows


def _price(rows: list[dict], sheet: dict) -> None:
    """Our side against the spread for every rated row with a line: FPI's
    margin stretched to the market's scale (fitted on the window's games),
    blended with this season's margins, then ats.pick. See ats.py."""
    import ats  # noqa: PLC0415
    k = ats.fit_stretch([(r["fpi_margin"], -r["spread_home"]) for r in rows
                         if r["fpi_margin"] is not None and r["spread_home"] is not None],
                        ats.STRETCH_DEFAULT["ncaaf"])
    season = {key: (t["games"], round(t["stats"]["pts"] - t["stats"]["opp"], 1))
              for key, t in sheet.items()
              if t.get("games") and (t.get("stats") or {}).get("pts") is not None
              and t["stats"].get("opp") is not None}
    for r in rows:
        edge = r.pop("_edge")
        if r["fpi_margin"] is None or r["spread_home"] is None:
            continue
        m = ats.blend(r["fpi_margin"] * k, season.get(nsys.name_key(r["home"])),
                      season.get(nsys.name_key(r["away"])), edge)
        p = ats.pick(m, r["spread_home"], MARGIN_SD, r["home"], r["away"])
        if p:
            p["stretch"] = k
            r["ats"] = p


# ---------------------------------------------------------- record keeping
def merge(history: list[dict], rows: list[dict], now: datetime | None = None) -> int:
    """Record each rated game once; never rewritten after. With `now`, a
    game that has kicked off is never recorded (marked counted=False): the
    record only holds picks posted before the start."""
    have = {h["event_id"] for h in history}
    n = 0
    for r in rows:
        m = r.get("model") or {}
        if not m or r["event_id"] in have:
            continue
        if now is not None:
            try:
                tip = datetime.fromisoformat(str(r["commence_time"]).replace("Z", "+00:00"))
            except ValueError:
                tip = None
            if tip is not None and tip <= now:
                r["counted"] = False
                continue
        history.append({"event_id": r["event_id"], "date": r["date"],
                        "home": r["home"], "away": r["away"],
                        "p_home": m["home_win_prob"],
                        "mkt_home": m.get("market_home_prob"),
                        "spread_home": r.get("spread_home"),
                        "fpi_margin": r.get("fpi_margin"),
                        **({"ats_side": r["ats"]["side"], "ats_tier": r["ats"]["tier"]}
                           if r.get("ats") else {})})
        have.add(r["event_id"])
        n += 1
    return n


def grade(history: list[dict], store: dict) -> int:
    """Settle recorded games that are final: who won, and whether the side
    FPI liked against the spread covered."""
    games = store.get("games", {})
    n = 0
    for h in history:
        if "home_won" in h:
            continue
        g = games.get(h["event_id"])
        if not g or not g.get("completed") or g.get("home_score") is None:
            continue
        margin = g["home_score"] - g["away_score"]
        h["home_won"] = margin > 0
        sp, fm = h.get("spread_home"), h.get("fpi_margin")
        posted = h.get("ats_side")
        if sp is not None and (posted or (fm is not None and fm + sp != 0)):
            # The side posted on the card; older rows had only FPI's raw line.
            side = (1 if posted == "home" else -1) if posted else (1 if fm + sp > 0 else -1)
            edge = side * (margin + sp)
            h["fpi_ats"] = "W" if edge > 0 else "L" if edge < 0 else "P"
        n += 1
    return n


def summary(history: list[dict]) -> dict:
    done = [h for h in history if "home_won" in h]
    brier = [(h["p_home"] - h["home_won"]) ** 2 for h in done]
    mkt = [(h["mkt_home"] - h["home_won"]) ** 2 for h in done
           if h.get("mkt_home") is not None]
    ats = [sum(1 for h in done if h.get("fpi_ats") == k) for k in "WLP"]
    import ats as _ats  # noqa: PLC0415
    # Only picks posted with a tier (calibrated pricing, Nov 2026 on): the
    # older raw-FPI picks were tiered on a different scale.
    tiers = {t: [0, 0, 0] for t in _ats.TIERS}
    for h in done:
        if h.get("fpi_ats") in ("W", "L", "P") and h.get("ats_tier") in tiers:
            tiers[h["ats_tier"]]["WLP".index(h["fpi_ats"])] += 1
    return {"graded": len(done), "pending": len(history) - len(done),
            "brier": round(sum(brier) / len(brier), 4) if brier else None,
            "market_brier": round(sum(mkt) / len(mkt), 4) if mkt else None,
            "fpi_ats": ats, "ats_tiers": tiers}


# ---------------------------------------------------------------- daily run
def daily(day: date, data, fetch=None, now: datetime | None = None) -> dict | None:
    """Fetch, store, grade, publish. ESPN only, idempotent; None off season."""
    if day.month not in SEASON_MONTHS:
        return None
    if fetch is None:
        import espn_cfb as fetch  # noqa: PLC0415
    data = Path(data)
    season = season_for(day)
    one = timedelta(days=1)
    store = nsys._load(data / "ncaaf_games.json", {})
    if store.get("season") != season:
        store = {"season": season, "last_day": None, "games": {}}

    # Finals since the last closed day, then the week ahead.
    start = (date.fromisoformat(store["last_day"]) + one if store.get("last_day")
             else day - one * CATCH_UP_DAYS)

    # Once per season: every final since the season began, so Team Stats and
    # records cover the year and not just the days since the board started.
    # A day that fails leaves the flag unset and the walk is repeated; games
    # merge by id, so repeating costs requests, never data.
    if not store.get("backfilled"):
        d, ok = date(season, *SEASON_START), True
        stop = min(start, day - one * CATCH_UP_DAYS)
        while d < stop:
            got = fetch.scoreboard(d.strftime("%Y%m%d"))
            if got is None:
                ok = False
            else:
                nsys.merge_games(store, [g for g in got
                                         if g.get("season") in (None, season)])
            d += one
        if ok:
            store["backfilled"] = True
    closed = start - one
    d = start
    while d <= day + one * (WINDOW_DAYS - 1):
        got = fetch.scoreboard(d.strftime("%Y%m%d"))
        if got is None:
            if d < day:
                closed = min(closed, d - one)
                d = max(d + one, day)     # skip ahead to the week's slate
                continue
        else:
            nsys.merge_games(store, [g for g in got
                                     if g.get("season") in (None, season)])
            if d < day and closed == d - one:
                closed = d
        d += one
    if closed >= start:
        store["last_day"] = closed.isoformat()

    boxes = 0
    for g in nsys._finals(store):
        if boxes >= SUMMARY_CAP:
            break
        # A final with its box but no line asks the summary again for the
        # line (the scoreboard drops odds once a game is over), LINE_TRIES
        # times at most: some games never had one.
        need_line = (g.get("box") and g.get("spread_home") is None
                     and g.get("line_tries", 0) < LINE_TRIES)
        if (g.get("box") and not need_line) or g.get("box_tries", 0) >= nsys.BOX_TRIES:
            continue
        box = fetch.summary(g["event_id"])
        boxes += 1
        if need_line:
            g["line_tries"] = g.get("line_tries", 0) + 1
        if box:
            nsys.attach_box(store, g["event_id"], box)
        else:
            g["box_tries"] = g.get("box_tries", 0) + 1

    old = nsys._load(data / "ncaaf.json", {})
    power = fetch.fpi(season) or (old.get("fpi") if old.get("season") == season
                                  else {}) or {}
    history = old.get("history") or []
    graded = grade(history, store)
    sheet = team_sheet(store, power)
    rows = board_rows(store, power, day, sheet)
    added = merge(history, rows, now=now or datetime.now(ZoneInfo("UTC")))
    nsys._save(data / "ncaaf_games.json", store, compact=True)
    nsys._save(data / "ncaaf.json", {
        "season": season, "date": day.isoformat(),
        "date_label": f"{day:%A, %B %-d, %Y}", "games": rows,
        "summary": summary(history), "fpi": power, "history": history})
    return {"games": len(rows), "stored": len(store["games"]), "boxes": boxes,
            "graded": graded, "new": added}


# ------------------------------------------------------------------ fixtures
def _club(tid, name):
    return {"id": tid, "name": name, "abbr": tid.upper(), "color": "9e1b32",
            "rank": None, "record": ""}


def _game(eid, home, away, hs=None, as_=None, spread=None, when="2026-11-07T20:00Z",
          neutral=False, ml=(None, None), total=None):
    done = hs is not None
    return {"event_id": eid, "date": when[:10], "commence_time": when,
            "season": 2026, "season_type": 2, "neutral": neutral,
            "postseason": False, "completed": done,
            "home": _club(home, f"Team {home.upper()}"),
            "away": _club(away, f"Team {away.upper()}"),
            "home_score": hs, "away_score": as_, "home_1h": None, "away_1h": None,
            "spread_home": spread, "ml_home": ml[0], "ml_away": ml[1],
            "total": total}


def _box(h, a, hy, hp, ht, ay, ap, at, hpts, apts):
    return {h: {"pts": hpts, "yds": hy, "plays": hp, "tov": ht},
            a: {"pts": apts, "yds": ay, "plays": ap, "tov": at}}


def _self_test() -> None:
    store = {"season": 2026, "games": {}}
    g1 = _game("1", "bama", "x", 42, 10, spread=-20.0)        # bama covers
    g2 = _game("2", "y", "bama", 24, 20, spread=-7.0, when="2026-11-01T20:00Z")
    g3 = _game("3", "lsu", "x", 28, 14, spread=-10.0, when="2026-10-25T20:00Z")
    for g in (g1, g2, g3):
        nsys.merge_games(store, [g])
    nsys.attach_box(store, "1", _box("bama", "x", 500, 70, 1, 200, 60, 3, 42, 10))
    nsys.attach_box(store, "2", _box("y", "bama", 350, 65, 0, 300, 60, 2, 24, 20))
    power = {"bama": {"rating": 20.0, "rank": 3}, "lsu": {"rating": 10.0, "rank": 15}}

    sheet = team_sheet(store, power)
    b = sheet[nsys.name_key("Team BAMA")]
    st = b["stats"]
    assert b["record"] == "1-1" and b["fpi"] == 3 and b["rank_label"] == "FPI"
    # Lost 24-20 getting 7 at y: a cover. Won by 32 laying 20: a cover.
    assert st["ats"] == [2, 0, 0], st["ats"]
    assert st["pts"] == 31.0 and st["opp"] == 17.0
    assert st["giv"] == 1.5 and st["tak"] == 1.5
    assert st["ypp"] == round(800 / 130, 1), "yards over plays, season totals"

    # Win probability: FPI gap + home edge over MARGIN_SD.
    p = win_prob(20.0, 10.0, neutral=False)
    assert abs(p - 0.5 * (1 + math.erf(12.5 / MARGIN_SD / math.sqrt(2)))) < 1e-9
    assert win_prob(10.0, 10.0, neutral=True) == 0.5, "no home edge in a bowl"
    assert win_prob(10.0, 10.0, neutral=False) > 0.5

    # Market: moneylines with the vig taken out.
    m = market_prob(-200, 170)
    raw_h, raw_a = 200 / 300, 100 / 270
    assert abs(m - raw_h / (raw_h + raw_a)) < 1e-9
    assert market_prob(None, 150) is None

    # Rows: the next WINDOW_DAYS by Eastern date, unplayed, soonest first.
    day = date(2026, 11, 9)
    up = [_game("10", "bama", "lsu", spread=-6.5, total=52.5,
                when="2026-11-15T00:30Z", ml=(-250, 205)),   # Sat 7:30pm ET
          _game("11", "y", "x", spread=-3.0, when="2026-11-10T01:00Z"),  # Mon 8pm ET
          _game("12", "bama", "y", spread=-1.0, when="2026-11-17T01:00Z")]  # Mon 16th: out
    for g in up:
        nsys.merge_games(store, [g])
    rows = board_rows(store, power, day, team_sheet(store, power))
    assert [r["event_id"] for r in rows] == ["11", "10"], [r["event_id"] for r in rows]
    r = rows[1]
    assert r["league"] == "ncaaf" and r["home"] == "Team BAMA" and r["away"] == "Team LSU"
    assert abs(r["model"]["home_win_prob"] - win_prob(20.0, 10.0, False)) < 1e-9
    assert abs(r["model"]["market_home_prob"] - market_prob(-250, 205)) < 1e-9
    # Same edge field the other boards publish: model minus market, points.
    assert r["model"]["disagreement"] == round(
        (win_prob(20.0, 10.0, False) - market_prob(-250, 205)) * 100, 1)
    assert r["line_note"] == ["Spread: Team BAMA -6.5 \u00b7 Total 52.5",
                              "FPI line: Team BAMA -12.5"], r["line_note"]
    assert r["team_stats"]["home"]["name"] == "Team BAMA"
    # Our side against the spread: FPI home by 12.5, too few games to fit a
    # stretch, so the default 0.83: home by 10.4 against -6.5, raw 3.9.
    assert r["ats"]["side"] == "home" and r["ats"]["line"] == -6.5
    assert r["ats"]["raw"] == 3.9 and r["ats"]["team"] == "Team BAMA"
    assert r["ats"]["stretch"] == 0.83
    assert r["total"] == 52.5, "the card's Total chip"
    # No FPI for either side: listed, not rated.
    # Today's games stay on the board after they finish (to show the result);
    # earlier days' finals do not.
    done_today = _game("13", "bama", "lsu", 30, 20, spread=-3.0, when="2026-11-09T17:00Z")
    done_before = _game("14", "bama", "lsu", 30, 20, spread=-3.0, when="2026-11-02T17:00Z")
    tmp = dict(store, games=dict(store["games"], **{"13": done_today, "14": done_before}))
    ids = [x["event_id"] for x in board_rows(tmp, power, day, team_sheet(store, power))]
    assert "13" in ids and "14" not in ids, ids
    # A team with no finals stored: no panel, rather than half a table.
    lone = dict(store, games={k: v for k, v in store["games"].items() if k != "3"})
    lone_rows = board_rows(lone, power, day, team_sheet(lone, power))
    assert "team_stats" not in next(x for x in lone_rows if x["event_id"] == "10")
    r11 = rows[0]
    assert r11["model"] == {} and r11["line_note"][0] == "Spread: Team Y -3"

    # Record: merge once, grade on the final.
    # A game that has kicked off is never recorded.
    late: list[dict] = []
    assert merge(late, rows, now=datetime(2026, 11, 15, 1, 0,
                                          tzinfo=ZoneInfo("UTC"))) == 0
    assert rows[1].get("counted") is False
    rows[1].pop("counted")
    hist: list[dict] = []
    assert merge(hist, rows) == 1, "only rated games are recorded"
    assert merge(hist, rows) == 0
    store["games"]["10"].update(completed=True, home_score=31, away_score=17)
    assert grade(hist, store) == 1 and grade(hist, store) == 0
    h = hist[0]
    assert h["home_won"] is True
    # FPI said home by 12.5 against -6.5: FPI side is home; won by 14: W.
    assert h["fpi_ats"] == "W"
    s = summary(hist)
    assert s["graded"] == 1 and s["fpi_ats"] == [1, 0, 0]
    # Tiered by the tier posted on the card, not recomputed later.
    assert h["ats_side"] == "home" and h["ats_tier"] == r["ats"]["tier"]
    assert s["ats_tiers"][h["ats_tier"]] == [1, 0, 0]
    assert sum(sum(v) for v in s["ats_tiers"].values()) == 1
    assert set(s["ats_tiers"]) == {"best", "lean", "check", "pass"}
    # Graded on the side posted: a posted away pick loses when home covers.
    h2 = dict(h, ats_side="away")
    for k in ("home_won", "fpi_ats"):
        h2.pop(k)
    grade([h2], store)
    assert h2["fpi_ats"] == "L"
    # Legacy rows (no tier stored) stay out of the tier records.
    legacy = dict(h)
    legacy.pop("ats_tier")
    assert sum(sum(v) for v in summary([legacy])["ats_tiers"].values()) == 0
    assert s["brier"] == round((1 - h["p_home"]) ** 2, 4)
    assert s["market_brier"] == round((1 - h["mkt_home"]) ** 2, 4)

    _test_daily()
    print("ncaaf self-test: all invariants hold")


def _morning(d: int) -> datetime:
    """9 AM Eastern on November d, 2026: tests never read the wall clock."""
    return datetime(2026, 11, d, 14, 0, tzinfo=ZoneInfo("UTC"))


def _test_daily() -> None:
    import json
    import tempfile

    class Fake:
        def __init__(self):
            self.days, self.boxes, self.calls = {}, {}, {"sb": 0, "sum": 0}

        def scoreboard(self, d):
            self.calls["sb"] += 1
            return [dict(g) for g in self.days.get(d, [])]

        def summary(self, eid):
            self.calls["sum"] += 1
            return self.boxes.get(eid, {})

        def fpi(self, season):
            return {"bama": {"rating": 20.0, "rank": 3},
                    "lsu": {"rating": 10.0, "rank": 15}}

    f = Fake()
    f.days = {"20261107": [_game("1", "bama", "x", 42, 10, spread=-20.0),
                           _game("3", "lsu", "x", 28, 14, spread=-10.0)],
              "20261114": [_game("10", "bama", "lsu", spread=-6.5,
                                 when="2026-11-15T00:30Z", ml=(-250, 205))]}
    f.boxes = {"1": _box("bama", "x", 500, 70, 1, 200, 60, 3, 42, 10),
               "3": _box("lsu", "x", 410, 66, 2, 250, 61, 1, 28, 14)}
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        assert daily(date(2026, 6, 1), data, fetch=f) is None, "off season"
        out = daily(date(2026, 11, 9), data, fetch=f, now=_morning(9))
        # The whole season so far, once (Aug 20 up to the catch-up window),
        # then 14 days back to yesterday, today and the 6 days after it.
        early = (date(2026, 11, 9) - timedelta(days=CATCH_UP_DAYS) - date(2026, *SEASON_START)).days
        assert f.calls["sb"] == early + CATCH_UP_DAYS + WINDOW_DAYS, f.calls
        assert json.loads((data / "ncaaf_games.json").read_text())["backfilled"] is True
        assert f.calls["sum"] == 2 and out["games"] == 1
        doc = json.loads((data / "ncaaf.json").read_text())
        assert [g["event_id"] for g in doc["games"]] == ["10"]
        assert doc["games"][0]["team_stats"]["home"]["stats"]["ats"] == [1, 0, 0]
        # Next morning: yesterday again plus the week ahead; no box refetch.
        before = dict(f.calls)
        daily(date(2026, 11, 10), data, fetch=f, now=_morning(10))
        assert f.calls["sb"] - before["sb"] == 1 + WINDOW_DAYS
        assert f.calls["sum"] == before["sum"]

    # A final stored without a line (ESPN's scoreboard drops the odds once a
    # game is over) asks its summary for the line once more, and ATS fills.
    h = Fake()
    h.days = {"20261107": [_game("1", "bama", "x", 42, 10)]}          # no spread
    h.boxes = {"1": _box("bama", "x", 500, 70, 1, 200, 60, 3, 42, 10)}
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        daily(date(2026, 11, 9), data, fetch=h, now=_morning(9))
        st = json.loads((data / "ncaaf_games.json").read_text())
        assert st["games"]["1"]["spread_home"] is None and st["games"]["1"]["box"]
        # The summary now carries the line.
        h.boxes["1"] = dict(h.boxes["1"], _odds={"spread_home": -20.0, "total": 51.5,
                                                 "ml_home": None, "ml_away": None})
        n = h.calls["sum"]
        daily(date(2026, 11, 10), data, fetch=h, now=_morning(10))
        st = json.loads((data / "ncaaf_games.json").read_text())
        assert h.calls["sum"] == n + 1, "asked again for the line"
        assert st["games"]["1"]["spread_home"] == -20.0 and st["games"]["1"]["total"] == 51.5
        assert "_odds" not in st["games"]["1"]["box"]
        n = h.calls["sum"]
        daily(date(2026, 11, 11), data, fetch=h, now=_morning(11))
        assert h.calls["sum"] == n, "has its line: not asked again"
    # A game whose summary never has a line is asked LINE_TRIES times, no more.
    k = Fake()
    k.days = {"20261107": [_game("1", "bama", "x", 42, 10)]}
    k.boxes = {"1": _box("bama", "x", 500, 70, 1, 200, 60, 3, 42, 10)}
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(9, 9 + LINE_TRIES + 3):
            daily(date(2026, 11, i), Path(tmp), fetch=k, now=_morning(i))
        assert k.calls["sum"] == 1 + LINE_TRIES, k.calls

    # Team Stats must cover the season, not the last fortnight (Auburn showed
    # "1-1" from two games in November): an early-season final is stored.
    e = Fake()
    e.days = {"20260905": [_game("s1", "bama", "x", 35, 7)],
              "20261107": [_game("1", "bama", "x", 42, 10, spread=-20.0)]}
    with tempfile.TemporaryDirectory() as tmp:
        daily(date(2026, 11, 9), Path(tmp), fetch=e, now=_morning(9))
        st = json.loads((Path(tmp) / "ncaaf_games.json").read_text())
        assert "s1" in st["games"] and st["games"]["s1"]["home_score"] == 35
        sheet = team_sheet(st, {})
        assert sheet[nsys.name_key("Team BAMA")]["record"] == "2-0"
    # A day that fails during the season backfill leaves it unfinished, and
    # the next run walks the early season again (merging is idempotent).
    b = Fake()
    real_b = b.scoreboard
    b.scoreboard = lambda d: None if d == "20260912" else real_b(d)
    with tempfile.TemporaryDirectory() as tmp:
        daily(date(2026, 11, 9), Path(tmp), fetch=b, now=_morning(9))
        assert not json.loads((Path(tmp) / "ncaaf_games.json").read_text()).get("backfilled")
        b.scoreboard = real_b
        n = b.calls["sb"]
        daily(date(2026, 11, 10), Path(tmp), fetch=b, now=_morning(10))
        assert json.loads((Path(tmp) / "ncaaf_games.json").read_text())["backfilled"] is True
        assert b.calls["sb"] - n > 60, "the early season was walked again"

    # A failed past scoreboard is not a closed day: it is fetched again.
    g = Fake()
    real = g.scoreboard
    g.scoreboard = lambda d: None if d == "20261105" else real(d)
    with tempfile.TemporaryDirectory() as tmp:
        daily(date(2026, 11, 9), Path(tmp), fetch=g, now=_morning(9))
        st = json.loads((Path(tmp) / "ncaaf_games.json").read_text())
        assert st["last_day"] == "2026-11-04", st["last_day"]
        doc = json.loads((Path(tmp) / "ncaaf.json").read_text())
        assert doc["games"] is not None, "the week ahead still published"


if __name__ == "__main__":
    _self_test()
