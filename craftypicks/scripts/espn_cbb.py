#!/usr/bin/env python3
"""ESPN, men's college basketball: the free feed behind the NCAAB System tabs.

Four endpoints, all keyless:

  scoreboard   tonight's games (full names, ids, the line) and past finals
  summary      one game's box score: rebounds, steals, turnovers, every
               player's points, the first-half score, and the closing line
  schedule     one team's season, for head-to-head history
  powerindex   ESPN BPI rank for every D-I team

Parsers are pure and carry the self-test. Fetchers go through results._get,
which already has the browser User-Agent ESPN insists on and never raises.

The shapes parsed here were read off real ESPN payloads (the fixtures in
sportsdataverse-py's test suite), not guessed: the sandbox this is written in
cannot reach ESPN, so the first live call happens on the GitHub runner.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SITE = ("https://site.api.espn.com/apis/site/v2/sports/basketball/"
        "mens-college-basketball")
BPI = ("https://site.web.api.espn.com/apis/fitt/v3/sports/basketball/"
       "mens-college-basketball/powerindex")


def _num(v):
    """'71' / 71.0 / {'value': 71.0} -> 71.0. None for anything else."""
    if isinstance(v, dict):
        v = v.get("value", v.get("displayValue"))
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return None if n is None else int(round(n))


EMPTY_ODDS = {"spread_home": None, "ml_home": None, "ml_away": None,
              "total": None}


def parse_odds(odds, home_abbr: str) -> dict:
    """The first odds block, as the HOME team's spread plus both moneylines.

    `details` ("DUKE -7.5") names the favourite, so it fixes the sign without
    trusting `spread`, whose orientation ESPN has not kept consistent. Only
    when `details` is missing does the bare number get used, signed by which
    side is flagged as the favourite.
    """
    if not isinstance(odds, list) or not odds or not isinstance(odds[0], dict):
        return dict(EMPTY_ODDS)
    o = odds[0]
    home_o = o.get("homeTeamOdds") or {}
    away_o = o.get("awayTeamOdds") or {}
    spread = None
    details = str(o.get("details") or "").strip()
    if details.upper() in ("EVEN", "PK", "PICK"):
        spread = 0.0
    elif details:
        parts = details.rsplit(" ", 1)
        line = _num(parts[-1]) if len(parts) == 2 else None
        if line is not None:
            fav = parts[0].strip().upper()
            if home_abbr:
                home_fav = fav == home_abbr.upper()
            else:
                # No abbreviation to match against: the favourite flag says.
                home_fav = (True if home_o.get("favorite") is True else
                            False if away_o.get("favorite") is True else None)
            if home_fav is not None:
                spread = -abs(line) if home_fav else abs(line)
    if spread is None and not details and _num(o.get("spread")) is not None:
        mag = abs(_num(o.get("spread")))
        if home_o.get("favorite") is True:
            spread = -mag
        elif away_o.get("favorite") is True:
            spread = mag
    return {"spread_home": spread,
            "ml_home": _int(home_o.get("moneyLine")),
            "ml_away": _int(away_o.get("moneyLine")),
            "total": _num(o.get("overUnder"))}


# Conference tournaments are season type 2 on ESPN, not 3; the note on the
# game is what says so.
_TOURNEY_WORDS = ("tournament", "championship")


def parse_event(ev) -> dict | None:
    """One scoreboard event, flattened. None if it does not parse."""
    try:
        comp = ev["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = sides["home"], sides["away"]
    except (KeyError, IndexError, TypeError):
        return None
    status = ((comp.get("status") or ev.get("status") or {}).get("type") or {})
    done = bool(status.get("completed"))

    def club(c):
        t = c.get("team") or {}
        return {"id": str(t.get("id", "")), "name": t.get("displayName", ""),
                "abbr": t.get("abbreviation", "")}

    def first_half(c):
        ls = c.get("linescores") or []
        return _int(ls[0].get("value", ls[0].get("displayValue"))) if ls else None

    season = ev.get("season") or {}
    notes = " ".join(str(n.get("headline", "")) for n in comp.get("notes") or []
                     if isinstance(n, dict)).lower()
    h, a = club(home), club(away)
    return {
        "event_id": str(ev.get("id", "")),
        "date": str(ev.get("date", ""))[:10],
        "commence_time": ev.get("date", ""),
        "season": season.get("year"),
        "season_type": season.get("type"),
        "neutral": bool(comp.get("neutralSite")),
        "postseason": season.get("type") == 3
                      or any(w in notes for w in _TOURNEY_WORDS),
        "completed": done,
        "home": h, "away": a,
        "home_score": _int(home.get("score")) if done else None,
        "away_score": _int(away.get("score")) if done else None,
        "home_1h": first_half(home) if done else None,
        "away_1h": first_half(away) if done else None,
        **parse_odds(comp.get("odds"), h["abbr"]),
    }


def parse_box(summary) -> dict:
    """Per team: rebounds, steals, turnovers and each player's points.

    totalTurnovers, not turnovers: the latter leaves out team turnovers
    (shot-clock violations and the like), which still count as a giveaway.
    """
    if not isinstance(summary, dict):
        return {}
    box = summary.get("boxscore") or {}
    out: dict = {}
    for t in box.get("teams") or []:
        tid = str((t.get("team") or {}).get("id", ""))
        st = {s.get("name"): s.get("displayValue")
              for s in t.get("statistics") or [] if isinstance(s, dict)}
        tov = st.get("totalTurnovers", st.get("turnovers"))
        out[tid] = {"reb": _int(st.get("totalRebounds")),
                    "stl": _int(st.get("steals")), "tov": _int(tov),
                    "players": {}}
    for t in box.get("players") or []:
        tid = str((t.get("team") or {}).get("id", ""))
        if tid not in out:
            continue
        for block in t.get("statistics") or []:
            names = block.get("names") or block.get("keys") or []
            if "PTS" not in names:
                continue
            i = names.index("PTS")
            for a in block.get("athletes") or []:
                stats = a.get("stats") or []
                if a.get("didNotPlay") or len(stats) <= i:
                    continue
                pts = _int(stats[i])
                pid = str((a.get("athlete") or {}).get("id", ""))
                if pid and pts is not None:
                    out[tid]["players"][pid] = pts
    if not out:
        return {}
    halves = {}
    try:
        for c in summary["header"]["competitions"][0]["competitors"]:
            ls = c.get("linescores") or []
            if ls:
                halves[str(c["team"]["id"])] = _int(
                    ls[0].get("displayValue", ls[0].get("value")))
    except (KeyError, IndexError, TypeError):
        pass
    out["_1h"] = halves
    home_abbr = ""
    for c in ((summary.get("header") or {}).get("competitions") or [{}])[0].get(
            "competitors") or []:
        if c.get("homeAway") == "home":
            home_abbr = (c.get("team") or {}).get("abbreviation", "")
    out["_odds"] = parse_odds(summary.get("pickcenter"), home_abbr)
    return out


def parse_schedule(payload) -> list[dict]:
    """A team's completed games: who was home, who was away, the score."""
    out = []
    for ev in (payload or {}).get("events") or []:
        try:
            comp = ev["competitions"][0]
            if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
                continue
            sides = {c["homeAway"]: c for c in comp["competitors"]}
            hs, as_ = _int(sides["home"].get("score")), _int(sides["away"].get("score"))
            if hs is None or as_ is None:
                continue
            out.append({"date": str(ev.get("date", ""))[:10],
                        "home_id": str(sides["home"]["team"]["id"]),
                        "away_id": str(sides["away"]["team"]["id"]),
                        "home_score": hs, "away_score": as_})
        except (KeyError, IndexError, TypeError):
            continue
    return out


