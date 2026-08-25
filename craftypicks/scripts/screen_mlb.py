"""MLB Stats API for the screen system. Free, no key, no scraping.

Ported from the V2.2 project to stdlib urllib so the repo keeps its
zero-dependency property — GitHub Actions installs nothing, which is one
less thing that can break at 9am.

The expensive call is vs_roster(): one request per batter. Callers must
gate it behind the cheap filters, which is what screen_source does.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://statsapi.mlb.com/api/v1"
PAUSE = 0.12
_cache: dict = {}


def _get(path: str, **params):
    key = (path, tuple(sorted(params.items())))
    if key in _cache:
        return _cache[key]
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "craftypicks-screens/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        _cache[key] = None
        return None
    _cache[key] = data
    time.sleep(PAUSE)
    return data


def probable_starters(date_str: str) -> list[dict]:
    """Today's probable pitchers. date_str is MM/DD/YYYY."""
    data = _get("/schedule", sportId=1, date=date_str,
                hydrate="probablePitcher,team") or {}
    out = []
    for day in data.get("dates", []):
        for game in day.get("games", []):
            teams = game.get("teams", {})
            for side, other in (("home", "away"), ("away", "home")):
                pitcher = (teams.get(side) or {}).get("probablePitcher")
                if not pitcher:
                    continue
                try:
                    out.append({
                        "pitcher_id": pitcher["id"],
                        "name": pitcher.get("fullName", "?"),
                        "team": teams[side]["team"].get("abbreviation")
                                or teams[side]["team"]["name"],
                        "team_id": teams[side]["team"]["id"],
                        "opponent": teams[other]["team"].get("abbreviation")
                                    or teams[other]["team"]["name"],
                        "opponent_id": teams[other]["team"]["id"],
                        "game_time": game.get("gameDate", ""),
                    })
                except (KeyError, TypeError):
                    continue
    return out


def pitcher_season(pitcher_id: int, season: int) -> dict:
    """Season K%, K/9 and innings. K% is strikeouts / batters faced."""
    data = _get(f"/people/{pitcher_id}/stats", stats="season",
                season=season, group="pitching") or {}
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    if not splits:
        return {"k_pct": None, "k_per_9": None, "innings": 0.0}
    s = splits[0].get("stat", {})
    bf = s.get("battersFaced") or 0
    k = s.get("strikeOuts") or 0
    ip = _innings(s.get("inningsPitched"))
    return {
        "k_pct": (k / bf) if bf else None,
        "k_per_9": (k * 9 / ip) if ip else None,
        "innings": ip,
    }


def _innings(value) -> float:
    """StatsAPI writes innings as 5.1 / 5.2 meaning 5⅓ / 5⅔, not 5.1 decimal."""
    if value is None:
        return 0.0
    whole, _, thirds = str(value).partition(".")
    try:
        return float(whole) + (float(thirds or 0) / 3.0)
    except ValueError:
        return 0.0


def team_k_per_game(team_id: int, season: int) -> float | None:
    """How often the opposing lineup strikes out per game."""
    data = _get(f"/teams/{team_id}/stats", stats="season",
                season=season, group="hitting") or {}
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    if not splits:
        return None
    s = splits[0].get("stat", {})
    games = s.get("gamesPlayed") or 0
    k = s.get("strikeOuts") or 0
    return (k / games) if games else None


def team_roster(team_id: int, season: int) -> list[int]:
    """Active roster, position players only."""
    data = _get(f"/teams/{team_id}/roster", rosterType="active", season=season) or {}
    return [p["person"]["id"] for p in data.get("roster", [])
            if (p.get("position") or {}).get("abbreviation") != "P"]


def vs_batter(pitcher_id: int, batter_id: int, season: int):
    data = _get(f"/people/{pitcher_id}/stats", stats="vsPlayerTotal",
                group="hitting", opposingPlayerId=batter_id, season=season)
    if not data:
        return None
    for block in data.get("stats", []):
        for split in block.get("splits", []):
            s = split.get("stat", {})
            if s.get("plateAppearances"):
                return s
    return None


def vs_roster(pitcher_id: int, opponent_team_id: int, season: int):
    """Career line against the whole opposing roster. One call per batter."""
    from screen_models import VsRoster
    agg = VsRoster()
    for batter_id in team_roster(opponent_team_id, season):
        s = vs_batter(pitcher_id, batter_id, season)
        if not s:
            continue
        agg.pa += s.get("plateAppearances", 0) or 0
        agg.k += s.get("strikeOuts", 0) or 0
        agg.ab += s.get("atBats", 0) or 0
        agg.h += s.get("hits", 0) or 0
        agg.doubles += s.get("doubles", 0) or 0
        agg.triples += s.get("triples", 0) or 0
        agg.hr += s.get("homeRuns", 0) or 0
        agg.bb += s.get("baseOnBalls", 0) or 0
        agg.hbp += s.get("hitByPitch", 0) or 0
        agg.sf += s.get("sacFlies", 0) or 0
        agg.batters_seen += 1
    return agg
