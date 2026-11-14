#!/usr/bin/env python3
"""ESPN, college football: the free feed behind the NCAAF board.

  scoreboard   games over a date (FBS only: groups=80) -- full names, rank,
               record, ESPN's spread, total and moneyline, neutral site
  summary      one game's box score: points, yards, plays, turnovers
  powerindex   ESPN FPI: rating (points vs an average FBS team on a neutral
               field) and rank, for every FBS team

The scoreboard shape is the same as basketball's, so events go through
espn_cbb.parse_event. Shapes checked against real ESPN payloads (the
sportsdataverse-py fixtures): this sandbox cannot reach ESPN.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import espn_cbb  # noqa: E402  -- parse_event / parse_odds / _int / _num / _get

SITE = ("https://site.api.espn.com/apis/site/v2/sports/football/"
        "college-football")
FPI = ("https://site.web.api.espn.com/apis/fitt/v3/sports/football/"
       "college-football/powerindex")


_int = espn_cbb._int
_num = espn_cbb._num


def parse_box(summary) -> dict:
    """Per team: points, total yards, offensive plays, turnovers; plus the
    game's line under "_odds" when the summary carries one.

    Plays are rush attempts plus pass attempts (sacks are not in either
    count, so yards per play reads a touch high -- the same for everyone).
    Points come from the header, which carries the final score.
    """
    if not isinstance(summary, dict):
        return {}
    out: dict = {}
    for t in (summary.get("boxscore") or {}).get("teams") or []:
        tid = str((t.get("team") or {}).get("id", ""))
        st = {s.get("name"): s.get("displayValue")
              for s in t.get("statistics") or [] if isinstance(s, dict)}
        ca = str(st.get("completionAttempts") or "").replace("/", "-").split("-")
        att = _int(ca[1]) if len(ca) == 2 else None
        rush = _int(st.get("rushingAttempts"))
        out[tid] = {"pts": None, "yds": _int(st.get("totalYards")),
                    "plays": (att or 0) + (rush or 0) if att is not None or rush is not None else None,
                    "tov": _int(st.get("turnovers"))}
    if not out:
        return {}
    abbr = {"home": "", "away": ""}
    try:
        for c in summary["header"]["competitions"][0]["competitors"]:
            tid = str(c["team"]["id"])
            if tid in out:
                out[tid]["pts"] = _int(c.get("score"))
            if c.get("homeAway") in abbr:
                abbr[c["homeAway"]] = (c.get("team") or {}).get("abbreviation", "")
    except (KeyError, IndexError, TypeError):
        pass
    box = {k: {"pts": v["pts"], "yds": v["yds"], "plays": v["plays"],
               "tov": v["tov"]} for k, v in out.items()}
    # The game's line. The scoreboard drops its odds once a game is final;
    # the summary keeps them, and ncaab_system.attach_box fills a missing
    # line from here (keys starting "_" are not stored in the box).
    odds = espn_cbb.parse_odds(summary.get("pickcenter"), abbr["home"], abbr["away"])
    if odds.get("spread_home") is not None or odds.get("total") is not None:
        box["_odds"] = odds
    return box


def parse_power(payload, kind: str = "fpi") -> dict[str, dict]:
    """Team id -> {"rating", "rank"} from a fitt powerindex payload.

    Values are positional; labels are on the top-level category, zipped by
    index. With no rank column the rank is taken from the rating.
    """
    if not isinstance(payload, dict):
        return {}
    names = next((c.get("names") or [] for c in payload.get("categories") or []
                  if c.get("name") == kind), [])
    vi = names.index(kind) if kind in names else None
    ri = names.index(kind + "rank") if kind + "rank" in names else None
    out: dict[str, dict] = {}
    for t in payload.get("teams") or []:
        tid = str((t.get("team") or {}).get("id", ""))
        cat = next((c for c in t.get("categories") or [] if c.get("name") == kind), None)
        vals = (cat or {}).get("values") or []
        if not tid or vi is None or vi >= len(vals) or _num(vals[vi]) is None:
            continue
        rank = _num(vals[ri]) if ri is not None and ri < len(vals) else None
        out[tid] = {"rating": _num(vals[vi]), "rank": int(rank) if rank else None}
    if out and any(v["rank"] is None for v in out.values()):
        for i, tid in enumerate(sorted(out, key=lambda k: -out[k]["rating"])):
            out[tid]["rank"] = i + 1
    return out


# ------------------------------------------------------------------ fetchers
def scoreboard(day: str) -> list[dict] | None:
    """FBS games on a date (YYYYMMDD). None when the call failed, [] when
    there were no games -- the same contract as the basketball feed."""
    data = espn_cbb._get(f"{SITE}/scoreboard?dates={day}&groups=80&limit=300")
    if not isinstance(data, dict) or "events" not in data:
        return None
    out = []
    for e in data.get("events") or []:
        g = espn_cbb.parse_event(e)
        if g:
            g["home_1h"] = g["away_1h"] = None   # quarter 1 is not a half
            out.append(g)
    return out


def summary(event_id: str) -> dict:
    return parse_box(espn_cbb._get(f"{SITE}/summary?event={event_id}"))


def fpi(season: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    page, pages = 1, 1
    while page <= pages and page <= 3:
        data = espn_cbb._get(f"{FPI}?season={season}&limit=300&page={page}")
        out.update(parse_power(data, "fpi"))
        pages = int(((data or {}).get("pagination") or {}).get("pages") or 1)
        page += 1
    return out


def _fx_summary():
    def stats(yds, rush_att, comp_att, tov):
        return [{"name": "totalYards", "displayValue": str(yds)},
                {"name": "completionAttempts", "displayValue": comp_att},
                {"name": "rushingAttempts", "displayValue": str(rush_att)},
                {"name": "turnovers", "displayValue": str(tov)}]
    return {
        "boxscore": {"teams": [
            {"team": {"id": "194"}, "homeAway": "home",
             "statistics": stats(445, 41, "17/21", 1)},
            {"team": {"id": "130"}, "homeAway": "away",
             "statistics": stats(300, 30, "20-35", 2)}]},
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "194"}, "score": "23"},
            {"homeAway": "away", "team": {"id": "130"}, "score": "34"}]}]},
    }


def _self_test() -> None:
    b = parse_box(_fx_summary())
    assert b["194"] == {"pts": 23, "yds": 445, "plays": 62, "tov": 1}, b["194"]
    # ESPN writes completions/attempts with "/" or "-": both read.
    assert b["130"]["plays"] == 65 and b["130"]["tov"] == 2
    assert parse_box({}) == {}
    assert "_odds" not in b, "no line in the summary, nothing claimed"
    # The summary keeps the game's line (pickcenter) after the scoreboard
    # has dropped it: that is what fills ATS for games already played.
    fx = _fx_summary()
    fx["header"]["competitions"][0]["competitors"][0]["team"]["abbreviation"] = "OSU"
    fx["header"]["competitions"][0]["competitors"][1]["team"]["abbreviation"] = "MICH"
    fx["pickcenter"] = [{"details": "OSU -7.5", "overUnder": 44.5,
                         "homeTeamOdds": {"favorite": True, "moneyLine": -300},
                         "awayTeamOdds": {"favorite": False, "moneyLine": 240}}]
    lined = parse_box(fx)
    assert lined["_odds"] == {"spread_home": -7.5, "ml_home": -300, "ml_away": 240,
                              "total": 44.5}, lined["_odds"]
    assert lined["194"]["yds"] == 445, "the box itself is unchanged"

    fpi = {"categories": [{"name": "fpi", "names": ["fpi", "fpirank", "fpioff"]}],
           "teams": [
               {"team": {"id": "194"}, "categories": [{"name": "fpi", "values": [24.1, 1.0, 12.0]}]},
               {"team": {"id": "130"}, "categories": [{"name": "fpi", "values": [-3.5, 71.0, 1.0]}]}]}
    assert parse_power(fpi) == {"194": {"rating": 24.1, "rank": 1},
                                "130": {"rating": -3.5, "rank": 71}}
    # No rank column: rank by rating.
    fpi["categories"][0]["names"] = ["fpi", "fpioff", "fpidef"]
    assert parse_power(fpi)["130"]["rank"] == 2
    assert parse_power({}) == {}

    print("espn_cfb self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