def parse_bpi(payload) -> dict[str, int]:
    """Team id -> BPI rank. Values are positional; the labels live on the
    top-level categories, so they are zipped by index."""
    if not isinstance(payload, dict):
        return {}
    names = next((c.get("names") or [] for c in payload.get("categories") or []
                  if c.get("name") == "bpi"), [])
    rank_i = names.index("bpirank") if "bpirank" in names else None
    val_i = names.index("bpi") if "bpi" in names else None
    ranks, values = {}, {}
    for t in payload.get("teams") or []:
        tid = str((t.get("team") or {}).get("id", ""))
        cat = next((c for c in t.get("categories") or [] if c.get("name") == "bpi"),
                   None)
        vals = (cat or {}).get("values") or []
        if not tid:
            continue
        if rank_i is not None and rank_i < len(vals) and _num(vals[rank_i]) is not None:
            ranks[tid] = int(_num(vals[rank_i]))
        if val_i is not None and val_i < len(vals) and _num(vals[val_i]) is not None:
            values[tid] = _num(vals[val_i])
    if ranks:
        return ranks
    order = sorted(values, key=lambda k: -values[k])
    return {tid: i + 1 for i, tid in enumerate(order)}


# ------------------------------------------------------------------ fetchers
def _get(url: str) -> dict:
    import results  # noqa: PLC0415 -- headers + never-raise policy live there
    return results._get(url)


