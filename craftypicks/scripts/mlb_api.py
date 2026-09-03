"""Client for MLB's free StatsAPI — probable starters, game logs, team rates.

Named `screen_mlb.py` until 2026-08-28, which was wrong in a way that nearly
cost us: it is not a screen, and four modules depend on it for data. It was
renamed so that retiring the strikeout screens cannot take the MLB board and
the pitcher props down with them.

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
                        "hand": (pitcher.get("pitchHand") or {}).get("code", ""),
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


def parse_hands(payload) -> dict[int, str]:
    """Pitcher id -> "L" / "R" / "". A person with no pitchHand is blank."""
    out = {}
    for person in (payload or {}).get("people", []) or []:
        pid = person.get("id")
        if pid is None:
            continue
        out[int(pid)] = (person.get("pitchHand") or {}).get("code") or ""
    return out


def pitch_hands(pitcher_ids) -> dict[int, str]:
    """Which way each of these pitchers throws. One free request for the slate.

    Not folded into probable_starters(): the schedule's probablePitcher
    hydration carries no pitchHand at all, which is why every card's
    home_hand has been an empty string since the board shipped. Asking per
    pitcher would be a request each; /people takes the whole day at once.
    """
    ids = sorted({int(p) for p in pitcher_ids if p})
    if not ids:
        return {}
    return parse_hands(_get("/people", personIds=",".join(str(i) for i in ids)))


# The last-ten record hides among sixteen split records; this is its type.
LAST_TEN = "lastTen"


def parse_standings(payload) -> dict[int, dict]:
    """Team id -> record, streak and last ten."""
    out = {}
    for record in (payload or {}).get("records", []) or []:
        for tr in record.get("teamRecords", []) or []:
            tid = (tr.get("team") or {}).get("id")
            if tid is None:
                continue
            last10 = {}
            for sr in ((tr.get("records") or {}).get("splitRecords") or []):
                if sr.get("type") == LAST_TEN:
                    last10 = sr
                    break
            out[int(tid)] = {
                "w": int(tr.get("wins") or 0),
                "l": int(tr.get("losses") or 0),
                "streak": (tr.get("streak") or {}).get("streakCode") or "",
                "l10_w": int(last10.get("wins") or 0),
                "l10_l": int(last10.get("losses") or 0),
            }
    return out


def standings(season: int, date_str: str) -> dict[int, dict]:
    """The table as it stood on the MORNING of date_str (YYYY-MM-DD).

    Verified: date=2026-09-01 returns the Padres at 73-65, which is what the
    board recorded at 9am that day; date=2026-08-31 returns 72-65. So the
    board passes its own date and gets the table its reader expects, with
    that evening's games still unplayed.

    One free request covers all thirty clubs across both leagues.
    """
    return parse_standings(_get("/standings", leagueId="103,104",
                                season=season, date=date_str,
                                standingsTypes="regularSeason"))


def parse_series(payload) -> list[dict]:
    """Completed meetings, oldest first."""
    out = []
    for day in (payload or {}).get("dates", []) or []:
        date = day.get("date") or ""
        for game in day.get("games", []) or []:
            if (game.get("status") or {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams") or {}
            away, home = teams.get("away") or {}, teams.get("home") or {}
            a_id = (away.get("team") or {}).get("id")
            h_id = (home.get("team") or {}).get("id")
            if a_id is None or h_id is None:
                continue
            out.append({
                "date": date or (game.get("gameDate") or "")[:10],
                "away_id": int(a_id), "away_runs": int(away.get("score") or 0),
                "home_id": int(h_id), "home_runs": int(home.get("score") or 0),
            })
    out.sort(key=lambda g: g["date"])
    return out


def season_series(team_id: int, opponent_id: int, season: int,
                  through: str) -> list[dict]:
    """Regular-season meetings on or before `through` (YYYY-MM-DD).

    gameType="R" is not optional. Without it the Padres-Reds series came back
    with an extra game and the first was a 14-3 exhibition on 8 March 2026.
    The runner probe checks for a March game precisely to catch its removal.
    """
    return parse_series(_get("/schedule", sportId=1, gameType="R",
                             startDate=f"{season}-01-01", endDate=through,
                             teamId=team_id, opponentId=opponent_id))


# 30 clubs x 2 splits = 60 rows, and this endpoint pages at 50 by default.
# The first read of it in development came back ten rows short with no error
# and no warning; the missing clubs were simply absent.
SPLIT_PAGE_LIMIT = 100


def parse_k_splits(payload) -> dict[int, dict]:
    """Team id -> strikeout rate against each hand.

    A club missing either half is dropped rather than half-reported: a card
    showing a rate against righties and nothing against lefties invites the
    reader to assume the missing one is zero.
    """
    splits = (((payload or {}).get("stats") or [{}])[0] or {}).get("splits") or []
    out: dict[int, dict] = {}
    for split in splits:
        tid = (split.get("team") or {}).get("id")
        code = (split.get("split") or {}).get("code")
        stat = split.get("stat") or {}
        pa = stat.get("plateAppearances")
        if tid is None or code not in ("vr", "vl") or not pa:
            continue
        k = float(stat.get("strikeOuts") or 0)
        out.setdefault(int(tid), {})["vR" if code == "vr" else "vL"] = {
            "k_pct": 100.0 * k / float(pa),
            "k": int(k),
            "pa": int(pa),
        }
    return {tid: v for tid, v in out.items() if "vL" in v and "vR" in v}


def team_k_splits(season: int) -> dict[int, dict]:
    """Every club's strikeout rate against right- and left-handers.

    One free request for the whole league. limit is mandatory --
    see SPLIT_PAGE_LIMIT.
    """
    return parse_k_splits(_get("/teams/stats", stats="statSplits",
                               sitCodes="vr,vl", season=season,
                               group="hitting", sportIds=1,
                               limit=SPLIT_PAGE_LIMIT))


def _self_test() -> None:
    """Parsers only. Every fetch is split from its parser so this needs no
    network -- the live endpoints are checked by the probe workflow instead."""
    # ---- handedness. The schedule does not carry pitchHand; /people does.
    people = {"people": [
        {"id": 681190, "fullName": "Randy Vasquez", "pitchHand": {"code": "R"}},
        {"id": 666157, "fullName": "Nick Lodolo", "pitchHand": {"code": "L"}},
        {"id": 999999, "fullName": "No Hand Listed"},
    ]}
    hands = parse_hands(people)
    assert hands[681190] == "R" and hands[666157] == "L", hands
    assert hands[999999] == "", "a missing pitchHand is blank, not a crash"
    assert parse_hands({}) == {} and parse_hands(None) == {}

    # ---- standings: the last ten hides among sixteen splitRecords.
    st = {"records": [{"teamRecords": [
        {"team": {"id": 135}, "wins": 73, "losses": 65,
         "streak": {"streakCode": "W1"},
         "records": {"splitRecords": [
             {"type": "home", "wins": 41, "losses": 28},
             {"type": "lastTen", "wins": 5, "losses": 5}]}},
        {"team": {"id": 113}, "wins": 65, "losses": 73,
         "streak": {"streakCode": "L1"},
         "records": {"splitRecords": [{"type": "lastTen",
                                       "wins": 4, "losses": 6}]}}]}]}
    table = parse_standings(st)
    assert table[135] == {"w": 73, "l": 65, "streak": "W1",
                          "l10_w": 5, "l10_l": 5}, table[135]
    assert table[113]["streak"] == "L1"
    bare = parse_standings({"records": [{"teamRecords": [
        {"team": {"id": 1}, "wins": 1, "losses": 2,
         "streak": {}, "records": {}}]}]})
    assert bare[1] == {"w": 1, "l": 2, "streak": "",
                       "l10_w": 0, "l10_l": 0}, bare
    assert parse_standings(None) == {}

    # ---- the season series. Only finals, oldest first.
    sched = {"dates": [
        {"date": "2026-08-31", "games": [{
            "status": {"abstractGameState": "Final"},
            "teams": {"away": {"team": {"id": 135}, "score": 5},
                      "home": {"team": {"id": 113}, "score": 0}}}]},
        {"date": "2026-06-08", "games": [{
            "status": {"abstractGameState": "Final"},
            "teams": {"away": {"team": {"id": 113}, "score": 2},
                      "home": {"team": {"id": 135}, "score": 6}}}]},
        {"date": "2026-09-02", "games": [{
            "status": {"abstractGameState": "Preview"},
            "teams": {"away": {"team": {"id": 135}, "score": None},
                      "home": {"team": {"id": 113}, "score": None}}}]}]}
    series = parse_series(sched)
    assert [g["date"] for g in series] == ["2026-06-08", "2026-08-31"], series
    assert series[0]["home_id"] == 135 and series[0]["home_runs"] == 6
    assert series[1]["away_runs"] == 5
    assert len(series) == 2, "a Preview game is not a result"
    assert parse_series({}) == []

    # ---- K% splits. Real 2026 figures, so these are checkable on the site.
    raw = {"stats": [{"splits": [
        {"team": {"id": 113}, "split": {"code": "vr"},
         "stat": {"strikeOuts": 1015, "plateAppearances": 3989}},
        {"team": {"id": 113}, "split": {"code": "vl"},
         "stat": {"strikeOuts": 307, "plateAppearances": 1230}},
        {"team": {"id": 141}, "split": {"code": "vr"},
         "stat": {"strikeOuts": 693, "plateAppearances": 3665}},
        {"team": {"id": 141}, "split": {"code": "vl"},
         "stat": {"strikeOuts": 311, "plateAppearances": 1510}},
        {"team": {"id": 999}, "split": {"code": "vr"},
         "stat": {"strikeOuts": 1, "plateAppearances": 10}}]}]}
    ks = parse_k_splits(raw)
    assert round(ks[113]["vR"]["k_pct"], 1) == 25.4, ks[113]
    assert ks[113]["vR"]["pa"] == 3989
    assert ks[113]["vR"]["k"] == 1015, "the raw count is kept so the combined "\
                                       "rate can be summed rather than averaged"
    assert round(ks[141]["vL"]["k_pct"], 1) == 20.6, ks[141]
    assert 999 not in ks, "a club with only one of the two splits is dropped"
    assert parse_k_splits({}) == {}

    print("mlb_api self-test: every parser holds")


if __name__ == "__main__":
    _self_test()
