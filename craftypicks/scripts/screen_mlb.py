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
        return {"k_pct": None, "k_per_9": None, "innings": 0.0, "era": None}
    s = splits[0].get("stat", {})
    bf = s.get("battersFaced") or 0
    k = s.get("strikeOuts") or 0
    ip = _innings(s.get("inningsPitched"))
    try:
        era = float(s.get("era")) if s.get("era") not in (None, "-.--") else None
    except (TypeError, ValueError):
        era = None
    return {
        "k_pct": (k / bf) if bf else None,
        "k_per_9": (k * 9 / ip) if ip else None,
        "innings": ip,
        "era": era,
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


def team_index(season: int) -> dict:
    """{normalised team name: mlb team id}, for joining odds-feed names."""
    data = _get("/teams", sportId=1, season=season) or {}
    out = {}
    for team in data.get("teams", []):
        tid = team.get("id")
        for label in (team.get("name"), team.get("teamName"),
                      team.get("clubName"), team.get("shortName")):
            if label and tid:
                out[str(label).strip().lower()] = tid
    return out



# --------------------------------------------------- pitcher vs one opponent
def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _get_reporting(path: str, **params):
    """Like _get, but says why it failed. Used only by the vs-opponent probe,
    where a silent None is the difference between 'never faced them' and
    'we're calling this endpoint wrong'."""
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "craftypicks-screens/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:180]
        except Exception:                                    # noqa: BLE001
            pass
        return None, f"HTTP {e.code} {body}"
    except (urllib.error.URLError, TimeoutError) as e:
        return None, f"{type(e).__name__}: {e}"
    except json.JSONDecodeError:
        return None, "response was not JSON"


def _totals(rows: list) -> dict | None:
    """Sum however many appearance rows into one line."""
    starts = innings = earned = strikeouts = 0.0
    for sp in rows:
        s = sp.get("stat") or {}
        starts += _num(s.get("gamesStarted"))
        innings += _innings(s.get("inningsPitched"))
        earned += _num(s.get("earnedRuns"))
        strikeouts += _num(s.get("strikeOuts"))
    if innings <= 0:
        return None
    return {"starts": int(starts), "innings": round(innings, 1),
            "era": round(earned * 9 / innings, 2), "strikeouts": int(strikeouts)}


# The vsTeam split family is the direct way to ask this question, but the
# exact stat-type and parameter combination that answers is something this
# repo has never been able to verify — statsapi is unreachable from where
# these files get written. So it is tried first and, when it stays silent,
# the same figure is rebuilt from the game log, which is a far more ordinary
# endpoint and filters on an opponent field rather than a query parameter.
_VS_CANDIDATES = [
    {"stats": "vsTeamTotal", "group": "pitching"},
    {"stats": "vsTeam", "group": "pitching"},
    {"stats": "vsTeamTotal", "group": "pitching", "_season": True},
    {"stats": "vsTeam", "group": "pitching", "_season": True},
]
_vs_direct: dict | None = None   # the candidate that answered, once known
_vs_direct_dead = False
_vs_probe_done = False


def _try_direct(pitcher_id: int, opponent_team_id: int, season: int,
                verbose: bool) -> dict | None:
    global _vs_direct, _vs_direct_dead, _vs_probe_done
    if _vs_direct_dead:
        return None

    candidates = [_vs_direct] if _vs_direct else _VS_CANDIDATES
    for cand in candidates:
        params = {k: v for k, v in cand.items() if not k.startswith("_")}
        params.update(opposingTeamId=opponent_team_id, sportId=1)
        if cand.get("_season"):
            params["season"] = season
        data, err = _get_reporting(f"/people/{pitcher_id}/stats", **params)
        rows = []
        for block in (data or {}).get("stats") or []:
            rows.extend(block.get("splits") or [])
        if verbose and not _vs_probe_done:
            label = f"stats={cand['stats']}{'+season' if cand.get('_season') else ''}"
            print(f"      vs-probe {label}: "
                  + (err if err else f"{len(rows)} split(s)"))
        totals = _totals(rows)
        if totals:
            if not _vs_direct:
                _vs_direct = cand
                print(f"   slate: vs-opponent via stats={cand['stats']}")
            return totals

    if not _vs_direct:
        _vs_direct_dead = True
        if verbose:
            print("   slate: vsTeam split gave nothing; using the game log instead")
    _vs_probe_done = True
    return None


def season_game_log(pitcher_id: int, season: int) -> list:
    """Every appearance this season, newest last. Cached per pitcher-season,
    so the vs-opponent line and the last-ten strip share one request."""
    data = _get(f"/people/{pitcher_id}/stats", stats="gameLog",
                group="pitching", season=season, sportId=1)
    rows = []
    for block in (data or {}).get("stats") or []:
        rows.extend(block.get("splits") or [])
    rows.sort(key=lambda sp: str(sp.get("date") or ""))
    return rows


def _from_game_log(pitcher_id: int, opponent_team_id: int,
                   seasons: list[int]) -> dict | None:
    """Rebuild the same line by filtering this pitcher's appearances.

    One request per pitcher-season regardless of opponent, and the season's
    log is cached, so both halves of a matchup share the fetch.
    """
    rows, spanned = [], []
    for year in seasons:
        appearances = season_game_log(pitcher_id, year)
        if appearances:
            spanned.append(year)
        for sp in appearances:
            if (sp.get("opponent") or {}).get("id") == opponent_team_id:
                rows.append(sp)
    totals = _totals(rows)
    if totals and spanned:
        totals["span"] = (f"{min(spanned)}" if min(spanned) == max(spanned)
                          else f"{min(spanned)}–{max(spanned)}")
        totals["source"] = "gameLog"
    return totals


def pitcher_vs_team(pitcher_id: int, opponent_team_id: int, season: int,
                    verbose: bool = True) -> dict | None:
    """This starter's line against tonight's opponent, or None.

    Context for a reader only. It is not an input to the rating and must
    never become one: these samples are small enough that the difference
    between a 2.10 and a 5.40 is usually four innings of luck.
    """
    if not pitcher_id or not opponent_team_id:
        return None
    direct = _try_direct(pitcher_id, opponent_team_id, season, verbose)
    if direct:
        direct.setdefault("source", "vsTeam")
        return direct
    return _from_game_log(pitcher_id, opponent_team_id, [season - 1, season])