def scoreboard(day: str) -> list[dict] | None:
    """Every D-I game on a date (YYYYMMDD). groups=50 is Division I.

    None when the call failed, [] when the day had no games. ESPN answers an
    empty day with {"events": []}; _get answers a failure with {}. Telling
    the two apart is what stops a bad morning being recorded as a day with
    no basketball and never fetched again."""
    data = _get(f"{SITE}/scoreboard?dates={day}&groups=50&limit=400")
    if not isinstance(data, dict) or "events" not in data:
        return None
    return [g for g in (parse_event(e) for e in data.get("events") or []) if g]


def summary(event_id: str) -> dict:
    return parse_box(_get(f"{SITE}/summary?event={event_id}"))


def schedule(team_id: str, season: int) -> list[dict]:
    return parse_schedule(_get(f"{SITE}/teams/{team_id}/schedule?season={season}"))


def bpi(season: int) -> dict[str, int]:
    """All pages. One page of 400 covers D-I today, but the loop costs nothing
    and a silent half-table would rank half the field as missing."""
    out: dict[str, int] = {}
    page, pages = 1, 1
    while page <= pages and page <= 5:
        data = _get(f"{BPI}?season={season}&limit=400&page={page}")
        out.update(parse_bpi(data))
        pages = int(((data or {}).get("pagination") or {}).get("pages") or 1)
        page += 1
    return out


# ------------------------------------------------------------------ fixtures
def _team(tid, name, abbr):
    return {"id": tid, "displayName": name, "abbreviation": abbr,
            "shortDisplayName": name.split()[0], "name": name.split()[-1]}


def _fx_event(completed=True, odds=None, neutral=False, notes=None,
              season_type=2):
    comp = {
        "neutralSite": neutral,
        "notes": notes or [],
        "status": {"type": {"completed": completed}},
        "competitors": [
            {"homeAway": "home", "team": _team("2509", "Purdue Boilermakers", "PUR"),
             "score": "75" if completed else "0",
             "linescores": [{"value": 36.0, "period": 1}, {"value": 39.0, "period": 2}]
             if completed else []},
            {"homeAway": "away", "team": _team("2335", "Liberty Flames", "LIB"),
             "score": "60" if completed else "0",
             "linescores": [{"value": 30.0, "period": 1}, {"value": 30.0, "period": 2}]
             if completed else []},
        ],
    }
    if odds is not None:
        comp["odds"] = odds
    return {"id": "401", "date": "2026-11-04T00:00Z",
            "season": {"year": 2027, "type": season_type},
            "status": {"type": {"completed": completed}},
            "competitions": [comp]}


def _fx_summary():
    names = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL",
             "BLK", "OREB", "DREB", "PF"]

    def ath(pid, pts, dnp=False):
        return {"athlete": {"id": pid, "displayName": f"P{pid}"},
                "didNotPlay": dnp,
                "stats": [] if dnp else ["30", str(pts)] + ["0"] * 11}

    def team_stats(reb, stl, tov):
        return [{"name": "totalRebounds", "displayValue": str(reb)},
                {"name": "steals", "displayValue": str(stl)},
                {"name": "turnovers", "displayValue": str(tov - 1)},
                {"name": "totalTurnovers", "displayValue": str(tov)}]

    return {
        "boxscore": {
            "teams": [
                {"team": {"id": "2509"}, "homeAway": "home",
                 "statistics": team_stats(38, 7, 9)},
                {"team": {"id": "2335"}, "homeAway": "away",
                 "statistics": team_stats(28, 3, 14)},
            ],
            "players": [
                {"team": {"id": "2509"}, "statistics": [
                    {"names": names, "athletes": [ath("1", 22), ath("2", 15),
                                                  ath("3", 0, dnp=True)]}]},
                {"team": {"id": "2335"}, "statistics": [
                    {"names": names, "athletes": [ath("9", 31)]}]},
            ],
        },
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "2509"}, "score": "75",
             "linescores": [{"displayValue": "36"}, {"displayValue": "39"}]},
            {"homeAway": "away", "team": {"id": "2335"}, "score": "60",
             "linescores": [{"displayValue": "30"}, {"displayValue": "30"}]},
        ]}]},
        "pickcenter": [{"details": "PUR -9.5", "overUnder": 141.5,
                        "homeTeamOdds": {"favorite": True, "moneyLine": -500},
                        "awayTeamOdds": {"favorite": False, "moneyLine": 380}}],
    }


def _self_test() -> None:
    # --- odds: the sign is the whole point
    fav_home = [{"details": "PUR -9.5", "overUnder": 141.5,
                 "homeTeamOdds": {"favorite": True, "moneyLine": -500},
                 "awayTeamOdds": {"favorite": False, "moneyLine": 380}}]
    o = parse_odds(fav_home, "PUR")
    assert o == {"spread_home": -9.5, "ml_home": -500, "ml_away": 380,
                 "total": 141.5}, o
    fav_away = [{"details": "LIB -3", "homeTeamOdds": {}, "awayTeamOdds": {}}]
    assert parse_odds(fav_away, "PUR")["spread_home"] == 3.0
    assert parse_odds([{"details": "EVEN"}], "PUR")["spread_home"] == 0.0
    # No details: fall back to the bare number and who is favoured.
    bare = [{"spread": 6.5, "homeTeamOdds": {"favorite": False},
             "awayTeamOdds": {"favorite": True}}]
    assert parse_odds(bare, "PUR")["spread_home"] == 6.5
    bare[0]["homeTeamOdds"]["favorite"] = True
    assert parse_odds(bare, "PUR")["spread_home"] == -6.5
    assert parse_odds(None, "PUR") == {"spread_home": None, "ml_home": None,
                                        "ml_away": None, "total": None}
    assert parse_odds([{"details": "garbage"}], "PUR")["spread_home"] is None

    # --- event
    g = parse_event(_fx_event(odds=fav_home))
    assert g["home"] == {"id": "2509", "name": "Purdue Boilermakers", "abbr": "PUR"}
    assert g["away"]["name"] == "Liberty Flames"
    assert (g["home_score"], g["away_score"]) == (75, 60)
    assert (g["home_1h"], g["away_1h"]) == (36, 30)
    assert g["spread_home"] == -9.5 and g["completed"] and g["season"] == 2027
    assert g["postseason"] is False and g["neutral"] is False
    up = parse_event(_fx_event(completed=False))
    assert up["home_score"] is None and up["home_1h"] is None
    assert up["spread_home"] is None
    assert parse_event(_fx_event(season_type=3))["postseason"] is True
    conf = _fx_event(notes=[{"headline": "Big East Tournament - Quarterfinal"}])
    assert parse_event(conf)["postseason"] is True
    assert parse_event({}) is None and parse_event({"competitions": []}) is None

    # --- box
    b = parse_box(_fx_summary())
    assert b["2509"]["reb"] == 38 and b["2509"]["stl"] == 7
    assert b["2509"]["tov"] == 9, "totalTurnovers, not turnovers"
    assert b["2509"]["players"] == {"1": 22, "2": 15}, "DNP must be dropped"
    assert b["2335"]["players"] == {"9": 31}
    assert b["_1h"] == {"2509": 36, "2335": 30}
    assert b["_odds"]["spread_home"] == -9.5
    assert parse_box({}) == {}

    # --- schedule
    sch = {"events": [
        {"date": "2025-11-05T01:45Z", "competitions": [{
            "status": {"type": {"completed": True}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "150"}, "score": {"value": 75.0}},
                {"homeAway": "away", "team": {"id": "251"}, "score": {"value": 60.0}}]}]},
        {"date": "2026-03-01T01:45Z", "competitions": [{
            "status": {"type": {"completed": False}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "150"}},
                {"homeAway": "away", "team": {"id": "9"}}]}]},
    ]}
    assert parse_schedule(sch) == [{"date": "2025-11-05", "home_id": "150",
                                    "away_id": "251", "home_score": 75,
                                    "away_score": 60}]
    assert parse_schedule({}) == []

    # --- BPI
    bpi = {"categories": [{"name": "bpi", "names": ["bpi", "bpirank", "bpioffense"]}],
           "teams": [
               {"team": {"id": "150"}, "categories": [{"name": "bpi", "values": [20.1, 1.0, 9.0]}]},
               {"team": {"id": "251"}, "categories": [{"name": "bpi", "values": [8.0, 41.0, 4.0]}]}]}
    assert parse_bpi(bpi) == {"150": 1, "251": 41}
    # No rank column: rank by the BPI value itself.
    bpi["categories"][0]["names"] = ["bpi", "bpioffense", "bpidefense"]
    assert parse_bpi(bpi) == {"150": 1, "251": 2}
    assert parse_bpi({}) == {}

    # A failed call is None; a day with no games is [].
    import unittest.mock as um
    with um.patch(__name__ + "._get", return_value={}):
        assert scoreboard("20261112") is None
    with um.patch(__name__ + "._get", return_value={"events": []}):
        assert scoreboard("20261112") == []

    print("espn_cbb self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
